package com.antreklabs.bayi.birim;

import static com.microsoft.playwright.assertions.PlaywrightAssertions.assertThat;

import com.microsoft.playwright.Browser;
import com.microsoft.playwright.Page;
import com.microsoft.playwright.Playwright;
import org.testng.annotations.Test;

/**
 * Toolchain imajının web + Java ısınma/duman testi (hedef projenin parçası DEĞİLDİR).
 *
 * <p>İmaj derlenirken iki kez kullanılır (toolchain/Dockerfile): ağ açıkken derlenerek çevrimdışı
 * Maven deposunu ısıtır; sonra son imajda AĞSIZ koşar ve şunları kanıtlar: güvenilir pom
 * çevrimdışı çözülüyor, Surefire sağlayıcısı TestNG, Playwright Java sürücüsü (driver +
 * driver-bundle) indirme yapmadan açılıyor ve imajdaki tarayıcıyı ({@code
 * PLAYWRIGHT_BROWSERS_PATH}) başlatıyor.
 */
public class IsinmaTest {
  @Test(groups = {"isinma"})
  public void tarayiciCevrimdisiAcilir() {
    try (Playwright playwright = Playwright.create()) {
      Browser tarayici = playwright.chromium().launch();
      Page sayfa = tarayici.newPage();
      sayfa.setContent("<button data-testid=\"dugme\">Tamam</button>");
      assertThat(sayfa.getByTestId("dugme")).hasText("Tamam");
    }
  }
}
