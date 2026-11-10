package com.antreklabs.bayi.altyapi;

import java.time.Duration;
import java.util.function.Function;
import java.util.function.Supplier;
import org.openqa.selenium.NoSuchElementException;
import org.openqa.selenium.StaleElementReferenceException;
import org.openqa.selenium.TimeoutException;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.support.ui.FluentWait;

/**
 * Deterministik bekleme: koşul sağlanana ya da üst sınır dolana kadar sorgular.
 *
 * <p>Kurallar (plan §5): yalnızca açık bekleme; örtük bekleme 0; {@code Thread.sleep} yasak.
 * İki hata türü bilerek ayrıdır — triage ve kırarak doğrula buna dayanır:
 * <ul>
 *   <li>{@link #kosul}: eylem ön koşulu (öğe bulunamadı / tıklanamadı) → {@link TimeoutException};
 *       JUnit XML'de {@code <error>} (locator/kurulum hatası).
 *   <li>{@link #dogrula}: beklenen sonuç → {@link AssertionError}; JUnit XML'de {@code <failure>}.
 * </ul>
 */
public final class Bekle {

  /** Sorgu aralığı. */
  public static final Duration ARALIK = Duration.ofMillis(250);

  private final WebDriver surucu;
  private final Duration ustSinir;

  public Bekle(WebDriver surucu, Duration ustSinir) {
    this.surucu = surucu;
    this.ustSinir = ustSinir;
  }

  public Duration ustSinir() {
    return ustSinir;
  }

  private FluentWait<WebDriver> bekleyici(String aciklama) {
    return new FluentWait<>(surucu)
        .withTimeout(ustSinir)
        .pollingEvery(ARALIK)
        .ignoring(NoSuchElementException.class)
        .ignoring(StaleElementReferenceException.class)
        .withMessage(aciklama);
  }

  /**
   * Koşul null/false dışında bir değer döndürene kadar bekler ve o değeri döndürür.
   *
   * @throws TimeoutException süre dolarsa (açıklama mesajda)
   */
  public <T> T kosul(String aciklama, Function<WebDriver, T> kosul) {
    return bekleyici(aciklama).until(kosul::apply);
  }

  /**
   * Beklenen sonuç sağlanana kadar bekler; sağlanmazsa son görülen değerle {@link AssertionError}.
   *
   * @param aciklama beklenti (ör. "cart-total metni")
   * @param beklenen beklenen değerin okunur hali
   * @param gorulen son görülen değeri okur (öğe yoksa "(öğe yok)" döndürmeli)
   * @param saglandi beklenti sağlandı mı
   */
  public void dogrula(String aciklama, String beklenen, Supplier<String> gorulen, Supplier<Boolean> saglandi) {
    try {
      bekleyici(aciklama).until(s -> Boolean.TRUE.equals(saglandi.get()) ? Boolean.TRUE : null);
    } catch (TimeoutException e) {
      String son;
      try {
        son = gorulen.get();
      } catch (RuntimeException okumaHatasi) {
        son = "(okunamadı: " + okumaHatasi.getClass().getSimpleName() + ")";
      }
      throw new AssertionError(
          aciklama + ": beklenen <" + beklenen + ">, görülen <" + son + "> (" + ustSinir.toMillis() + " ms)");
    }
  }
}
