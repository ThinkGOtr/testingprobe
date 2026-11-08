package com.antreklabs.bayi.birim;

import static org.testng.Assert.assertEquals;
import static org.testng.Assert.assertFalse;
import static org.testng.Assert.assertTrue;
import static org.testng.Assert.expectThrows;

import com.antreklabs.bayi.altyapi.Bekle;
import com.antreklabs.bayi.altyapi.Kanit;
import java.lang.reflect.Proxy;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicInteger;
import org.openqa.selenium.OutputType;
import org.openqa.selenium.TakesScreenshot;
import org.openqa.selenium.TimeoutException;
import org.openqa.selenium.WebDriver;
import org.testng.annotations.Test;

/** Bekleme hata türleri (eylem → TimeoutException, beklenti → AssertionError) ve kanıt dosyaları. */
public class BekleKanitBirimTesti {

  /** Ekran görüntüsü ve sayfa kaynağı veren sahte sürücü. */
  private static WebDriver sahteSurucu() {
    return (WebDriver)
        Proxy.newProxyInstance(
            BekleKanitBirimTesti.class.getClassLoader(),
            new Class<?>[] {WebDriver.class, TakesScreenshot.class},
            (vekil, metot, args) -> {
              switch (metot.getName()) {
                case "getScreenshotAs":
                  return ((OutputType<?>) args[0]).convertFromPngBytes(new byte[] {(byte) 0x89, 'P', 'N', 'G'});
                case "getPageSource":
                  return "<hierarchy><node resource-id=\"cart-total\"/></hierarchy>";
                case "toString":
                  return "sahte";
                default:
                  return null;
              }
            });
  }

  @Test(groups = "birim")
  public void kosulSaglaninciyaKadarBekler() {
    Bekle b = new Bekle(sahteSurucu(), Duration.ofSeconds(5));
    AtomicInteger tur = new AtomicInteger();
    assertEquals(b.kosul("üçüncü turda", s -> tur.incrementAndGet() >= 3 ? "tamam" : null), "tamam");
    assertEquals(tur.get(), 3);
  }

  @Test(groups = "birim")
  public void eylemZamanAsimiTimeoutException() {
    Bekle b = new Bekle(sahteSurucu(), Duration.ofMillis(300));
    TimeoutException e = expectThrows(TimeoutException.class, () -> b.kosul("öğe görünmedi: kimlik 'add-to-cart'", s -> null));
    assertTrue(e.getMessage().contains("öğe görünmedi: kimlik 'add-to-cart'"), e.getMessage());
  }

  @Test(groups = "birim")
  public void beklentiZamanAsimiAssertionError() {
    Bekle b = new Bekle(sahteSurucu(), Duration.ofMillis(300));
    AssertionError e =
        expectThrows(AssertionError.class, () -> b.dogrula("'cart-total' metni", "150,00 TL", () -> "175,00 TL", () -> false));
    assertTrue(e.getMessage().contains("beklenen <150,00 TL>, görülen <175,00 TL>"), e.getMessage());
    b.dogrula("'cart-total' metni", "150,00 TL", () -> "150,00 TL", () -> true);
  }

  @Test(groups = "birim")
  public void kanitDosyalari() throws Exception {
    Path kok = Files.createTempDirectory("kanit-birim-");
    Path d = Kanit.topla(sahteSurucu(), kok, "SepetTesti", "kampanya Yedi/Adet");
    assertEquals(d, kok.resolve("SepetTesti.kampanya_Yedi_Adet"));
    assertTrue(Files.size(d.resolve(Kanit.EKRAN)) > 0);
    assertTrue(Files.readString(d.resolve(Kanit.SAYFA_KAYNAGI), StandardCharsets.UTF_8).contains("cart-total"));
    assertFalse(Files.exists(d.resolve("kanit-hatasi.txt")));
  }
}
