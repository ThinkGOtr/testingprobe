package com.antreklabs.bayi.altyapi;

import com.microsoft.playwright.Browser;
import com.microsoft.playwright.BrowserType;
import com.microsoft.playwright.Playwright;
import com.microsoft.playwright.PlaywrightException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * İş parçacığı başına tek Playwright + Chromium (TypeScript: işçi başına tarayıcı).
 *
 * <p>Playwright for Java nesneleri iş parçacığı güvenli değildir: her iş parçacığı kendi
 * {@link Playwright} örneğini ve tarayıcısını kullanır; testler arasında yalnızca tarayıcı paylaşılır,
 * her test yeni bir {@code BrowserContext} + {@code Page} alır (çerez/oturum sızmaz). Örnekler JVM
 * kapanırken kapatılır.
 *
 * <p>Tarayıcı {@code PLAYWRIGHT_BROWSERS_PATH}'ten (yoksa Playwright'ın varsayılan önbelleğinden)
 * açılır; {@code PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1} ile test sırasında indirme yapılmaz — tarayıcı
 * yoksa açıklayıcı hata verilir (kurulum: README "Tarayıcı kurulumu").
 */
public final class Tarayici {

  private static final Logger LOG = Logger.getLogger(Tarayici.class.getName());
  private static final ThreadLocal<Tarayici> ISCI = new ThreadLocal<>();
  private static final List<Tarayici> TUMU = new CopyOnWriteArrayList<>();

  static {
    Runtime.getRuntime().addShutdownHook(new Thread(Tarayici::hepsiniKapat, "tarayici-kapat"));
  }

  private final Playwright playwright;
  private final Browser browser;

  private Tarayici(Playwright playwright, Browser browser) {
    this.playwright = playwright;
    this.browser = browser;
  }

  /** Bu iş parçacığının tarayıcısı (ilk çağrıda açılır; kapanmışsa yeniden açılır). */
  public static Browser browser(Ayarlar ayarlar) {
    Tarayici t = ISCI.get();
    if (t == null || !t.browser.isConnected()) {
      if (t != null) {
        t.kapat();
      }
      t = ac(ayarlar);
      ISCI.set(t);
      TUMU.add(t);
    }
    return t.browser;
  }

  private static Tarayici ac(Ayarlar ayarlar) {
    Playwright pw =
        Playwright.create(new Playwright.CreateOptions().setEnv(Map.of("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "1")));
    try {
      Browser b = pw.chromium().launch(new BrowserType.LaunchOptions().setHeadless(ayarlar.headless()));
      return new Tarayici(pw, b);
    } catch (PlaywrightException e) {
      pw.close();
      String yol = System.getenv("PLAYWRIGHT_BROWSERS_PATH");
      throw new IllegalStateException(
          "Chromium açılamadı (PLAYWRIGHT_BROWSERS_PATH=" + (yol == null ? "<varsayılan önbellek>" : yol)
              + "). Tarayıcı test sırasında indirilmez; README 'Tarayıcı kurulumu'na bakın.",
          e);
    }
  }

  private void kapat() {
    TUMU.remove(this);
    try {
      playwright.close();
    } catch (RuntimeException e) {
      LOG.log(Level.FINE, "Playwright kapatılamadı", e);
    }
  }

  static void hepsiniKapat() {
    for (Tarayici t : TUMU) {
      t.kapat();
    }
  }
}
