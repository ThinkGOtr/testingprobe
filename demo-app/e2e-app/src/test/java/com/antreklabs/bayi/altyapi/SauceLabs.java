package com.antreklabs.bayi.altyapi;

import io.appium.java_client.remote.options.BaseOptions;
import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.function.UnaryOperator;
import java.util.logging.Level;
import java.util.logging.Logger;
import java.util.regex.Pattern;
import org.openqa.selenium.JavascriptExecutor;
import org.openqa.selenium.remote.RemoteWebDriver;

/**
 * Sauce Labs sanal cihaz (Android emülatör / iOS simülatör) oturumu — elle Sauce turu
 * ({@code .github/workflows/sauce-demo.yml}). Testler runner'da koşar, Appium oturumu Sauce'tadır.
 *
 * <p>Etkin: {@code appium.url} {@code *.saucelabs.com} ise. Kimlik ({@code SAUCE_USERNAME} /
 * {@code SAUCE_ACCESS_KEY}) yalnız ortamdan okunur ve YETENEKLERE (capabilities) KONMAZ: Selenium
 * oturum hatasında yetenekleri (kısaltılmış değerlerle) istisna mesajına yazar; GitHub maskesi
 * kısaltılmış değeri tanımaz (canlı tur 45191577699). Kimlik HTTP Basic başlığıyla gider
 * ({@link #istemci}). Diğer ortam değişkenleri: {@code SAUCE_TUNNEL_NAME}, {@code SAUCE_BUILD},
 * {@code SAUCE_APPIUM_VERSION} (yoksa gönderilmez: Sauce'un cihaz için önerdiği sürüm),
 * {@code SAUCE_OTURUM_DOSYASI} (test → oturum kimliği kaydı; özet betiği Sauce iş bağlantısını bundan
 * kurar).
 *
 * <p>Uygulama {@code app.path} ile verilir ({@code storage:filename=…} — Sauce storage'a yüklenmiş
 * derleme); cihaz {@code device.name} + {@code platform.version}.
 */
public final class SauceLabs {

  private static final Logger LOG = Logger.getLogger(SauceLabs.class.getName());

  /** Sauce adlarında güvenli karakterler (iş adı, derleme, tünel). */
  private static final Pattern GUVENLI = Pattern.compile("[^A-Za-z0-9 ._#:()-]");

  private final UnaryOperator<String> ortam;

  SauceLabs(UnaryOperator<String> ortam) {
    this.ortam = ortam;
  }

  /** Süreç ortamından. */
  public static SauceLabs ortamdan() {
    return new SauceLabs(System::getenv);
  }

  /** Birim testleri için. */
  public static SauceLabs haritadan(Map<String, String> ortam) {
    return new SauceLabs(ortam::get);
  }

  /** Appium adresi bir Sauce Labs uç noktası mı ({@code https://*.saucelabs.com}). */
  public static boolean sauceAdresi(String appiumUrl) {
    try {
      URI u = new URI(appiumUrl);
      String host = u.getHost();
      return "https".equals(u.getScheme()) && host != null && host.toLowerCase().endsWith(".saucelabs.com");
    } catch (Exception e) {
      return false;
    }
  }

  private Optional<String> deger(String ad) {
    String v = ortam.apply(ad);
    return v == null || v.isBlank() ? Optional.empty() : Optional.of(v.trim());
  }

  static String guvenliAd(String s) {
    String t = GUVENLI.matcher(s).replaceAll("_");
    return t.length() > 120 ? t.substring(0, 120) : t;
  }

  /**
   * {@code sauce:options} — kimlik, tünel, derleme ve iş adı. Kimlik eksikse açıklayıcı hata (oturum
   * Sauce'a kimliksiz gitmez).
   */
  public Map<String, Object> secenekler(String isAdi) {
    Map<String, Object> s = new LinkedHashMap<>();
    deger("SAUCE_APPIUM_VERSION").ifPresent(v -> s.put("appiumVersion", v));
    deger("SAUCE_TUNNEL_NAME").ifPresent(t -> s.put("tunnelName", guvenliAd(t)));
    deger("SAUCE_BUILD").ifPresent(b -> s.put("build", guvenliAd(b)));
    if (isAdi != null && !isAdi.isBlank()) {
      s.put("name", guvenliAd(isAdi));
    }
    s.put("tags", java.util.List.of("testing-probe", "demo-app", "sauce-tur"));
    return s;
  }

  /**
   * Sauce uç noktasına Basic kimlikle giden istemci yapılandırması (kimlik yeteneklerde değil). Kimlik
   * eksikse açıklayıcı hata: oturum Sauce'a kimliksiz gitmez.
   */
  public io.appium.java_client.AppiumClientConfig istemci(java.net.URL adres) {
    String kullanici = deger("SAUCE_USERNAME").orElseThrow(() -> eksik("SAUCE_USERNAME"));
    String anahtar = deger("SAUCE_ACCESS_KEY").orElseThrow(() -> eksik("SAUCE_ACCESS_KEY"));
    // Basic başlığı her isteğe baştan eklenir (JDK Authenticator yalnız 401 meydan okumasına yanıt verir).
    String basic =
        "Basic "
            + java.util.Base64.getEncoder()
                .encodeToString((kullanici + ":" + anahtar).getBytes(java.nio.charset.StandardCharsets.UTF_8));
    org.openqa.selenium.remote.http.Filter kimlik =
        next ->
            req -> {
              req.setHeader("Authorization", basic);
              return next.execute(req);
            };
    io.appium.java_client.AppiumClientConfig c =
        io.appium.java_client.AppiumClientConfig.defaultConfig().baseUrl(adres).readTimeout(java.time.Duration.ofMinutes(5));
    return c.withFilter(c.filter().andThen(kimlik))
        .authenticateAs(new org.openqa.selenium.UsernameAndPassword(kullanici, anahtar));
  }

  /** Seçeneklere Sauce ayarlarını ekler. */
  public void uygula(BaseOptions<?> o, String isAdi) {
    o.setCapability("sauce:options", secenekler(isAdi));
  }

  private static IllegalArgumentException eksik(String ad) {
    return new IllegalArgumentException("Sauce Labs oturumu için " + ad + " ortam değişkeni gerekir");
  }

  /**
   * Test sonucunu Sauce işine yazar ({@code sauce:job-result}) ve oturum kimliğini kayıt dosyasına
   * ekler (JSON satırı). Hata testi düşürmez (yalnız uyarı).
   */
  public void bitir(RemoteWebDriver surucu, String isAdi, boolean gecti) {
    String oturum = null;
    try {
      oturum = String.valueOf(surucu.getSessionId());
      ((JavascriptExecutor) surucu).executeScript("sauce:job-result=" + (gecti ? "passed" : "failed"));
    } catch (RuntimeException e) {
      LOG.log(Level.WARNING, "Sauce iş sonucu yazılamadı", e);
    }
    Optional<String> dosya = deger("SAUCE_OTURUM_DOSYASI");
    if (oturum == null || dosya.isEmpty() || !oturum.matches("[A-Za-z0-9-]{8,64}")) {
      return;
    }
    String satir =
        "{\"test\":\"" + jsonKacis(isAdi) + "\",\"oturum\":\"" + oturum + "\",\"durum\":\""
            + (gecti ? "passed" : "failed") + "\"}\n";
    try {
      Path p = Path.of(dosya.get());
      if (p.getParent() != null) {
        Files.createDirectories(p.getParent());
      }
      Files.writeString(p, satir, StandardCharsets.UTF_8, StandardOpenOption.CREATE, StandardOpenOption.APPEND);
    } catch (IOException e) {
      LOG.log(Level.WARNING, "Sauce oturum kaydı yazılamadı", e);
    }
  }

  static String jsonKacis(String s) {
    StringBuilder b = new StringBuilder();
    for (char c : s.toCharArray()) {
      if (c == '"' || c == '\\') {
        b.append('\\').append(c);
      } else if (c < 0x20) {
        b.append(String.format("\\u%04x", (int) c));
      } else {
        b.append(c);
      }
    }
    return b.toString();
  }
}
