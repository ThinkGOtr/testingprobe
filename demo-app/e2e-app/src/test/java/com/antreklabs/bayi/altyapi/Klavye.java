package com.antreklabs.bayi.altyapi;

import io.appium.java_client.HasOnScreenKeyboard;
import io.appium.java_client.HidesKeyboard;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.openqa.selenium.By;
import org.openqa.selenium.JavascriptExecutor;
import org.openqa.selenium.Rectangle;
import org.openqa.selenium.StaleElementReferenceException;
import org.openqa.selenium.TimeoutException;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebDriverException;
import org.openqa.selenium.WebElement;
import org.openqa.selenium.support.ui.FluentWait;

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

  /** Sürükleme mesafesi (pt). */
  private static final int MESAFE = 40;

  /**
   * Klavye öğesinin üst kenarından uzaklık (pt). iOS 27'de klavyenin görünen (cam) kabı
   * {@code XCUIElementTypeKeyboard} çerçevesinin ~17 pt üstünden başlar, metin klavyesinde öneri
   * şeridi (~44 pt) da çerçevenin dışındadır; eski 16 pt pay sürüklemeyi klavyeye düşürüyordu
   * (number-pad açık kalıyor, metin klavyesinde 'q' yazılıyordu). 72 pt ikisini de aşar.
   */
  private static final int PAY = 72;

  /**
   * Sürükleme kabın ÜST bölümünde başlar (kap üstünden en çok bu kadar aşağıda): klavye çerçevesi
   * açılış animasyonunda bayat okunabiliyor (oturmuş görünen y=764, gerçekte 550); yalnız çerçeveye
   * göre hesaplanan nokta tuşlara düşüp karakter ekliyordu ("bayi1" → "bayi1q", adet 1 → 14). Kabın
   * üst bölümü telefonda klavyenin hiçbir zaman örtmediği yerdir.
   */
  private static final int UST_BOSLUK = 96;

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

  /** Klavye açılış animasyonunun oturması için en çok deneme ve aralık (ms). */
  private static final int OTURMA_DENEME = 12;

  private static final long OTURMA_ARALIK_MS = 150;

  /** Sürükleme sonrası klavye hâlâ açıksa en çok bu kadar kez yeniden denenir. */
  private static final int KAPATMA_DENEME = 3;

  /**
   * iOS: klavyenin üstünde kalan kaydırma kabında, kenar boşluğundan yukarı kısa bir sürükleme.
   * Klavyenin üst kenarı açılış animasyonu bitince okunur: yazıdan hemen sonra çerçeve hâlâ ekranın
   * altından yükselirken (ör. y=764, oturunca 567) okunursa sürükleme klavye tuşlarına düşer — tuşa
   * basar (adet değişir), klavye açık kalır. Klavye kapanmadıysa yeniden dener. Sürükleme
   * yapılamazsa (kap yok / klavyenin üstünde yer yok) hiçbir şey yapmaz.
   */
  static void iosSurukleyerekKapat(WebDriver surucu) {
    for (int deneme = 0; deneme < KAPATMA_DENEME; deneme++) {
      Integer klavyeUst = oturmusKlavyeUst(surucu);
      if (klavyeUst == null || !surukle(surucu, klavyeUst)) {
        return;
      }
      if (oturmusKlavyeUst(surucu) == null
          || (surucu instanceof HasOnScreenKeyboard
              && !((HasOnScreenKeyboard) surucu).isKeyboardShown())) {
        return;
      }
    }
  }

  /** Klavye çerçevesinin üst kenarı, art arda iki okumada aynı kalınca; klavye yoksa null. */
  private static Integer oturmusKlavyeUst(WebDriver surucu) {
    int[] onceki = {-1};
    try {
      return new FluentWait<>(surucu)
          .withTimeout(Duration.ofMillis(OTURMA_DENEME * OTURMA_ARALIK_MS))
          .pollingEvery(Duration.ofMillis(OTURMA_ARALIK_MS))
          .ignoring(StaleElementReferenceException.class)
          .until(
              d -> {
                List<WebElement> klavyeler = d.findElements(By.className("XCUIElementTypeKeyboard"));
                if (klavyeler.isEmpty()) {
                  return Optional.<Integer>empty();
                }
                int ust = klavyeler.get(0).getRect().getY();
                boolean oturdu = onceki[0] == ust;
                onceki[0] = ust;
                return oturdu ? Optional.of(ust) : null;
              })
          .orElse(null);
    } catch (TimeoutException e) {
      return onceki[0] < 0 ? null : onceki[0];
    }
  }

  private static boolean surukle(WebDriver surucu, int klavyeUst) {
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
        return true;
      }
    }
    return false;
  }

  /**
   * Kap ve klavye üst kenarına göre sürükleme çizgisi: {x, başlangıç y, bitiş y}; kabın klavye
   * üstünde kalan bölümü sürüklemeye yetmiyorsa null. Saf hesap (birim testli).
   */
  public static int[] surukleme(Rectangle kap, int klavyeUst) {
    int alt = Math.min(kap.getY() + UST_BOSLUK, Math.min(kap.getY() + kap.getHeight(), klavyeUst) - PAY);
    int ust = alt - MESAFE;
    if (kap.getWidth() <= 2 * KENAR || ust <= kap.getY()) {
      return null;
    }
    return new int[] {kap.getX() + KENAR, alt, ust};
  }

  /**
   * Okunan alan değeri yazılan metni tutuyor mu. Okunamayan / boş değer (ör. Android parola alanı)
   * doğrulanamaz sayılır ve kabul edilir; maskeli değerde (•••) yalnız uzunluk karşılaştırılır.
   */
  public static boolean degerTutuyor(String okunan, String metin) {
    if (okunan == null || okunan.isEmpty()) {
      return true;
    }
    if (okunan.chars().allMatch(c -> c == '•' || c == '●' || c == '*')) {
      return okunan.length() == metin.length();
    }
    return bosluklar(okunan).equals(bosluklar(metin));
  }

  private static String bosluklar(String s) {
    return s.replace('\u00a0', ' ').replace('\u202f', ' ').replaceAll("\\s+", " ").trim();
  }
}
