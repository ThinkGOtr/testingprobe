package com.antreklabs.bayi.altyapi;

import io.appium.java_client.AppiumBy;
import java.util.List;
import java.util.Map;
import org.openqa.selenium.JavascriptExecutor;
import org.openqa.selenium.SearchContext;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebDriverException;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.remote.RemoteWebElement;

/**
 * Ekran dışındaki öğeyi görünür alana getirme (web'de Playwright bunu eylemde kendisi yapar).
 *
 * <ul>
 *   <li>Android: UiAutomator2 görünmeyen öğeyi ağaçta göstermez; {@code UiScrollable.scrollIntoView}
 *       kaydırarak arar.
 *   <li>iOS: XCUITest ekran dışı öğeyi ağaçta gösterir ({@code visible=false});
 *       {@code mobile: scroll toVisible} ile getirilir.
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
          if (!l.isEmpty() && l.get(0) instanceof RemoteWebElement && !l.get(0).isDisplayed()) {
            ((JavascriptExecutor) surucu)
                .executeScript(
                    "mobile: scroll", Map.of("elementId", ((RemoteWebElement) l.get(0)).getId(), "toVisible", true));
          }
          return;
        default:
          return;
      }
    } catch (WebDriverException e) {
      // kaydırılabilir kap yok / öğe kayboldu: bekleme döngüsü yeniden dener
    }
  }
}
