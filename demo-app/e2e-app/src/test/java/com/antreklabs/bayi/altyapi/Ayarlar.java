package com.antreklabs.bayi.altyapi;

import java.nio.file.Path;
import java.time.Duration;
import java.util.Map;
import java.util.Optional;
import java.util.function.UnaryOperator;
import java.util.regex.Pattern;

/**
 * Koşum ayarları: önce sistem özelliği ({@code -Dad=değer}), yoksa ortam değişkeni, yoksa varsayılan.
 *
 * <p>Sır (demo test token'ı) yalnızca ortamdan ya da komut satırından gelir; depoda varsayılanı yoktur.
 * Komut satırı süreç listesinde göründüğü için {@code DEMOAPP_TEST_TOKEN} ortam değişkeni tercih edilir.
 */
public final class Ayarlar {

  /** Sistem özelliği → ortam değişkeni eşlemesi (README tablosu bununla aynıdır). */
  static final Map<String, String> ORTAM_KARSILIGI =
      Map.ofEntries(
          Map.entry("platform", "PLATFORM"),
          Map.entry("appium.url", "APPIUM_URL"),
          Map.entry("app.path", "APP_PATH"),
          Map.entry("app.id", "APP_ID"),
          Map.entry("app.activity", "APP_ACTIVITY"),
          Map.entry("app.args", "APP_ARGS"),
          Map.entry("app.workdir", "APP_WORKDIR"),
          Map.entry("device.name", "DEVICE_NAME"),
          Map.entry("device.udid", "DEVICE_UDID"),
          Map.entry("platform.version", "PLATFORM_VERSION"),
          Map.entry("demo.api.url", "DEMO_API_URL"),
          Map.entry("demoapp.test.token", "DEMOAPP_TEST_TOKEN"),
          Map.entry("break.campaign", "BREAK_CAMPAIGN"),
          Map.entry("tp.fault", "TP_FAULT"),
          Map.entry("tp.e2e.no.reset", "TP_E2E_NO_RESET"),
          Map.entry("bekleme.ms", "BEKLEME_MS"),
          Map.entry("bayi.kilit.ms", "BAYI_KILIT_MS"),
          Map.entry("kanit.dizini", "KANIT_DIZINI"),
          Map.entry("kimlik.android", "KIMLIK_ANDROID"),
          Map.entry("kimlik.ios", "KIMLIK_IOS"),
          Map.entry("kimlik.windows", "KIMLIK_WINDOWS"));

  /** Ekilmiş hata kodunun biçimi (web: fixtures.ts FAULT_PATTERN; toolchain `fault`). */
  static final Pattern HATA_KODU = Pattern.compile("^[a-z0-9_]{1,40}$");

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
      String ortamAdi = ORTAM_KARSILIGI.get(ad);
      v = ortamAdi == null ? null : ortam.apply(ortamAdi);
    }
    return v == null || v.isBlank() ? Optional.empty() : Optional.of(v.trim());
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

  /** Hedef platform; verilmemişse ya da geçersizse açıklayıcı hata. */
  public Platform platform() {
    return Platform.coz(deger("platform").orElse(null));
  }

  /** Appium sunucusu (Appium 3: temel yol "/"). */
  public String appiumUrl() {
    return deger("appium.url", "http://127.0.0.1:4723");
  }

  /** Kurulacak uygulama dosyası (.apk, .app, .exe); boşsa {@link #appId()} kurulu uygulamayı açar. */
  public Optional<String> appPath() {
    // Appium sunucusu göreli yolu kendi dizinine göre çözer: yerelde var olan dosya mutlak yola
    // çevrilir. Yerelde olmayan yol (ör. Windows VM içindeki exe) olduğu gibi geçer.
    return deger("app.path")
        .map(
            p -> {
              Path yol = Path.of(p);
              return !yol.isAbsolute() && java.nio.file.Files.exists(yol) ? yol.toAbsolutePath().normalize().toString() : p;
            });
  }

  /** Kurulu uygulamanın kimliği: Android paket adı, iOS bundle id, Windows AUMID / exe yolu. */
  public Optional<String> appId() {
    return deger("app.id");
  }

  /** Android: açılış aktivitesi (yalnızca app.id ile; app.path verilince Appium kendisi bulur). */
  public Optional<String> appActivity() {
    return deger("app.activity");
  }

  /** Windows: uygulamaya geçirilecek komut satırı argümanları (ör. demo API adresi). */
  public Optional<String> appArgs() {
    return deger("app.args");
  }

  /** Windows: uygulamanın çalışma dizini (NovaWindows {@code appWorkingDir}). */
  public Optional<String> appWorkdir() {
    return deger("app.workdir");
  }

  /** Emülatör / simülatör / cihaz adı. */
  public Optional<String> deviceName() {
    return deger("device.name");
  }

  /** Fiziksel cihaz ya da belirli simülatör UDID'i. */
  public Optional<String> udid() {
    return deger("device.udid");
  }

  /** Platform sürümü (iOS simülatör seçimi için yararlı). */
  public Optional<String> platformVersion() {
    return deger("platform.version");
  }

  /**
   * /test/* uçlarının kökü. Doğrudan API ise {@code /test/reset} buna eklenir. Varsayılan web
   * vekilidir (vite preview /api → API); compose'daki nginx /api/test/ yolunu açmaz, orada
   * DEMO_API_URL verilmelidir.
   */
  public String demoApiUrl() {
    return deger("demo.api.url", "http://127.0.0.1:8081/api").replaceAll("/+$", "");
  }

  /** /test/* paylaşılan sırrı; yalnızca ortamdan / komut satırından. */
  public Optional<String> testToken() {
    return deger("demoapp.test.token");
  }

  /** "Kırarak doğrula": BREAK_CAMPAIGN=1 iken bayinin kampanya kuralı test süresince bozulur. */
  public boolean kampanyaKirik() {
    return "1".equals(deger("break.campaign", ""));
  }

  /**
   * "Ekilmiş hata koşusu": TP_FAULT=&lt;kod&gt; iken bayinin hesabı test süresince katalogdaki o
   * hatayla çalışır (demo API {@code faults.py}). {@code BREAK_CAMPAIGN=1} ile birlikte verilirse
   * TP_FAULT geçerlidir. Biçimi bozuk kod açıklayıcı hatadır; kodun katalogda olup olmadığına API
   * karar verir (bilinmeyen kod → 422).
   */
  public Optional<String> ekilmisHata() {
    Optional<String> kod = deger("tp.fault");
    if (kod.isPresent() && !HATA_KODU.matcher(kod.get()).matches()) {
      throw new IllegalArgumentException("TP_FAULT geçersiz: '" + kod.get() + "' (beklenen biçim: " + HATA_KODU.pattern() + ")");
    }
    return kod;
  }

  /** TP_E2E_NO_RESET=1: token yokken yalnızca sepet yalıtımı. */
  public boolean sifirlamaYok() {
    return "1".equals(deger("tp.e2e.no.reset", ""));
  }

  /** Beklenti ve eylem bekleme üst sınırı (web: expect 5 sn; cihazda daha yavaş, 10 sn). */
  public Duration bekleme() {
    return Duration.ofMillis(sayi("bekleme.ms", 10_000));
  }

  /** Bayi kilidini bekleme üst sınırı (web: LOCK_WAIT_MS). */
  public Duration bayiKilidiBekleme() {
    return Duration.ofMillis(sayi("bayi.kilit.ms", 40_000));
  }

  /** Başarısız test kanıtlarının dizini (ekran görüntüsü + sayfa kaynağı). */
  public Path kanitDizini() {
    return Path.of(deger("kanit.dizini", "target/kanit"));
  }

  /** Platform için kimlik stratejisi geçersiz kılması (kimlik.android=id|erisilebilirlik). */
  public Optional<String> kimlikStratejisi(Platform p) {
    return deger("kimlik." + p.ad());
  }
}
