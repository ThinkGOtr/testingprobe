package com.antreklabs.bayi.birim;

import static org.testng.Assert.assertEquals;
import static org.testng.Assert.assertFalse;
import static org.testng.Assert.assertThrows;
import static org.testng.Assert.assertTrue;

import com.antreklabs.bayi.altyapi.Ayarlar;
import com.antreklabs.bayi.altyapi.Platform;
import com.antreklabs.bayi.altyapi.SauceLabs;
import com.antreklabs.bayi.altyapi.SurucuFabrikasi;
import io.appium.java_client.remote.options.BaseOptions;
import java.util.Map;
import org.testng.annotations.Test;

/** Sauce Labs sanal cihaz oturumu seçenekleri — cihaz ve ağ gerekmez. */
public class SauceLabsBirimTesti {

  @Test(groups = "birim")
  public void sauceAdresiYalnizHttpsSaucelabs() {
    assertTrue(SauceLabs.sauceAdresi("https://ondemand.eu-central-1.saucelabs.com/wd/hub"));
    assertTrue(SauceLabs.sauceAdresi("https://ondemand.us-west-1.saucelabs.com:443/wd/hub"));
    assertFalse(SauceLabs.sauceAdresi("http://ondemand.eu-central-1.saucelabs.com/wd/hub"));
    assertFalse(SauceLabs.sauceAdresi("https://saucelabs.com.evil.example/wd/hub"));
    assertFalse(SauceLabs.sauceAdresi("http://127.0.0.1:4723"));
    assertFalse(SauceLabs.sauceAdresi("geçersiz adres"));
  }

  @Test(groups = "birim")
  public void seceneklerKimlikTunelDerlemeAd() {
    SauceLabs s =
        SauceLabs.haritadan(
            Map.of(
                "SAUCE_USERNAME", "kullanici",
                "SAUCE_ACCESS_KEY", "anahtar",
                "SAUCE_TUNNEL_NAME", "tp-1-1-android",
                "SAUCE_BUILD", "demo-12-sauce"));
    Map<String, Object> o = s.secenekler("GirisTesti.dogruBilgilerleGiris");
    // Kimlik yeteneklerde YOK (oturum hatası yetenekleri günlüğe yazar); Basic başlıkla gider.
    assertFalse(o.containsKey("username"));
    assertFalse(o.containsKey("accessKey"));
    assertFalse(o.toString().contains("anahtar"));
    assertEquals(o.get("tunnelName"), "tp-1-1-android");
    assertEquals(o.get("build"), "demo-12-sauce");
    assertEquals(o.get("name"), "GirisTesti.dogruBilgilerleGiris");
    assertFalse(o.containsKey("appiumVersion"), "sürüm verilmezse Sauce'un önerdiği sürüm");
    assertEquals(
        SauceLabs.haritadan(Map.of("SAUCE_APPIUM_VERSION", "3.8.0")).secenekler("x").get("appiumVersion"), "3.8.0");
  }

  @Test(groups = "birim")
  public void kimlikYoksaOturumAcilmaz() throws Exception {
    java.net.URL u = new java.net.URI("https://ondemand.eu-central-1.saucelabs.com:443/wd/hub").toURL();
    assertThrows(IllegalArgumentException.class, () -> SauceLabs.haritadan(Map.of()).istemci(u));
    assertThrows(IllegalArgumentException.class, () -> SauceLabs.haritadan(Map.of("SAUCE_USERNAME", "k")).istemci(u));
    // Kimlik istemci yapılandırmasında (Basic), URL'de değil.
    io.appium.java_client.AppiumClientConfig c =
        SauceLabs.haritadan(Map.of("SAUCE_USERNAME", "k", "SAUCE_ACCESS_KEY", "gizli")).istemci(u);
    assertEquals(c.baseUrl().toString(), u.toString());
    assertTrue(c.credentials() instanceof org.openqa.selenium.UsernameAndPassword);
    // Filtre Basic başlığını baştan ekler.
    org.openqa.selenium.remote.http.HttpRequest[] giden = new org.openqa.selenium.remote.http.HttpRequest[1];
    c.filter()
        .andFinally(r -> { giden[0] = r; return new org.openqa.selenium.remote.http.HttpResponse(); })
        .execute(new org.openqa.selenium.remote.http.HttpRequest(org.openqa.selenium.remote.http.HttpMethod.POST, "/session"));
    assertEquals(giden[0].getHeader("Authorization"), "Basic " + java.util.Base64.getEncoder().encodeToString("k:gizli".getBytes(java.nio.charset.StandardCharsets.UTF_8)));
  }

  @Test(groups = "birim")
  public void iosHazirWdaTuretilmisVeri() {
    BaseOptions<?> yok = SurucuFabrikasi.secenekler(Platform.IOS, Ayarlar.haritadan(Map.of("app.id", "x"), Map.of()));
    assertEquals(yok.getCapability("appium:usePrebuiltWDA"), null);
    BaseOptions<?> var =
        SurucuFabrikasi.secenekler(Platform.IOS, Ayarlar.haritadan(Map.of("app.id", "x"), Map.of("WDA_DERIVED_DATA", "/tmp/wda")));
    assertEquals(var.getCapability("appium:usePrebuiltWDA"), true);
    assertEquals(var.getCapability("appium:derivedDataPath"), "/tmp/wda");
    assertEquals(yok.getCapability("appium:isHeadless"), null);
    BaseOptions<?> ekransiz =
        SurucuFabrikasi.secenekler(Platform.IOS, Ayarlar.haritadan(Map.of("app.id", "x"), Map.of("IOS_HEADLESS", "1")));
    assertEquals(ekransiz.getCapability("appium:isHeadless"), true);
  }

  @Test(groups = "birim")
  public void sauceStorageBasvurusuDosyaYoluSayilmaz() {
    // Windows'ta Path.of("storage:…") InvalidPathException atar; uzak başvuru olduğu gibi geçmeli.
    for (String v : new String[] {"storage:filename=bayi.apk", "storage:0123-abcd", "https://ornek.test/a.apk"}) {
      assertEquals(Ayarlar.haritadan(Map.of("app.path", v), Map.of()).appPath().orElseThrow(), v);
    }
  }

  @Test(groups = "birim")
  public void uygulaSauceOptionsEkler() {
    Ayarlar a = Ayarlar.haritadan(Map.of("app.path", "storage:filename=bayi.apk", "device.name", "Google Pixel 9 Emulator"), Map.of());
    BaseOptions<?> o = SurucuFabrikasi.secenekler(Platform.ANDROID, a);
    SauceLabs.haritadan(Map.of("SAUCE_USERNAME", "k", "SAUCE_ACCESS_KEY", "a")).uygula(o, "Ad \"tırnak\"");
    @SuppressWarnings("unchecked")
    Map<String, Object> so = (Map<String, Object>) o.getCapability("sauce:options");
    assertFalse(o.toString().contains("accessKey"));
    assertEquals(so.get("name"), "Ad _t_rnak_");
    assertEquals(o.getCapability("appium:app"), "storage:filename=bayi.apk");
  }
}
