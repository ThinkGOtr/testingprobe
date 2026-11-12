package com.antreklabs.bayi.birim;

import static org.testng.Assert.assertEquals;
import static org.testng.Assert.assertNotNull;

import com.microsoft.playwright.Playwright;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.testng.annotations.Test;

/**
 * Playwright for Java sürüm eşitliği (011 plan §2.5): Java sürücüsünün paketlediği Playwright
 * çekirdeği, depo kökündeki {@code .playwright-version} (npm {@code @playwright/test}) ile AYNI
 * sürümdür — dolayısıyla aynı tarayıcı derlemelerini ({@code browsers.json}) kullanır ve
 * {@code PLAYWRIGHT_BROWSERS_PATH} tek bir tarayıcı önbelleğiyle iki hattı da besler.
 */
public class SurumBirimTesti {

  private static final Pattern SURUM = Pattern.compile("\"version\"\\s*:\\s*\"([^\"]+)\"");

  static String kaynak(String yol) throws IOException {
    try (InputStream in = Playwright.class.getClassLoader().getResourceAsStream(yol)) {
      assertNotNull(in, "sınıf yolunda yok: " + yol + " (com.microsoft.playwright:driver)");
      return new String(in.readAllBytes(), StandardCharsets.UTF_8);
    }
  }

  @Test(groups = "birim")
  public void surucuCekirdegiPlaywrightSurumuyleAyni() throws IOException {
    String beklenen = Files.readString(Path.of("../../.playwright-version"), StandardCharsets.UTF_8).trim();
    Matcher m = SURUM.matcher(kaynak("driver/package/package.json"));
    assertNotNull(m.find() ? m.group(1) : null, "driver package.json sürümü okunamadı");
    assertEquals(m.group(1), beklenen,
        "Playwright for Java sürücüsü (pom playwright.version) .playwright-version ile aynı çekirdeği paketlemeli");
  }

  @Test(groups = "birim")
  public void tsBagimliligiAyni() throws IOException {
    String beklenen = Files.readString(Path.of("../../.playwright-version"), StandardCharsets.UTF_8).trim();
    String pkg = Files.readString(Path.of("../e2e/package.json"), StandardCharsets.UTF_8);
    Matcher m = Pattern.compile("\"@playwright/test\"\\s*:\\s*\"([^\"]+)\"").matcher(pkg);
    assertEquals(m.find() ? m.group(1) : null, beklenen);
  }
}
