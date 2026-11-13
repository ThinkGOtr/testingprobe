package com.antreklabs.bayi.altyapi;

import com.antreklabs.bayi.ekranlar.GirisEkrani;
import com.antreklabs.bayi.ekranlar.KatalogEkrani;
import com.antreklabs.bayi.ekranlar.Kimlikler;
import com.antreklabs.bayi.ekranlar.OnayEkrani;
import com.antreklabs.bayi.ekranlar.SepetEkrani;
import com.antreklabs.bayi.ekranlar.SiparisEkrani;
import io.appium.java_client.AppiumDriver;
import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.Optional;
import java.util.logging.Level;
import java.util.logging.Logger;
import org.openqa.selenium.WebDriverException;
import org.testng.IHookCallBack;
import org.testng.IHookable;
import org.testng.ITestContext;
import org.testng.ITestResult;
import org.testng.SkipException;
import org.testng.annotations.Test;

/**
 * Tüm uygulama testlerinin tabanı (web: tests/fixtures.ts {@code test} fikstürleri).
 *
 * <p>Her test için, sırasıyla:
 * <ol>
 *   <li>bayi seçilir ({@link Bayi} notasyonu ya da işçi bayisi) ve süreçler arası kilitle alınır;
 *   <li>bayinin verisi sıfırlanır ({@code /test/reset}) ya da yalnızca sepeti boşaltılır;
 *   <li>{@code TP_FAULT=<kod>} ise bayi için o ekilmiş hata, yoksa {@code BREAK_CAMPAIGN=1} ise
 *       kampanya kırılması açılır ({@code /test/break});
 *   <li>uygulama sıfırdan başlatılır (yeni Appium oturumu);
 *   <li>{@link OturumAcik} sınıflarda arayüzden giriş yapılır; sonra {@link #hazirlikSonrasi()}.
 * </ol>
 * Test bitince: başarısızsa kanıt ({@code target/kanit/}), oturum kapanır, kırılma geri alınır,
 * kilit bırakılır.
 *
 * <p>Hazırlık {@code @BeforeMethod} değil {@link IHookable} ile testin içinde koşar: hazırlık
 * hatası JUnit XML'de ayrı bir yapılandırma satırı olmaz, testin kendi hatası olur (test başına tek
 * satır; hata türü korunur — kırarak doğrula assertion hatasını kurulum hatasından ayırır).
 *
 * <p>Fikstür erişimi (plan §2.8): her ekran için {@code lowerCamel(SınıfAdı)()} erişimcisi; fikstür
 * adı = erişimcinin adı. Üretilen testler yalnızca bu erişimcileri çağırır.
 */
public abstract class TestTabani implements IHookable {

  private static final Logger LOG = Logger.getLogger(TestTabani.class.getName());

  /** Yalnızca sıfırlanmış veriyle anlamlı testlerin grubu (web: {@code @sifir-veri}). */
  public static final String SIFIR_VERI = "sifir-veri";

  private Ayarlar ayarlar;
  private Bayiler.BayiBilgisi bayi;
  private BayiKilidi kilit;
  private TestVerisi veri;
  private TestVerisi.Kirilma kirilma;
  private AppiumDriver surucu;
  private UygulamaOturumu oturum;
  private String metotAdi;

  private GirisEkrani girisEkrani;
  private KatalogEkrani katalogEkrani;
  private SepetEkrani sepetEkrani;
  private OnayEkrani onayEkrani;
  private SiparisEkrani siparisEkrani;

  /** Platform: sistem özelliği / ortam, yoksa TestNG parametresi {@code platform}. */
  static Platform platformCoz(Ayarlar ayarlar, String testngParametresi) {
    try {
      return ayarlar.platform();
    } catch (IllegalArgumentException e) {
      if (testngParametresi != null && !testngParametresi.isBlank()) {
        return Platform.coz(testngParametresi);
      }
      throw e;
    }
  }

  /** Metodun TestNG grupları. */
  static boolean grupta(Method metot, String grup) {
    Test t = metot.getAnnotation(Test.class);
    return t != null && Arrays.asList(t.groups()).contains(grup);
  }

  /** Hazırlık → test → kapanış. */
  @Override
  public void run(IHookCallBack geriCagri, ITestResult sonuc) {
    // Allure: story / tp-case / gruplar etiket olarak (üretilen test notasyon taşımaz; gruplar yeter).
    TestGruplari.allureyeEkle(sonuc.getMethod().getGroups());
    try {
      Method metot = sonuc.getMethod().getConstructorOrMethod().getMethod();
      metotAdi = metot.getName();
      hazirla(metot, sonuc.getTestContext());
      hazirlikSonrasi();
      geriCagri.runTestMethod(sonuc);
    } catch (RuntimeException | Error e) {
      // Hazırlık hatası (testin kendi hatası buraya gelmez, TestNG onu sonuca yazar).
      sonuc.setThrowable(e);
      throw e;
    } finally {
      Throwable hata = sonuc.getThrowable();
      kapat(hata != null && !(hata instanceof SkipException));
    }
  }

  /** Alt sınıf için: hazırlıktan sonra, testten önce ortak adım (web: {@code test.beforeEach}). */
  protected void hazirlikSonrasi() {}

  private void hazirla(Method metot, ITestContext baglam) {
    ayarlar = Ayarlar.oku();
    Platform platform = platformCoz(ayarlar, baglam.getCurrentXmlTest().getParameter("platform"));
    Kimlik.kur(platform, ayarlar);
    bayi = Bayiler.sinifIcin(getClass(), 0);

    TestVerisi.Kip kip = TestVerisi.kip(ayarlar);
    if (kip == TestVerisi.Kip.YALNIZ_SEPET && grupta(metot, SIFIR_VERI)) {
      throw new SkipException("TP_E2E_NO_RESET=1: sipariş geçmişi silinemez, '" + SIFIR_VERI + "' testi atlandı");
    }

    kilit = BayiKilidi.al(BayiKilidi.dizin(ayarlar.demoApiUrl()), bayi.kullaniciAdi(), ayarlar.bayiKilidiBekleme());
    veri = new TestVerisi(ayarlar);
    if (kip == TestVerisi.Kip.SIFIRLAMA) {
      veri.sifirla(bayi.kullaniciAdi());
      Optional<TestVerisi.Kirilma> istenen = TestVerisi.kirilma(ayarlar);
      if (istenen.isPresent()) {
        kirilma = istenen.get();
        veri.kir(kirilma, bayi.kullaniciAdi(), true);
      }
    } else {
      veri.sepetiBosalt(bayi);
    }

    surucu = SurucuFabrikasi.olustur(platform, ayarlar);
    oturum = new UygulamaOturumu(surucu, new Bekle(surucu, ayarlar.bekleme()));

    if (getClass().isAnnotationPresent(OturumAcik.class)) {
      girisEkrani().ac();
      girisEkrani().girisYap(bayi.kullaniciAdi(), bayi.parola());
      oturum
          .bekle()
          .kosul(
              "arayüzden giriş tamamlanmadı (kimlik '" + Kimlikler.Menu.BAYI_ADI + "')",
              s -> s.findElements(Kimlik.bul(Kimlikler.Menu.BAYI_ADI)).isEmpty() ? null : Boolean.TRUE);
    }
  }

  private void kapat(boolean basarisiz) {
    try {
      if (surucu != null && basarisiz) {
        Kanit.topla(surucu, ayarlar.kanitDizini(), getClass().getSimpleName(), metotAdi);
      }
    } finally {
      try {
        if (surucu != null) {
          try {
            surucu.quit();
          } catch (WebDriverException e) {
            LOG.log(Level.WARNING, "Appium oturumu kapatılamadı", e);
          }
        }
        if (kirilma != null && veri != null) {
          try {
            veri.kir(kirilma, bayi.kullaniciAdi(), false);
          } catch (RuntimeException e) {
            // Sonraki testin /test/reset'i kırılmayı da kaldırır.
            LOG.log(Level.WARNING, "kırılma (kampanya / ekilmiş hata) geri alınamadı", e);
          }
        }
      } finally {
        if (kilit != null) {
          kilit.close();
        }
        surucu = null;
        oturum = null;
        kilit = null;
        veri = null;
        kirilma = null;
        girisEkrani = null;
        katalogEkrani = null;
        sepetEkrani = null;
        onayEkrani = null;
        siparisEkrani = null;
      }
    }
  }

  private UygulamaOturumu oturum() {
    if (oturum == null) {
      throw new IllegalStateException("uygulama oturumu yok (TestTabani hazırlığı başarısız)");
    }
    return oturum;
  }

  /** Testin bayisi (elle yazılmış testler için; web: {@code dealer} fikstürü). */
  protected final Bayiler.BayiBilgisi bayi() {
    return bayi;
  }

  /** Giriş ekranı. */
  protected final GirisEkrani girisEkrani() {
    if (girisEkrani == null) {
      girisEkrani = new GirisEkrani(oturum());
    }
    return girisEkrani;
  }

  /** Ürün kataloğu ekranı. */
  protected final KatalogEkrani katalogEkrani() {
    if (katalogEkrani == null) {
      katalogEkrani = new KatalogEkrani(oturum());
    }
    return katalogEkrani;
  }

  /** Sepet ekranı. */
  protected final SepetEkrani sepetEkrani() {
    if (sepetEkrani == null) {
      sepetEkrani = new SepetEkrani(oturum());
    }
    return sepetEkrani;
  }

  /** Sipariş onayı ekranı. */
  protected final OnayEkrani onayEkrani() {
    if (onayEkrani == null) {
      onayEkrani = new OnayEkrani(oturum());
    }
    return onayEkrani;
  }

  /** Sipariş geçmişi ekranı. */
  protected final SiparisEkrani siparisEkrani() {
    if (siparisEkrani == null) {
      siparisEkrani = new SiparisEkrani(oturum());
    }
    return siparisEkrani;
  }
}
