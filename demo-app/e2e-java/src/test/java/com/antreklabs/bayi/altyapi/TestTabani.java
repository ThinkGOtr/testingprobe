package com.antreklabs.bayi.altyapi;

import com.antreklabs.bayi.ekranlar.CartPage;
import com.antreklabs.bayi.ekranlar.CatalogPage;
import com.antreklabs.bayi.ekranlar.LoginPage;
import com.antreklabs.bayi.ekranlar.OrderPage;
import com.microsoft.playwright.APIResponse;
import com.microsoft.playwright.Browser;
import com.microsoft.playwright.BrowserContext;
import com.microsoft.playwright.Page;
import com.microsoft.playwright.PlaywrightException;
import com.microsoft.playwright.assertions.PlaywrightAssertions;
import com.microsoft.playwright.options.RequestOptions;
import java.lang.reflect.Method;
import java.time.Duration;
import java.util.Arrays;
import java.util.Map;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.logging.Level;
import java.util.logging.Logger;
import org.testng.IHookCallBack;
import org.testng.IHookable;
import org.testng.ITestResult;
import org.testng.SkipException;
import org.testng.annotations.Test;

/**
 * Tüm web testlerinin tabanı (TypeScript: tests/fixtures.ts {@code test} fikstürleri).
 *
 * <p>Her test için, sırasıyla:
 * <ol>
 *   <li>işçi yuvası alınır (en çok {@link Bayiler#E2E} kadar eşzamanlı test; TS {@code parallelIndex});
 *       yuvalar doluysa biri boşalana dek bayi kilidi süresi kadar beklenir;
 *   <li>bayi seçilir ({@link Bayi} notasyonu ya da yuvanın bayisi) ve süreçler arası kilitle alınır;
 *   <li>bayinin verisi sıfırlanır ({@code POST /test/reset}) ya da yalnızca sepeti boşaltılır;
 *   <li>{@code BREAK_CAMPAIGN=1} ise bayinin kampanya kuralı bozulur ({@code POST /test/break});
 *   <li>yeni {@code BrowserContext} + {@code Page} açılır (baseURL, tr-TR, Europe/Istanbul) ve trace
 *       kaydı başlar;
 *   <li>{@link OturumAcik} sınıflarda bayi API ile oturum açar ({@code signedIn}); sonra
 *       {@link #hazirlikSonrasi()} ({@code test.beforeEach}).
 * </ol>
 * Test bitince: başarısızsa kanıt ({@code target/kanit/<Sınıf>.<metot>/}: ekran.png, trace.zip,
 * sayfa.html), bağlam kapanır, kırılma geri alınır, kilit ve yuva bırakılır.
 *
 * <p>İş parçacığı güvenliği: TestNG paralel koşusunda ({@code testng.xml}: {@code parallel="classes"})
 * tüm test durumu iş parçacığına özeldir ({@link ThreadLocal}); tarayıcı iş parçacığı başına bir
 * kez açılır ({@link Tarayici}).
 *
 * <p>Hazırlık {@code @BeforeMethod} değil {@link IHookable} ile testin içinde koşar: hazırlık hatası
 * JUnit XML'de ayrı bir yapılandırma satırı olmaz, testin kendi hatası olur (hata türü korunur —
 * kırarak doğrula assertion hatasını kurulum hatasından ayırır).
 *
 * <p>Raporlar: test gruplarından Allure etiketleri ({@code tag}, Jira anahtarı → {@code story},
 * {@code tp-case}) eklenir ({@link TestGruplari}).
 *
 * <p>Fikstür erişimi (009 §2.8, 011 §2.5): adlar TS {@code interface Fixtures} ile aynıdır —
 * {@code dealer()}, {@code signedIn()}, {@code loginPage()}, {@code catalogPage()}, {@code cartPage()},
 * {@code orderPage()}. Page object erişimcisi = {@code lowerCamel(SınıfAdı)()}. Üretilen testler
 * yalnızca page object erişimcilerini çağırır.
 */
public abstract class TestTabani implements IHookable {

  private static final Logger LOG = Logger.getLogger(TestTabani.class.getName());

  /** Yalnızca sıfırlanmış veriyle anlamlı testlerin grubu (TS: {@code @sifir-veri}). */
  public static final String SIFIR_VERI = "sifir-veri";

  /** Masaüstü Chrome görüntü alanı (TS: devices["Desktop Chrome"]). */
  private static final int GENISLIK = 1280;
  private static final int YUKSEKLIK = 720;

  /** Tek testin durumu (iş parçacığına özel). */
  private static final class Durum {
    Ayarlar ayarlar;
    int yuva = -1;
    Bayiler.BayiBilgisi bayi;
    BayiKilidi kilit;
    TestVerisi veri;
    boolean kirildi;
    BrowserContext baglam;
    Page page;
    LoginPage loginPage;
    CatalogPage catalogPage;
    CartPage cartPage;
    OrderPage orderPage;
  }

  private static final boolean[] YUVALAR = new boolean[Bayiler.E2E.size()];
  /** Boş yuva sayısı: yuva bekleyen test, bir yuva boşalana dek (zaman aşımıyla) bekler. */
  private static final Semaphore BOS_YUVA = new Semaphore(YUVALAR.length, true);

  private final ThreadLocal<Durum> durum = ThreadLocal.withInitial(Durum::new);

  /**
   * Boş işçi yuvası (TS: {@code testInfo.parallelIndex}). Hepsi doluysa (thread-count > bayi
   * sayısı) bir yuva boşalana dek en çok {@code bekleme} kadar bekler; süre dolarsa açıklayıcı hata.
   */
  public static int yuvaAl(Duration bekleme) {
    boolean alindi;
    try {
      alindi = BOS_YUVA.tryAcquire(Math.max(0, bekleme.toMillis()), TimeUnit.MILLISECONDS);
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new IllegalStateException("işçi yuvası beklenirken kesildi", e);
    }
    if (!alindi) {
      throw new IllegalStateException(
          "Boş işçi yuvası "
              + bekleme.toMillis()
              + " ms içinde açılmadı: en fazla "
              + YUVALAR.length
              + " eşzamanlı test (bayi kullanıcısı sayısı); testng.xml thread-count değerini düşürün.");
    }
    synchronized (YUVALAR) {
      for (int i = 0; i < YUVALAR.length; i++) {
        if (!YUVALAR[i]) {
          YUVALAR[i] = true;
          return i;
        }
      }
    }
    BOS_YUVA.release();
    throw new IllegalStateException("işçi yuvası sayacı tutarsız"); // izin alındıysa boş yuva vardır
  }

  /** Yuvayı bırakır (bekleyen test varsa o alır); {@code yuva < 0} ya da zaten boşsa etkisiz. */
  public static void yuvaBirak(int yuva) {
    if (yuva < 0) {
      return;
    }
    synchronized (YUVALAR) {
      if (!YUVALAR[yuva]) {
        return;
      }
      YUVALAR[yuva] = false;
    }
    BOS_YUVA.release();
  }

  /** Metodun TestNG grupları. */
  static boolean grupta(Method metot, String grup) {
    Test t = metot.getAnnotation(Test.class);
    return t != null && Arrays.asList(t.groups()).contains(grup);
  }

  /** Hazırlık → test → kapanış. */
  @Override
  public void run(IHookCallBack geriCagri, ITestResult sonuc) {
    Method metot = sonuc.getMethod().getConstructorOrMethod().getMethod();
    // Allure: story / tp-case / gruplar etiket olarak (üretilen test notasyon taşımaz; gruplar yeter).
    TestGruplari.allureyeEkle(sonuc.getMethod().getGroups());
    try {
      hazirla(metot);
      hazirlikSonrasi();
      geriCagri.runTestMethod(sonuc);
    } catch (RuntimeException | Error e) {
      // Hazırlık hatası (testin kendi hatası buraya gelmez, TestNG onu sonuca yazar).
      sonuc.setThrowable(e);
      throw e;
    } finally {
      Throwable hata = sonuc.getThrowable();
      kapat(metot.getName(), hata != null && !(hata instanceof SkipException));
    }
  }

  /** Alt sınıf için: hazırlıktan sonra, testten önce ortak adım (TS: {@code test.beforeEach}). */
  protected void hazirlikSonrasi() {}

  private void hazirla(Method metot) {
    Durum d = durum.get();
    d.ayarlar = Ayarlar.oku();
    TestVerisi.Kip kip = TestVerisi.kip(d.ayarlar);
    if (kip == TestVerisi.Kip.YALNIZ_SEPET && grupta(metot, SIFIR_VERI)) {
      throw new SkipException("TP_E2E_NO_RESET=1: sipariş geçmişi silinemez, '" + SIFIR_VERI + "' testi atlandı");
    }
    d.yuva = yuvaAl(d.ayarlar.bayiKilidiBekleme());
    d.bayi = Bayiler.sinifIcin(getClass(), d.yuva);
    d.kilit =
        BayiKilidi.al(
            BayiKilidi.dizin(d.ayarlar.baseUrl(), d.ayarlar.demoApiUrl()), d.bayi.kullaniciAdi(), d.ayarlar.bayiKilidiBekleme());
    d.veri = new TestVerisi(d.ayarlar);
    if (kip == TestVerisi.Kip.SIFIRLAMA) {
      d.veri.sifirla(d.bayi.kullaniciAdi());
      if (d.ayarlar.kampanyaKirik()) {
        d.kirildi = true;
        d.veri.kampanyayiKir(d.bayi.kullaniciAdi(), true);
      }
    } else {
      d.veri.sepetiBosalt(d.bayi);
    }

    PlaywrightAssertions.setDefaultAssertionTimeout(d.ayarlar.bekleme().toMillis());
    Browser browser = Tarayici.browser(d.ayarlar);
    d.baglam =
        browser.newContext(
            new Browser.NewContextOptions()
                .setBaseURL(d.ayarlar.baseUrl())
                .setLocale("tr-TR")
                .setTimezoneId("Europe/Istanbul")
                .setViewportSize(GENISLIK, YUKSEKLIK));
    d.baglam.setDefaultTimeout(d.ayarlar.bekleme().toMillis());
    d.baglam.setDefaultNavigationTimeout(d.ayarlar.gezinme().toMillis());
    Kanit.izlemeyiBaslat(d.baglam);
    d.page = d.baglam.newPage();

    if (getClass().isAnnotationPresent(OturumAcik.class)) {
      signedIn();
    }
  }

  private void kapat(String metotAdi, boolean basarisiz) {
    Durum d = durum.get();
    try {
      if (d.baglam != null) {
        if (basarisiz && d.page != null) {
          Kanit.topla(d.page, d.baglam, d.ayarlar.kanitDizini(), getClass().getSimpleName(), metotAdi);
        } else {
          Kanit.izlemeyiBirak(d.baglam);
        }
      }
    } finally {
      try {
        if (d.baglam != null) {
          try {
            d.baglam.close();
          } catch (PlaywrightException e) {
            LOG.log(Level.WARNING, "tarayıcı bağlamı kapatılamadı", e);
          }
        }
        if (d.kirildi && d.veri != null) {
          try {
            d.veri.kampanyayiKir(d.bayi.kullaniciAdi(), false);
          } catch (RuntimeException e) {
            // Sonraki testin /test/reset'i kırılmayı da kaldırır.
            LOG.log(Level.WARNING, "kampanya kırılması geri alınamadı", e);
          }
        }
      } finally {
        if (d.kilit != null) {
          d.kilit.close();
        }
        yuvaBirak(d.yuva);
        durum.remove();
      }
    }
  }

  private Durum hazir() {
    Durum d = durum.get();
    if (d.page == null) {
      throw new IllegalStateException("tarayıcı sayfası yok (TestTabani hazırlığı başarısız)");
    }
    return d;
  }

  /** Testin bayisi (TS: {@code dealer} fikstürü). */
  protected final Bayiler.BayiBilgisi dealer() {
    return durum.get().bayi;
  }

  /**
   * Bayi API ile oturum açar; çerez sayfa bağlamıyla paylaşılır (TS: {@code signedIn} fikstürü).
   * {@link OturumAcik} sınıflarda hazırlıkta kendiliğinden çağrılır.
   */
  protected final void signedIn() {
    Durum d = hazir();
    APIResponse yanit =
        d.page
            .request()
            .post(
                "/api/auth/login",
                RequestOptions.create().setData(Map.of("kullanici_adi", d.bayi.kullaniciAdi(), "parola", d.bayi.parola())));
    if (!yanit.ok()) {
      throw new IllegalStateException("API ile giriş başarısız: " + yanit.status());
    }
  }

  /** Ham sayfa (yalnız elle yazılmış testler; TS: {@code page} fikstürü). */
  protected final Page page() {
    return hazir().page;
  }

  /** Giriş sayfası. */
  protected final LoginPage loginPage() {
    Durum d = hazir();
    if (d.loginPage == null) {
      d.loginPage = new LoginPage(d.page);
    }
    return d.loginPage;
  }

  /** Ürün kataloğu sayfası. */
  protected final CatalogPage catalogPage() {
    Durum d = hazir();
    if (d.catalogPage == null) {
      d.catalogPage = new CatalogPage(d.page);
    }
    return d.catalogPage;
  }

  /** Sepet sayfası. */
  protected final CartPage cartPage() {
    Durum d = hazir();
    if (d.cartPage == null) {
      d.cartPage = new CartPage(d.page);
    }
    return d.cartPage;
  }

  /** Sipariş onayı ve sipariş geçmişi. */
  protected final OrderPage orderPage() {
    Durum d = hazir();
    if (d.orderPage == null) {
      d.orderPage = new OrderPage(d.page);
    }
    return d.orderPage;
  }
}
