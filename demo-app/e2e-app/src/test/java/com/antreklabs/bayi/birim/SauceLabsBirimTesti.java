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
    assertEquals(o.get("username"), "kullanici");
    assertEquals(o.get("accessKey"), "anahtar");
    assertEquals(o.get("tunnelName"), "tp-1-1-android");
    assertEquals(o.get("build"), "demo-12-sauce");
    assertEquals(o.get("name"), "GirisTesti.dogruBilgilerleGiris");
    assertEquals(o.get("appiumVersion"), "latest");
  }

  @Test(groups = "birim")
  public void kimlikYoksaOturumAcilmaz() {
    assertThrows(IllegalArgumentException.class, () -> SauceLabs.haritadan(Map.of()).secenekler("x"));
    assertThrows(
        IllegalArgumentException.class,
        () -> SauceLabs.haritadan(Map.of("SAUCE_USERNAME", "k")).secenekler("x"));
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
    assertEquals(so.get("username"), "k");
    assertEquals(so.get("name"), "Ad _t_rnak_");
    assertEquals(o.getCapability("appium:app"), "storage:filename=bayi.apk");
  }
}
