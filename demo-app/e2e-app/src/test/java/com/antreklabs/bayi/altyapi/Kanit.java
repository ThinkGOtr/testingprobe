package com.antreklabs.bayi.altyapi;

import io.qameta.allure.Allure;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.openqa.selenium.OutputType;
import org.openqa.selenium.TakesScreenshot;
import org.openqa.selenium.WebDriver;
import org.openqa.selenium.WebDriverException;

/**
 * Başarısız testin kanıtı: ekran görüntüsü ve sayfa kaynağı (erişilebilirlik ağacı XML).
 *
 * <p>Dosyalar {@code target/kanit/<Sınıf>.<metot>/} altına yazılır ({@code ekran.png},
 * {@code sayfa-kaynagi.xml}); triage bunları okur. Allure raporuna da eklenir. Kanıt toplanamazsa
 * testin asıl hatası gölgelenmez: yalnızca {@code kanit-hatasi.txt} yazılır.
 */
public final class Kanit {

  /** Ekran görüntüsü dosya adı. */
  public static final String EKRAN = "ekran.png";
  /** Sayfa kaynağı dosya adı. */
  public static final String SAYFA_KAYNAGI = "sayfa-kaynagi.xml";

  private Kanit() {}

  /** Testin kanıt dizini: güvenli karakterlere indirgenmiş {@code Sınıf.metot}. */
  public static Path dizin(Path kok, String sinif, String metot) {
    String ad = (sinif + "." + metot).replaceAll("[^A-Za-z0-9._-]", "_");
    return kok.resolve(ad);
  }

  /** Kanıtı toplar; yazılan dizini döndürür. */
  public static Path topla(WebDriver surucu, Path kok, String sinif, String metot) {
    Path hedef = dizin(kok, sinif, metot);
    StringBuilder hatalar = new StringBuilder();
    try {
      Files.createDirectories(hedef);
    } catch (IOException e) {
      return hedef;
    }
    try {
      byte[] png = ((TakesScreenshot) surucu).getScreenshotAs(OutputType.BYTES);
      Files.write(hedef.resolve(EKRAN), png);
      Allure.addAttachment("Ekran görüntüsü", "image/png", new ByteArrayInputStream(png), "png");
    } catch (WebDriverException | ClassCastException | IOException e) {
      hatalar.append("ekran görüntüsü: ").append(e.getClass().getSimpleName()).append('\n');
    }
    try {
      String kaynak = surucu.getPageSource();
      Files.writeString(hedef.resolve(SAYFA_KAYNAGI), kaynak, StandardCharsets.UTF_8);
      Allure.addAttachment("Sayfa kaynağı", "application/xml", kaynak, "xml");
    } catch (WebDriverException | IOException e) {
      hatalar.append("sayfa kaynağı: ").append(e.getClass().getSimpleName()).append('\n');
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
