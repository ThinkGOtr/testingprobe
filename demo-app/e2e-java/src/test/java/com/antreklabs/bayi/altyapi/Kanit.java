package com.antreklabs.bayi.altyapi;

import com.microsoft.playwright.BrowserContext;
import com.microsoft.playwright.Page;
import com.microsoft.playwright.PlaywrightException;
import com.microsoft.playwright.Tracing;
import io.qameta.allure.Allure;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * Başarısız testin kanıtı: ekran görüntüsü, Playwright trace'i ve sayfa HTML'i.
 *
 * <p>Dosyalar {@code target/kanit/<Sınıf>.<metot>/} altına yazılır ({@code ekran.png},
 * {@code trace.zip}, {@code sayfa.html}; 011 plan §2.5); triage bunları okur (web yöntemi: trace /
 * sayfa.html). Allure raporuna da eklenir. Kanıt toplanamazsa testin asıl hatası gölgelenmez:
 * yalnızca {@code kanit-hatasi.txt} yazılır.
 */
public final class Kanit {

  /** Ekran görüntüsü dosya adı. */
  public static final String EKRAN = "ekran.png";
  /** Playwright trace dosya adı (npx playwright show-trace ile açılır). */
  public static final String TRACE = "trace.zip";
  /** Sayfa HTML'i dosya adı. */
  public static final String SAYFA = "sayfa.html";

  private Kanit() {}

  /** Testin kanıt dizini: güvenli karakterlere indirgenmiş {@code Sınıf.metot}. */
  public static Path dizin(Path kok, String sinif, String metot) {
    String ad = (sinif + "." + metot).replaceAll("[^A-Za-z0-9._-]", "_");
    return kok.resolve(ad);
  }

  /** Trace kaydını başlatır (her test; yalnız başarısızlıkta dosyaya yazılır). */
  public static void izlemeyiBaslat(BrowserContext baglam) {
    baglam.tracing().start(new Tracing.StartOptions().setScreenshots(true).setSnapshots(true).setSources(false));
  }

  /** Başarılı testte trace'i yazmadan kapatır. */
  public static void izlemeyiBirak(BrowserContext baglam) {
    try {
      baglam.tracing().stop();
    } catch (PlaywrightException ignored) {
      // bağlam kapanmış olabilir; kayıt zaten atılır
    }
  }

  /** Kanıtı toplar (trace kaydını da kapatır); yazılan dizini döndürür. */
  public static Path topla(Page page, BrowserContext baglam, Path kok, String sinif, String metot) {
    Path hedef = dizin(kok, sinif, metot);
    StringBuilder hatalar = new StringBuilder();
    try {
      Files.createDirectories(hedef);
    } catch (IOException e) {
      izlemeyiBirak(baglam);
      return hedef;
    }
    try {
      byte[] png = page.screenshot(new Page.ScreenshotOptions().setFullPage(true));
      Files.write(hedef.resolve(EKRAN), png);
      Allure.addAttachment("Ekran görüntüsü", "image/png", new ByteArrayInputStream(png), "png");
    } catch (PlaywrightException | IOException e) {
      hatalar.append("ekran görüntüsü: ").append(e.getClass().getSimpleName()).append('\n');
    }
    try {
      String html = page.content();
      Files.writeString(hedef.resolve(SAYFA), html, StandardCharsets.UTF_8);
      Allure.addAttachment("Sayfa HTML'i", "text/html", html, "html");
    } catch (PlaywrightException | IOException e) {
      hatalar.append("sayfa HTML'i: ").append(e.getClass().getSimpleName()).append('\n');
    }
    try {
      Path trace = hedef.resolve(TRACE);
      baglam.tracing().stop(new Tracing.StopOptions().setPath(trace));
      try (InputStream in = Files.newInputStream(trace)) {
        Allure.addAttachment("Playwright trace", "application/zip", in, "zip");
      }
    } catch (PlaywrightException | IOException e) {
      hatalar.append("trace: ").append(e.getClass().getSimpleName()).append('\n');
    }
    if (hatalar.length() > 0) {
      try {
        Files.writeString(hedef.resolve("kanit-hatasi.txt"), hatalar.toString(), StandardCharsets.UTF_8);
      } catch (IOException ignored) {
        // kanıt yazılamadı; asıl test hatası yine raporlanır
      }
    }
    return hedef;
  }
}
