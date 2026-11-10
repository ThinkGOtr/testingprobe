package com.antreklabs.bayi.altyapi;

import io.appium.java_client.AppiumBy;
import java.util.List;
import java.util.Map;
import org.openqa.selenium.By;
import org.openqa.selenium.JavascriptExecutor;
import org.openqa.selenium.Rectangle;
import org.openqa.selenium.SearchContext;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebDriverException;
import org.openqa.selenium.WebElement;

/**
 * Ekran dışındaki öğeyi görünür alana getirme (web'de Playwright bunu eylemde kendisi yapar).
 *
 * <ul>
 *   <li>Android: UiAutomator2 görünmeyen öğeyi ağaçta göstermez; {@code UiScrollable.scrollIntoView}
 *       kaydırarak arar.
 *   <li>iOS: XCUITest ekran dışı öğeyi ağaçta gösterir ({@code visible=false}). WDA'nın
 *       {@code mobile: scroll} komutu RN ScrollView'da işe yaramaz ({@code toVisible} yalnız tablo
 *       hücrelerini tanır: "max scroll count reached"; {@code direction} hiç kaydırmaz — iOS 18.5
 *       simülatörü, Xcode 27.2). Bunun yerine kaydırma kabında, öğenin bulunduğu yöne kısa bir
 *       sürükleme yapılır (kenar boşluğundan). Klavyenin altında kalan öğe de "aşağıda" sayılır:
 *       sürükleme içeriği yukarı taşır, {@code keyboardDismissMode="on-drag"} klavyeyi kapatır.
 *   <li>Windows: masaüstü penceresi sabit; kaydırma yok.
 * </ul>
 *
 * <p>Bu sınıf beklemez: bekleme döngüsünün ({@link Bekle}) her turunda bir kez denenir.
 */
public final class Kaydirma {

  private Kaydirma() {}

  /**
   * Android'de kaydırarak arayan UiScrollable ifadesi.
   *
   * @param kapsayici kapsayıcı kimlik (ör. ürün kartı); yoksa null
   * @param id aranan kimlik
   */
  public static String androidKaydirmaIfadesi(Kimlik.Strateji strateji, String kapsayici, String id) {
    String hedef =
        kapsayici == null
            ? Kimlik.uiSelector(strateji, id)
            : Kimlik.uiSelector(strateji, kapsayici) + ".childSelector(" + Kimlik.uiSelector(strateji, id) + ")";
    return "new UiScrollable(new UiSelector().scrollable(true)).scrollIntoView(" + hedef + ")";
  }

  /** Kimliği (kapsayıcı içinde) görünür alana getirmeyi bir kez dener. */
  public static void getir(WebDriver surucu, String kapsayici, String id) {
    try {
      switch (Kimlik.platform()) {
        case ANDROID:
          surucu.findElements(
              AppiumBy.androidUIAutomator(androidKaydirmaIfadesi(Kimlik.etkinStrateji(), kapsayici, id)));
          return;
        case IOS:
          SearchContext kok = surucu;
          if (kapsayici != null) {
            List<WebElement> k = surucu.findElements(Kimlik.bul(kapsayici));
            if (k.isEmpty()) {
              return;
            }
            kok = k.get(0);
          }
          List<WebElement> l = kok.findElements(Kimlik.bul(id));
          if (!l.isEmpty() && !l.get(0).isDisplayed()) {
            iosSurukle(surucu, l.get(0).getRect());
          }
          return;
        default:
          return;
      }
    } catch (WebDriverException e) {
      // kaydırılabilir kap yok / öğe kayboldu: bekleme döngüsü yeniden dener
    }
  }

  /** Sürüklemenin başladığı x: kabın sol kenarından içeri (dokunulabilir öğe olmayan kenar boşluğu). */
  private static final int KENAR = 4;

  /** iOS: hedefe doğru, görünür en yüksek kaydırma kabında bir sürükleme. */
  private static void iosSurukle(WebDriver surucu, Rectangle hedef) {
    Rectangle kap = null;
    for (WebElement k : surucu.findElements(By.className("XCUIElementTypeScrollView"))) {
      Rectangle r = k.getRect();
      if (k.isDisplayed() && (kap == null || r.getHeight() > kap.getHeight())) {
        kap = r;
      }
    }
    int[] c = kap == null ? null : iosSurukleme(kap, hedef);
    if (c != null) {
      ((JavascriptExecutor) surucu)
          .executeScript(
              "mobile: dragFromToForDuration",
              Map.of("duration", 0.2, "fromX", c[0], "fromY", c[1], "toX", c[0], "toY", c[2]));
    }
  }

  /**
   * iOS sürükleme çizgisi {x, başlangıç y, bitiş y}: hedef kabın üstündeyse aşağı (içerik aşağı
   * iner), değilse — kabın altında ya da kap içinde ama örtülü (klavye) — yukarı. Mesafe kap
   * yüksekliğinin %40'ı; ivmeyle içerik ~%55-60 kayar, kabın hemen altındaki öğe kabın üstünden
   * taşmaz. Kap sürüklemeye yetmeyecek kadar küçükse null. Saf hesap (birim testli).
   */
  public static int[] iosSurukleme(Rectangle kap, Rectangle hedef) {
    int h = kap.getHeight();
    if (h < 50 || kap.getWidth() <= 2 * KENAR) {
      return null;
    }
    int alt = kap.getY() + h * 3 / 4;
    int ust = kap.getY() + h * 7 / 20;
    int x = kap.getX() + KENAR;
    boolean ustte = hedef.getY() + hedef.getHeight() <= kap.getY();
    return ustte ? new int[] {x, ust, alt} : new int[] {x, alt, ust};
  }
}
