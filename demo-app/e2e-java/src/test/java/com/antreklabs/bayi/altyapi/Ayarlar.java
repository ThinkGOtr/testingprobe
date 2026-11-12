package com.antreklabs.bayi.altyapi;

import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.UnaryOperator;

/**
 * Koşum ayarları: önce sistem özelliği ({@code -Dad=değer}), yoksa ortam değişkeni, yoksa varsayılan.
 *
 * <p>Ortam adları TypeScript e2e ile aynıdır ({@code BASE_URL}, {@code DEMO_API_URL},
 * {@code DEMOAPP_TEST_TOKEN}, {@code BREAK_CAMPAIGN}, {@code TP_E2E_NO_RESET}); API kökü için
 * {@code API_URL} de kabul edilir (011 plan §2.5).
 *
 * <p>Sır (demo test token'ı) yalnızca ortamdan ya da komut satırından gelir; depoda varsayılanı yoktur.
 * Komut satırı süreç listesinde göründüğü için {@code DEMOAPP_TEST_TOKEN} ortam değişkeni tercih edilir.
 */
public final class Ayarlar {

  /** Sistem özelliği → ortam değişkenleri (öncelik sırasıyla; README tablosu bununla aynıdır). */
  static final Map<String, List<String>> ORTAM_KARSILIGI =
      Map.ofEntries(
          Map.entry("base.url", List.of("BASE_URL")),
          Map.entry("demo.api.url", List.of("DEMO_API_URL", "API_URL")),
          Map.entry("demoapp.test.token", List.of("DEMOAPP_TEST_TOKEN")),
          Map.entry("break.campaign", List.of("BREAK_CAMPAIGN")),
          Map.entry("tp.e2e.no.reset", List.of("TP_E2E_NO_RESET")),
          Map.entry("headless", List.of("HEADLESS")),
          Map.entry("bekleme.ms", List.of("BEKLEME_MS")),
          Map.entry("gezinme.ms", List.of("GEZINME_MS")),
          Map.entry("bayi.kilit.ms", List.of("BAYI_KILIT_MS")),
          Map.entry("kanit.dizini", List.of("KANIT_DIZINI")));

  private final UnaryOperator<String> ozellik;
  private final UnaryOperator<String> ortam;

  private Ayarlar(UnaryOperator<String> ozellik, UnaryOperator<String> ortam) {
    this.ozellik = ozellik;
    this.ortam = ortam;
  }

  /** Süreç ayarları (System.getProperty + System.getenv). */
  public static Ayarlar oku() {
    return new Ayarlar(System::getProperty, System::getenv);
  }

  /** Birim testleri için: verilen özellik ve ortam haritalarından ayar. */
  public static Ayarlar haritadan(Map<String, String> ozellikler, Map<String, String> ortamlar) {
    return new Ayarlar(ozellikler::get, ortamlar::get);
  }

  private Optional<String> deger(String ad) {
    String v = ozellik.apply(ad);
    if (v == null || v.isBlank()) {
      v = null;
      for (String ortamAdi : ORTAM_KARSILIGI.getOrDefault(ad, List.of())) {
        String o = ortam.apply(ortamAdi);
        if (o != null && !o.isBlank()) {
          v = o;
          break;
        }
      }
    }
    return v == null ? Optional.empty() : Optional.of(v.trim());
  }

  private String deger(String ad, String varsayilan) {
    return deger(ad).orElse(varsayilan);
  }

  private long sayi(String ad, long varsayilan) {
    Optional<String> v = deger(ad);
    if (v.isEmpty()) {
      return varsayilan;
    }
    try {
      return Long.parseLong(v.get());
    } catch (NumberFormatException e) {
      throw new IllegalArgumentException(ad + " sayı olmalı: '" + v.get() + "'", e);
    }
  }

  /** Web uygulamasının kökü (TS: {@code use.baseURL}); varsayılan compose'daki demo-app-web. */
  public String baseUrl() {
    return deger("base.url", "http://127.0.0.1:8081").replaceAll("/+$", "");
  }

  /**
   * /test/* uçlarının kökü. Doğrudan API ise {@code /test/reset} buna eklenir. Verilmezse web vekili
   * kullanılır ({@code <base.url>/api}; vite preview /api → API). Compose'daki nginx /api/test/ yolunu
   * açmaz, orada DEMO_API_URL verilmelidir (ör. http://demo-app-api:8000).
   */
  public String demoApiUrl() {
    return deger("demo.api.url").map(u -> u.replaceAll("/+$", "")).orElseGet(() -> baseUrl() + "/api");
  }

  /** /test/* paylaşılan sırrı; yalnızca ortamdan / komut satırından. */
  public Optional<String> testToken() {
    return deger("demoapp.test.token");
  }

  /** "Kırarak doğrula": BREAK_CAMPAIGN=1 iken bayinin kampanya kuralı test süresince bozulur. */
  public boolean kampanyaKirik() {
    return "1".equals(deger("break.campaign", ""));
  }

  /** TP_E2E_NO_RESET=1: token yokken yalnızca sepet yalıtımı. */
  public boolean sifirlamaYok() {
    return "1".equals(deger("tp.e2e.no.reset", ""));
  }

  /** Tarayıcı penceresiz mi; varsayılan evet. Pencereli koşu: {@code -Dheadless=false}. */
  public boolean headless() {
    String v = deger("headless", "true").toLowerCase(java.util.Locale.ROOT);
    return !(v.equals("false") || v.equals("0"));
  }

  /** Beklenti ve eylem bekleme üst sınırı (TS: expect.timeout / actionTimeout = 5 sn). */
  public Duration bekleme() {
    return Duration.ofMillis(sayi("bekleme.ms", 5_000));
  }

  /** Sayfa gezinme üst sınırı (TS: navigationTimeout = 10 sn). */
  public Duration gezinme() {
    return Duration.ofMillis(sayi("gezinme.ms", 10_000));
  }

  /** Bayi kilidini bekleme üst sınırı (TS: LOCK_WAIT_MS). */
  public Duration bayiKilidiBekleme() {
    return Duration.ofMillis(sayi("bayi.kilit.ms", 40_000));
  }

  /** Başarısız test kanıtlarının dizini (ekran görüntüsü + trace + sayfa HTML'i). */
  public Path kanitDizini() {
    return Path.of(deger("kanit.dizini", "target/kanit"));
  }
}
