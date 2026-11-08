package com.antreklabs.bayi.birim;

import static org.testng.Assert.assertEquals;
import static org.testng.Assert.assertFalse;
import static org.testng.Assert.assertNotEquals;
import static org.testng.Assert.assertTrue;
import static org.testng.Assert.expectThrows;

import com.antreklabs.bayi.altyapi.Bayi;
import com.antreklabs.bayi.altyapi.BayiKilidi;
import com.antreklabs.bayi.altyapi.Bayiler;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import org.testng.annotations.Test;

/** {@code @Bayi} çözümü ve bayi kilidi (web: tests/dealers.spec.ts "Bayi seçimi (birim)"). */
public class BayiBirimTesti {

  @Bayi("bayi2")
  static class Bayi2yeSabit {}

  static class AltSinif extends Bayi2yeSabit {}

  static class Sabitsiz {}

  @Bayi("bayi3")
  static class AjanBayisi {}

  @Bayi("yok")
  static class OlmayanBayi {}

  @Test(groups = "birim")
  public void isciBayisiVeSabitleme() {
    assertEquals(Bayiler.sec(null, 0).kullaniciAdi(), "bayi1");
    assertEquals(Bayiler.sec(null, 1).kullaniciAdi(), "bayi2");
    assertEquals(Bayiler.sec("bayi2", 0), Bayiler.E2E.get(1));
    assertTrue(
        expectThrows(IllegalArgumentException.class, () -> Bayiler.sec(null, Bayiler.E2E.size()))
            .getMessage()
            .contains("paralel işçi"));
  }

  @Test(groups = "birim")
  public void notasyonCozumu() {
    assertEquals(Bayiler.sinifIcin(Bayi2yeSabit.class, 0).kullaniciAdi(), "bayi2");
    assertEquals(Bayiler.sinifIcin(AltSinif.class, 0).kullaniciAdi(), "bayi2", "@Bayi kalıtılır");
    assertEquals(Bayiler.sinifIcin(Sabitsiz.class, 0).kullaniciAdi(), "bayi1");
    assertEquals(Bayiler.sinifIcin(Bayi2yeSabit.class, 0).ad(), "Sahil Bayi");
  }

  @Test(groups = "birim")
  public void ajanBayisiE2eyeKapali() {
    assertTrue(
        expectThrows(IllegalArgumentException.class, () -> Bayiler.sinifIcin(AjanBayisi.class, 0))
            .getMessage()
            .contains("doğrulama ajanına ayrılmıştır"));
    assertTrue(
        expectThrows(IllegalArgumentException.class, () -> Bayiler.sinifIcin(OlmayanBayi.class, 0))
            .getMessage()
            .contains("e2e bayisi değil"));
    assertFalse(Bayiler.E2E.stream().anyMatch(b -> b.kullaniciAdi().equals(Bayiler.AJAN_BAYISI)));
  }

  @Test(groups = "birim")
  public void kilitDiziniApiyeGore() {
    assertEquals(BayiKilidi.dizin("http://a:1"), BayiKilidi.dizin("http://a:1"));
    assertNotEquals(BayiKilidi.dizin("http://a:1"), BayiKilidi.dizin("http://b:1"));
  }

  @Test(groups = "birim")
  public void kilitOzeldirVeBekleyenSonraAlir() throws Exception {
    Path dizin = Files.createTempDirectory("demoapp-kilit-birim-");
    BayiKilidi a = BayiKilidi.al(dizin, "bayi1", Duration.ofSeconds(5));
    // Aynı bayiyi başka iş parçacığı kısa sürede alamaz.
    CompletableFuture<Throwable> kisa =
        CompletableFuture.supplyAsync(
            () -> {
              try {
                BayiKilidi.al(dizin, "bayi1", Duration.ofMillis(150)).close();
                return null;
              } catch (RuntimeException e) {
                return e;
              }
            });
    Throwable hata = kisa.get(5, TimeUnit.SECONDS);
    assertTrue(hata instanceof IllegalStateException && hata.getMessage().contains("serbest kalmadı"), String.valueOf(hata));
    // Bekleyen, kilit bırakılınca alır.
    CompletableFuture<Boolean> bekleyen =
        CompletableFuture.supplyAsync(
            () -> {
              try (BayiKilidi b = BayiKilidi.al(dizin, "bayi1", Duration.ofSeconds(5))) {
                return Boolean.TRUE;
              }
            });
    assertFalse(bekleyen.isDone());
    a.close();
    a.close(); // ikinci bırakma zararsız
    assertTrue(bekleyen.get(5, TimeUnit.SECONDS));
    // Başka bayinin kilidi bağımsızdır.
    try (BayiKilidi x = BayiKilidi.al(dizin, "bayi1", Duration.ofSeconds(1));
        BayiKilidi y = BayiKilidi.al(dizin, "bayi2", Duration.ofSeconds(1))) {
      assertTrue(Files.exists(dizin.resolve("bayi2.kilit")));
    }
  }

  @Test(groups = "birim")
  public void kilitSureclerArasidir() throws IOException, InterruptedException {
    // Ayrı bir JVM kilidi tutarken bu süreç alamaz; süreç bitince kilit kendiliğinden düşer.
    Path dizin = Files.createTempDirectory("demoapp-kilit-surec-");
    String java = Path.of(System.getProperty("java.home"), "bin", "java").toString();
    Process cocuk =
        new ProcessBuilder(
                java,
                "-cp",
                System.getProperty("java.class.path"),
                KilitTutucu.class.getName(),
                dizin.toString())
            .redirectErrorStream(true)
            .start();
    try {
      // Çocuğun kilidi aldığını, yazdığı satırla öğren (bekleme: akış okuma, uyku yok).
      String satir = new String(cocuk.getInputStream().readNBytes(7)).trim();
      assertEquals(satir, "TUTUYOR");
      assertTrue(
          expectThrows(IllegalStateException.class, () -> BayiKilidi.al(dizin, "bayi1", Duration.ofMillis(300)))
              .getMessage()
              .contains("serbest kalmadı"));
    } finally {
      cocuk.getOutputStream().close(); // çocuk stdin kapanınca çıkar
      assertTrue(cocuk.waitFor(10, TimeUnit.SECONDS));
    }
    try (BayiKilidi k = BayiKilidi.al(dizin, "bayi1", Duration.ofSeconds(5))) {
      assertTrue(Files.exists(dizin.resolve("bayi1.kilit")));
    }
  }

  /** Ayrı süreçte kilidi tutan yardımcı: kilidi alır, "TUTUYOR" yazar, stdin kapanınca çıkar. */
  public static final class KilitTutucu {
    public static void main(String[] args) throws IOException {
      try (BayiKilidi k = BayiKilidi.al(Path.of(args[0]), "bayi1", Duration.ofSeconds(5))) {
        System.out.print("TUTUYOR");
        System.out.flush();
        while (System.in.read() >= 0) {
          // stdin kapanana kadar bekle
        }
      }
    }
  }
}
