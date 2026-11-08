package com.antreklabs.bayi.birim;

import static org.testng.Assert.assertEquals;
import static org.testng.Assert.assertFalse;
import static org.testng.Assert.assertThrows;
import static org.testng.Assert.assertTrue;

import com.antreklabs.bayi.altyapi.Ayarlar;
import com.antreklabs.bayi.altyapi.Kaydirma;
import com.antreklabs.bayi.altyapi.Kimlik;
import com.antreklabs.bayi.altyapi.Platform;
import io.appium.java_client.AppiumBy;
import java.util.Map;
import org.testng.annotations.Test;

/** Kimlik stratejisi platform başına (plan §2.2) — cihaz gerekmez. */
public class KimlikBirimTesti {

  private static Ayarlar ayar(Map<String, String> ozellikler) {
    return Ayarlar.haritadan(ozellikler, Map.of());
  }

  @Test(groups = "birim")
  public void varsayilanStratejiPlanTablosuylaAyni() {
    assertEquals(Kimlik.bul(Platform.ANDROID, "login-username"), AppiumBy.id("login-username"));
    assertEquals(Kimlik.bul(Platform.IOS, "login-username"), AppiumBy.accessibilityId("login-username"));
    assertEquals(Kimlik.bul(Platform.WINDOWS, "login-username"), AppiumBy.accessibilityId("login-username"));
  }

  @Test(groups = "birim")
  public void etkinPlatformKurulunca() {
    Kimlik.kur(Platform.IOS, ayar(Map.of()));
    assertEquals(Kimlik.platform(), Platform.IOS);
    assertEquals(Kimlik.bul("cart-total"), AppiumBy.accessibilityId("cart-total"));
    Kimlik.kur(Platform.ANDROID, ayar(Map.of()));
    assertEquals(Kimlik.bul("cart-total"), AppiumBy.id("cart-total"));
  }

  @Test(groups = "birim")
  public void stratejiAyarlaDegisir() {
    Kimlik.kur(Platform.ANDROID, ayar(Map.of("kimlik.android", "erisilebilirlik")));
    assertEquals(Kimlik.bul("cart-total"), AppiumBy.accessibilityId("cart-total"));
    Kimlik.kur(Platform.ANDROID, ayar(Map.of("kimlik.android", "uiautomator")));
    assertEquals(
        Kimlik.bul("cart-total"),
        AppiumBy.androidUIAutomator("new UiSelector().resourceIdMatches(\"(.+:id/)?cart-total\")"));
    assertThrows(IllegalArgumentException.class, () -> Kimlik.strateji(Platform.IOS, ayar(Map.of("kimlik.ios", "uiautomator"))));
    assertThrows(IllegalArgumentException.class, () -> Kimlik.strateji(Platform.ANDROID, ayar(Map.of("kimlik.android", "xpath"))));
    Kimlik.kur(Platform.ANDROID, ayar(Map.of()));
  }

  @Test(groups = "birim")
  public void onekKimlikKurallari() {
    assertEquals(Kimlik.ekli("product-card-", "P-001"), "product-card-P-001");
    assertThrows(IllegalArgumentException.class, () -> Kimlik.ekli("add-to-cart", "P-001"));
    assertThrows(IllegalArgumentException.class, () -> Kimlik.ekli("product-card-", ""));
    assertThrows(IllegalArgumentException.class, () -> Kimlik.bul(Platform.IOS, " "));
  }

  @Test(groups = "birim")
  public void androidKaydirmaIfadesi() {
    String ifade = Kaydirma.androidKaydirmaIfadesi(Kimlik.Strateji.ID, "product-card-P-004", "add-to-cart");
    assertTrue(ifade.startsWith("new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView("), ifade);
    assertTrue(ifade.contains("(.+:id/)?product-card-P-004\").childSelector("), ifade);
    // Ters bölü yok: \Q…\E Appium'un UiSelector ayrıştırıcısında eşleşmez (cihazda gözlendi).
    assertFalse(ifade.contains("\\"), ifade);
    // Düzenli ifade özel karakterleri sınıfa alınır; ifade yine birebir eşleşir.
    assertEquals(Kimlik.uiSelector(Kimlik.Strateji.ID, "a.b(c)"), "new UiSelector().resourceIdMatches(\"(.+:id/)?a[.]b[(]c[)]\")");
    assertTrue(java.util.regex.Pattern.matches("(.+:id/)?a[.]b[(]c[)]", "com.x:id/a.b(c)"));
    String erisim = Kaydirma.androidKaydirmaIfadesi(Kimlik.Strateji.ERISILEBILIRLIK, null, "cart-total");
    assertTrue(erisim.endsWith("scrollIntoView(new UiSelector().description(\"cart-total\"))"), erisim);
  }

  @Test(groups = "birim")
  public void platformCozumu() {
    assertEquals(Platform.coz(" Android "), Platform.ANDROID);
    assertThrows(IllegalArgumentException.class, () -> Platform.coz("web"));
    assertThrows(IllegalArgumentException.class, () -> Platform.coz(null));
  }
}
