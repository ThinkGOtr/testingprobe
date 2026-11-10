package com.antreklabs.bayi.birim;

import static org.testng.Assert.assertEquals;
import static org.testng.Assert.assertFalse;
import static org.testng.Assert.assertThrows;
import static org.testng.Assert.assertTrue;

import com.antreklabs.bayi.altyapi.Ayarlar;
import com.antreklabs.bayi.altyapi.Platform;
import com.antreklabs.bayi.altyapi.SurucuFabrikasi;
import com.antreklabs.bayi.altyapi.TestVerisi;
import io.appium.java_client.remote.options.BaseOptions;
import java.time.Duration;
import java.util.Map;
import java.util.Optional;
import org.openqa.selenium.Capabilities;
import org.testng.annotations.Test;

/** Ayar önceliği, yalıtım kipi ve platform başına Appium seçenekleri — cihaz gerekmez. */
public class AyarlarBirimTesti {

  private static Object yetenek(Capabilities c, String ad) {
    Object v = c.getCapability(ad);
    return v != null ? v : c.getCapability("appium:" + ad);
  }

  @Test(groups = "birim")
  public void ozellikOrtamVarsayilanOnceligi() {
    Ayarlar bos = Ayarlar.haritadan(Map.of(), Map.of());
    assertEquals(bos.appiumUrl(), "http://127.0.0.1:4723");
    assertEquals(bos.demoApiUrl(), "http://127.0.0.1:8081/api");
    assertEquals(bos.bekleme(), Duration.ofSeconds(10));
    assertEquals(bos.testToken(), Optional.empty());
    assertFalse(bos.kampanyaKirik());
    assertThrows(IllegalArgumentException.class, bos::platform);

    Ayarlar ortam = Ayarlar.haritadan(Map.of(), Map.of("PLATFORM", "ios", "DEMO_API_URL", "http://api:8000/", "BREAK_CAMPAIGN", "1"));
    assertEquals(ortam.platform(), Platform.IOS);
    assertEquals(ortam.demoApiUrl(), "http://api:8000");
    assertTrue(ortam.kampanyaKirik());

    Ayarlar ikisi = Ayarlar.haritadan(Map.of("platform", "windows"), Map.of("PLATFORM", "ios"));
    assertEquals(ikisi.platform(), Platform.WINDOWS, "sistem özelliği ortamı ezer");
    assertThrows(IllegalArgumentException.class, () -> Ayarlar.haritadan(Map.of("bekleme.ms", "x"), Map.of()).bekleme());
  }

  @Test(groups = "birim")
  public void yalitimKipi() {
    assertEquals(TestVerisi.kip(Ayarlar.haritadan(Map.of(), Map.of("DEMOAPP_TEST_TOKEN", "t"))), TestVerisi.Kip.SIFIRLAMA);
    assertEquals(TestVerisi.kip(Ayarlar.haritadan(Map.of(), Map.of("TP_E2E_NO_RESET", "1"))), TestVerisi.Kip.YALNIZ_SEPET);
    assertTrue(
        org.testng.Assert.expectThrows(
                IllegalStateException.class,
                () -> TestVerisi.kip(Ayarlar.haritadan(Map.of(), Map.of("BREAK_CAMPAIGN", "1", "TP_E2E_NO_RESET", "1"))))
            .getMessage()
            .contains("BREAK_CAMPAIGN=1 için DEMOAPP_TEST_TOKEN gerekir"));
    assertThrows(IllegalStateException.class, () -> TestVerisi.kip(Ayarlar.haritadan(Map.of(), Map.of())));
  }

  @Test(groups = "birim")
  public void androidSecenekleri() {
    Ayarlar a = Ayarlar.haritadan(Map.of("app.path", "/x/bayi.apk", "device.name", "emulator-5554"), Map.of());
    BaseOptions<?> o = SurucuFabrikasi.secenekler(Platform.ANDROID, a);
    assertEquals(String.valueOf(o.getPlatformName()).toLowerCase(), "android");
    assertEquals(String.valueOf(yetenek(o, "automationName")).toLowerCase(), "uiautomator2");
    assertEquals(yetenek(o, "app"), "/x/bayi.apk");
    assertEquals(yetenek(o, "deviceName"), "emulator-5554");
    assertEquals(yetenek(o, "noReset"), Boolean.FALSE);
    // RN testID öneksiz resource-id'dir; sürücü paket öneki eklememeli. Verilen APK her oturumda kurulur.
    assertEquals(yetenek(o, "disableIdLocatorAutocompletion"), Boolean.TRUE);
    assertEquals(yetenek(o, "enforceAppInstall"), Boolean.TRUE);

    BaseOptions<?> kurulu =
        SurucuFabrikasi.secenekler(
            Platform.ANDROID, Ayarlar.haritadan(Map.of("app.id", "com.antreklabs.bayisiparis", "app.activity", ".MainActivity"), Map.of()));
    assertEquals(yetenek(kurulu, "appPackage"), "com.antreklabs.bayisiparis");
    assertEquals(yetenek(kurulu, "appActivity"), ".MainActivity");
    assertEquals(yetenek(kurulu, "disableIdLocatorAutocompletion"), Boolean.TRUE);
    assertThrows(
        IllegalArgumentException.class, () -> SurucuFabrikasi.secenekler(Platform.ANDROID, Ayarlar.haritadan(Map.of(), Map.of())));
  }

  @Test(groups = "birim")
  public void iosSecenekleri() {
    BaseOptions<?> o =
        SurucuFabrikasi.secenekler(
            Platform.IOS, Ayarlar.haritadan(Map.of("app.path", "/x/Bayi.app", "device.name", "iPhone 16", "platform.version", "18.0"), Map.of()));
    assertEquals(String.valueOf(o.getPlatformName()).toLowerCase(), "ios");
    assertEquals(String.valueOf(yetenek(o, "automationName")).toLowerCase(), "xcuitest");
    assertEquals(yetenek(o, "app"), "/x/Bayi.app");
    assertEquals(yetenek(o, "platformVersion"), "18.0");
    BaseOptions<?> kurulu = SurucuFabrikasi.secenekler(Platform.IOS, Ayarlar.haritadan(Map.of("app.id", "com.antreklabs.bayisiparis"), Map.of()));
    assertEquals(yetenek(kurulu, "bundleId"), "com.antreklabs.bayisiparis");
  }

  @Test(groups = "birim")
  public void windowsSecenekleri() {
    BaseOptions<?> o =
        SurucuFabrikasi.secenekler(
            Platform.WINDOWS,
            Ayarlar.haritadan(Map.of("app.path", "C:\\bayi\\Bayi.exe", "app.args", "--api http://10.0.0.2:8081/api"), Map.of()));
    assertEquals(String.valueOf(o.getPlatformName()).toLowerCase(), "windows");
    assertEquals(yetenek(o, "automationName"), SurucuFabrikasi.NOVA_WINDOWS);
    assertEquals(yetenek(o, "app"), "C:\\bayi\\Bayi.exe");
    assertEquals(yetenek(o, "appArguments"), "--api http://10.0.0.2:8081/api");
    assertEquals(yetenek(o, "appWorkingDir"), null);
    assertThrows(
        IllegalArgumentException.class, () -> SurucuFabrikasi.secenekler(Platform.WINDOWS, Ayarlar.haritadan(Map.of(), Map.of())));
  }

  @Test(groups = "birim")
  public void windowsCalismaDiziniOrtamdan() {
    BaseOptions<?> o =
        SurucuFabrikasi.secenekler(
            Platform.WINDOWS,
            Ayarlar.haritadan(Map.of(), Map.of("APP_PATH", "C:\\tp\\bayi\\BayiSiparis.exe", "APP_WORKDIR", "C:\\tp\\bayi")));
    assertEquals(yetenek(o, "appWorkingDir"), "C:\\tp\\bayi");
  }

  @Test(groups = "birim")
  public void windowsPowershellTirnagiReddedilir() {
    for (Map<String, String> kotu :
        java.util.List.of(
            Map.of("app.path", "C:\\a.exe", "app.args", "--x '; Remove-Item C:\\ -Recurse; '"),
            Map.of("app.path", "C:\\a.exe", "app.args", "--x\n--y"),
            Map.of("app.path", "C:\\a.exe", "app.args", "--x \u2019y"),
            Map.of("app.path", "C:\\a.exe", "app.workdir", "C:\\O'Brien"),
            Map.of("app.path", "C:\\a'b.exe"))) {
      assertThrows(
          IllegalArgumentException.class,
          () -> SurucuFabrikasi.secenekler(Platform.WINDOWS, Ayarlar.haritadan(kotu, Map.of())));
    }
  }

  @Test(groups = "birim")
  public void tokenSecenekleredeYok() {
    Ayarlar a =
        Ayarlar.haritadan(Map.of("app.path", "/x/bayi.apk"), Map.of("DEMOAPP_TEST_TOKEN", "gizli-deger-123"));
    for (Platform p : Platform.values()) {
      BaseOptions<?> o = SurucuFabrikasi.secenekler(p, a);
      assertFalse(o.toJson().toString().contains("gizli-deger-123"), p + " seçenekleri token içeriyor");
    }
  }
}
