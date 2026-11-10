package com.antreklabs.bayi.altyapi;

import io.appium.java_client.HasOnScreenKeyboard;
import io.appium.java_client.HidesKeyboard;
import java.util.List;
import java.util.Map;
import org.openqa.selenium.By;
import org.openqa.selenium.JavascriptExecutor;
import org.openqa.selenium.Rectangle;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebDriverException;
import org.openqa.selenium.WebElement;

/**
 * Ekran klavyesi: metin yazıldıktan sonra kapatılır, altındaki butonu (ör. "Sepete ekle",
 * "Giriş yap") örtmesin. Windows'ta ekran klavyesi yoktur.
 *
 * <p>iOS: XCUITest'in {@code hideKeyboard}'u yalnızca klavyedeki bir tuşa ("done" vb.) basarak
 * kapatabilir. Adet alanının sayı klavyesinde (number-pad) böyle bir tuş yoktur; giriş ekranının
 * "next"/"go" tuşları ise eylem tetikler (parolaya geçer / giriş yapar), basılamaz. Bu yüzden iOS'ta
 * uygulamanın kendi kapatma yolu kullanılır: kaydırma kabında kısa bir sürükleme
 * ({@code keyboardDismissMode="on-drag"}, katalog ekranı). Sürükleme kabın kenar boşluğundan
 * (dokunulabilir öğe olmayan şerit) başlar; içerik hafifçe kayar, hedef öğeyi {@link Kaydirma}
 * yeniden görünür alana getirir.
 */
public final class Klavye {

  /** Sürüklemenin başladığı nokta: kabın sol kenarından içeri (kart dışı kenar boşluğu). */
  private static final int KENAR = 4;

  /** Sürükleme mesafesi ve klavyenin üst kenarından uzaklık (pt). */
  private static final int MESAFE = 40;

  private static final int PAY = 16;

  private Klavye() {}

  /** Klavye açıksa kapatır; kapatılamazsa sessizce geçer (sonraki dokunma kendi beklemesini yapar). */
  public static void kapat(WebDriver surucu) {
    if (!(surucu instanceof HidesKeyboard)) {
      return;
    }
    try {
      if (surucu instanceof HasOnScreenKeyboard && !((HasOnScreenKeyboard) surucu).isKeyboardShown()) {
        return;
      }
      if (Kimlik.platform() == Platform.IOS) {
        iosSurukleyerekKapat(surucu);
        return;
      }
      ((HidesKeyboard) surucu).hideKeyboard();
    } catch (WebDriverException e) {
      // klavye kapatılamadı: sonraki eylemin beklemesi (ve kaydırma) devralır
    }
  }

  /**
   * iOS: klavyenin üstünde kalan kaydırma kabında, kenar boşluğundan yukarı kısa bir sürükleme.
   * Sürükleme yapılamazsa (kap yok / klavyenin üstünde yer yok) hiçbir şey yapmaz.
   */
  static void iosSurukleyerekKapat(WebDriver surucu) {
    List<WebElement> klavyeler = surucu.findElements(By.className("XCUIElementTypeKeyboard"));
    if (klavyeler.isEmpty()) {
      return;
    }
    int klavyeUst = klavyeler.get(0).getRect().getY();
    for (WebElement kap : surucu.findElements(By.className("XCUIElementTypeScrollView"))) {
      int[] cizgi = surukleme(kap.getRect(), klavyeUst);
      if (cizgi != null) {
        ((JavascriptExecutor) surucu)
            .executeScript(
                "mobile: dragFromToForDuration",
                Map.of(
                    "duration", 0.2,
                    "fromX", cizgi[0],
                    "fromY", cizgi[1],
                    "toX", cizgi[0],
                    "toY", cizgi[2]));
        return;
      }
    }
  }

  /**
   * Kap ve klavye üst kenarına göre sürükleme çizgisi: {x, başlangıç y, bitiş y}; kabın klavye
   * üstünde kalan bölümü sürüklemeye yetmiyorsa null. Saf hesap (birim testli).
   */
  public static int[] surukleme(Rectangle kap, int klavyeUst) {
    int alt = Math.min(kap.getY() + kap.getHeight(), klavyeUst) - PAY;
    int ust = alt - MESAFE;
    if (kap.getWidth() <= 2 * KENAR || ust <= kap.getY()) {
      return null;
    }
    return new int[] {kap.getX() + KENAR, alt, ust};
  }
}
