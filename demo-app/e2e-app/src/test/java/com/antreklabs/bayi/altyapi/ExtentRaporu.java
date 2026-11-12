package com.antreklabs.bayi.altyapi;

import com.aventstack.extentreports.ExtentReports;
import com.aventstack.extentreports.ExtentTest;
import com.aventstack.extentreports.Status;
import com.aventstack.extentreports.markuputils.MarkupHelper;
import com.aventstack.extentreports.model.Log;
import com.aventstack.extentreports.model.Media;
import com.aventstack.extentreports.model.ScreenCapture;
import com.aventstack.extentreports.reporter.ExtentSparkReporter;
import com.aventstack.extentreports.reporter.JsonFormatter;
import java.io.IOException;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Arrays;
import java.util.Base64;
import java.util.Comparator;
import java.util.Date;
import java.util.IdentityHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.logging.Level;
import java.util.logging.Logger;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;
import org.testng.IExecutionListener;
import org.testng.ITestListener;
import org.testng.ITestResult;

/**
 * Extent (Spark) HTML raporu: {@code target/extent-report/index.html} — Allure'un yanında ikinci
 * okunur rapor. TestNG bu dinleyiciyi {@code META-INF/services/org.testng.ITestNGListener}
 * üzerinden kendisi yükler (testng.xml ve {@code -Dgroups} koşusunda aynı).
 *
 * <ul>
 *   <li><b>Tek dosya, dış kaynak yok:</b> Spark çevrimdışı kipte üretilir; Extent'in yanına
 *       kopyaladığı css/js/yazı tipi dosyaları {@code index.html} içine gömülür ve silinir. Rapor
 *       ağ olmadan ve portalın sandbox'ında (çerezsiz, opak köken) tek istekle açılır.
 *   <li><b>Kanıt:</b> başarısız testin {@link Kanit} ekran görüntüsü ({@code kanit/<Sınıf>.<metot>/
 *       ekran.png}; bu testte yazıldıysa) rapor modeline ve arşive <em>dosya yolu</em> olarak girer;
 *       koşu sonunda tek dosyaya gömülürken yoldan okunup base64 gömülür. Gömme sınırı
 *       ({@value #EN_COK_GOMULU_EKRAN}) koşu geneli sayılır (önceki tekrarlardan arşivle gelen
 *       ekranlar dahil); sonrakilerde rapor dizininden göreli bağlantı ve açıklama satırı. Model,
 *       arşiv ve bellek ekran sayısıyla / tekrar sayısıyla büyümez.
 *   <li><b>Yazım:</b> ara yazım seyrektir (her {@value #ARA_YAZIM_TEST} testte bir ya da
 *       {@value #ARA_YAZIM_MS} ms'de bir; ara raporun css/js'i yanındaki dizindedir). Kesintide
 *       (SIGTERM, JVM kapanışı) kapanış kancası son durumu en çok {@value #KESINTI_SURE_MS} ms'de
 *       yazar. Tek dosyaya gömme koşu sonunda yapılır.
 *   <li><b>Atomik yazım:</b> Spark ve arşiv önce geçici dosyalara yazar; yalnız tamamlanmış çıktı
 *       {@code index.html} / {@code extent.json} yerine taşınır. Yazım (ör. {@link OutOfMemoryError}
 *       ile) yarıda kalırsa önceki geçerli rapor (son ara yazım ya da önceki tekrar) kalır, yanına
 *       {@value #UYARI} yazılır; önceki rapor yoksa kısa açıklama sayfası.
 *   <li><b>Tekrarlı koşu:</b> her tekrar ayrı JVM'dir; {@code -Dextent.tekrar=<i>/<n>} ile
 *       {@code i > 1} tekrarında önceki tekrarların testleri rapor dizinindeki {@code extent.json}
 *       arşivinden geri yüklenir, rapor tekrarları birlikte gösterir (tekrar test adına eklenir).
 *       Tekrarsız koşu ve ilk tekrar arşivi ve eski raporu siler: {@code clean}'siz yeniden koşuda
 *       eski koşunun sonuçları rapora karışmaz.
 *   <li><b>Test adı:</b> {@code @Test(description)} (yoksa {@code Sınıf › metot}); alt bilgi
 *       {@code Sınıf.metot}. Kategoriler TestNG gruplarıdır, {@code tp-case-*} hariç (case kimliği
 *       test ayrıntısında ayrı satır; {@link TestGruplari}).
 *   <li><b>İç içe koşu:</b> bir testin kendi başlattığı TestNG koşusunun testleri rapora girmez
 *       (JUnit XML ile aynı test listesi).
 *   <li><b>İş parçacığı güvenliği:</b> test düğümleri sonuç nesnesine göre eşlenir; rapora yazım
 *       tek kilit altındadır.
 *   <li><b>Koşuyu düşürmez:</b> raporlama hatası ({@link OutOfMemoryError} dahil) yalnızca günlüğe
 *       yazılır ve rapor kapatılır (bkz. atomik yazım); testler ve Surefire JUnit XML'i etkilenmez.
 *   <li><b>Kaçış:</b> ad, alt bilgi, kategori, cihaz ve bilgi satırları HTML'e kaçışlı girer
 *       ({@code & < > " ' \}); Spark test adını {@code <script>} içindeki bir JS dizesine de
 *       yazar (zaman çizelgesi), tırnak ve ters bölü oradan da çıkamaz. Grafik etiketleri tarayıcıda
 *       bu altı varlıktan çözülür (yalnız canvas metni; HTML'e geri yazılmaz).
 * </ul>
 *
 * <p>Dizin: sistem özelliği {@code extent.rapor.dizini} (pom: {@code target/extent-report}); boş
 * verilirse rapor üretilmez.
 */
public final class ExtentRaporu implements IExecutionListener, ITestListener {

  /** Rapor dosyası (rapor dizini altında). */
  public static final String RAPOR = "index.html";
  /** Tekrarlar arası arşiv (rapor dizini altında). */
  public static final String ARSIV = "extent.json";
  /** Gömülecek tek bir kaynağın (css/js/yazı tipi) üst sınırı. */
  static final long EN_BUYUK_KAYNAK = 8L * 1024 * 1024;
  /** Gömülecek ekran görüntüsünün üst sınırı. */
  static final long EN_BUYUK_EKRAN = 10L * 1024 * 1024;
  /** Rapora gömülen ekran görüntüsü sayısının üst sınırı (sonrakiler göreli bağlantı). */
  public static final int EN_COK_GOMULU_EKRAN = 50;
  /** Kesintide (kapanış kancası) son durumu yazmaya ayrılan en uzun süre (ms). */
  public static final long KESINTI_SURE_MS = 10_000;
  /** Spark'ın yazdığı geçici rapor (tamamlanınca {@link #RAPOR} yerine taşınır). */
  static final String YENI_RAPOR = ".index.yeni.html";
  /** Arşivin geçici dosyası (tamamlanınca {@link #ARSIV} yerine taşınır). */
  static final String YENI_ARSIV = ".extent.yeni.json";
  /** Rapor güncellenemediğinde önceki raporun yanına yazılan uyarı. */
  public static final String UYARI = "index.uyari.txt";
  /** Ara yazım: bu kadar test bittiğinde … */
  public static final int ARA_YAZIM_TEST = 25;
  /** … ya da son yazımdan bu kadar süre (ms) geçtiğinde. */
  public static final long ARA_YAZIM_MS = 30_000;

  private static final Logger LOG = Logger.getLogger(ExtentRaporu.class.getName());
  /** Süreç genelinde tek rapor: TestNG dinleyiciyi her (iç içe) koşu için yeniden örnekler. */
  private static final Durum ORTAK = new Durum(null, null, null);

  /** Rapor modeline yol olarak girebilen ekran görüntüsü yolu (Spark yolu kaçışsız yazar). */
  private static final String GUVENLI_YOL = "[A-Za-z0-9._/-]+";
  private static final Pattern GUVENLI_YOL_DESENI = Pattern.compile(GUVENLI_YOL);
  /**
   * Zaman çizelgesi etiketleri: Spark adı JS dizesine kaçışlı (HTML varlığı) yazar; canvas varlık
   * çözmez. Bu betik {@code spark-script.js}'ten (grafik çizimi) hemen önce yalnız bilinen altı
   * varlığı düz metne çevirir; sonuç yalnız canvas etiketi olur, DOM'a HTML olarak yazılmaz.
   */
  public static final String ZAMAN_CIZELGESI_COZUCU =
      "<script>if(typeof timeline!==\"undefined\"){(function(){"
          + "var c={\"&amp;\":\"&\",\"&lt;\":\"<\",\"&gt;\":\">\",\"&quot;\":'\"',\"&#39;\":\"'\",\"&#92;\":\"\\\\\"},y={};"
          + "for(var k in timeline){y[k.replace(/&(?:amp|lt|gt|quot|#39|#92);/g,function(e){return c[e];})]=timeline[k];}"
          + "timeline=y;})();}</script>";
  /** Rapor sayfasındaki yerel başvurular: css {@code <link>}, simge {@code <link>}, betik, {@code url(…)}. */
  private static final Pattern GOMULECEK =
      Pattern.compile(
          "<link\\b[^>]*\\bhref=\"(?<css>[^\"]+\\.css)\"[^>]*>"
              + "|(?<simgeOn><link\\b[^>]*\\bhref=\")(?<simge>[^\"]+\\.(?:png|ico|svg))(?<simgeSon>\"[^>]*>)"
              + "|<script\\b[^>]*\\bsrc=\"(?<js>[^\"]+\\.js)\"[^>]*>\\s*</script>"
              + "|<img data-featherlight='(?<ekran>" + GUVENLI_YOL + ")' src=\"\\k<ekran>\">"
              + "|url\\(\\s*['\"]?(?<url>[^'\")]+?)['\"]?\\s*\\)");
  private static final Pattern SATIR_SONU = Pattern.compile("[\\r\\n\\u2028\\u2029\\u0085]+\\s*");
  private static final Pattern CSS_URL = Pattern.compile("url\\(\\s*['\"]?([^'\")]+?)['\"]?\\s*\\)");
  private static final Pattern DIS_KAYNAK = Pattern.compile("^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//|#)");

  /** Bir raporun durumu; alanlar {@code this} kilidi altında okunur/yazılır. */
  private static final class Durum {
    private final Path dizinSecimi;
    private final Path kanitKoku;
    private final String tekrar;
    private final Map<ITestResult, ExtentTest> testler = new IdentityHashMap<>();
    private ExtentReports rapor;
    private Path dizin;
    private boolean kapali;
    /** İç içe TestNG koşusu sayacı (bir test kendi içinde TestNG çalıştırabilir). */
    private int derinlik;
    /** Son yazımdan bu yana biten test sayısı ve son yazımın zamanı ({@link System#nanoTime}). */
    private int yazilmayan;
    private long sonYazim;
    /** Koşu genelinde (arşivden gelen önceki tekrarlar dahil) gömülecek ekran görüntüsü sayısı. */
    private int gomuluEkran;
    /** Kesintide son durumu yazan kapanış kancası (koşu sonunda kaldırılır). */
    private Thread kanca;

    /** {@code null} verilen değer sistem özelliğinden okunur (birim testleri açıkça verir). */
    Durum(Path dizin, Path kanitKoku, String tekrar) {
      this.dizinSecimi = dizin;
      this.kanitKoku = kanitKoku;
      this.tekrar = tekrar;
    }

    synchronized boolean kapali() {
      return kapali;
    }
  }

  private final Durum d;

  /** TestNG'nin kullandığı kurucu (süreç genelindeki ortak rapor). */
  public ExtentRaporu() {
    this(ORTAK);
  }

  /**
   * Ortak rapordan bağımsız, verilen dizinlere yazan dinleyici (birim testleri). {@code tekrar}
   * boş olabilir.
   */
  public ExtentRaporu(Path raporDizini, Path kanitKoku, String tekrar) {
    this(new Durum(raporDizini, kanitKoku, tekrar == null ? "" : tekrar));
  }

  private ExtentRaporu(Durum durum) {
    this.d = durum;
  }

  /** Raporlama bir hata yüzünden (ya da boş dizin seçimiyle) devre dışı mı. */
  public boolean kapali() {
    return d.kapali();
  }

  // ------------------------------------------------------------------ TestNG olayları

  @Override
  public void onExecutionStart() {
    synchronized (d) {
      d.derinlik++;
    }
    guvenli("başlatma", this::baslat);
  }

  @Override
  public void onExecutionFinish() {
    synchronized (d) {
      d.derinlik = Math.max(0, d.derinlik - 1);
      if (d.derinlik > 0) {
        return; // iç içe TestNG koşusu bitti; rapor dıştaki koşuyla kapanır
      }
    }
    guvenli(
        "kapanış",
        () -> {
          synchronized (d) {
            try {
              yaz(true);
            } finally {
              d.rapor = null;
              d.testler.clear();
              d.gomuluEkran = 0;
              kancaKaldir();
            }
          }
        });
  }

  @Override
  public void onTestStart(ITestResult sonuc) {
    guvenli("test başlangıcı", () -> dugum(sonuc));
  }

  @Override
  public void onTestSuccess(ITestResult sonuc) {
    bitir(sonuc, Status.PASS);
  }

  @Override
  public void onTestFailure(ITestResult sonuc) {
    bitir(sonuc, Status.FAIL);
  }

  @Override
  public void onTestSkipped(ITestResult sonuc) {
    bitir(sonuc, Status.SKIP);
  }

  @Override
  public void onTestFailedButWithinSuccessPercentage(ITestResult sonuc) {
    bitir(sonuc, Status.WARNING);
  }

  @Override
  public void onTestFailedWithTimeout(ITestResult sonuc) {
    bitir(sonuc, Status.FAIL);
  }

  // ------------------------------------------------------------------ rapor

  /** Raporun yazılacağı dizin; {@code extent.rapor.dizini} boşsa {@code null} (rapor kapalı). */
  static Path raporDizini() {
    String secim = System.getProperty("extent.rapor.dizini", "target/extent-report").trim();
    return secim.isEmpty() ? null : Path.of(secim);
  }

  /** Açıklamasız test adı: {@code Sınıf › metot} (+ {@code (tekrar 2/3)}); JUnit kimliğiyle aynı biçim. */
  public static String testAdi(String sinif, String metot, String tekrar) {
    return testAdi(sinif, metot, null, tekrar);
  }

  /**
   * Rapordaki test adı: {@code @Test(description)}, yoksa {@code Sınıf › metot}; tekrarlı koşuda
   * {@code (tekrar 2/3)} eklenir.
   */
  public static String testAdi(String sinif, String metot, String aciklama, String tekrar) {
    // Satır sonları tek boşluk: ad zaman çizelgesinde tek satırlık bir JS dizesidir.
    String ad =
        aciklama == null || aciklama.isBlank()
            ? basitAd(sinif) + " › " + metot
            : SATIR_SONU.matcher(aciklama.strip()).replaceAll(" ");
    return tekrar == null || tekrar.isBlank() ? ad : ad + " (tekrar " + tekrar.trim() + ")";
  }

  /** Test adının altındaki bilgi: {@code Sınıf.metot} (açıklama ad olduğunda testin kod kimliği). */
  public static String altBilgi(String sinif, String metot) {
    return basitAd(sinif) + "." + metot;
  }

  private static String basitAd(String sinif) {
    return sinif.substring(sinif.lastIndexOf('.') + 1);
  }

  /**
   * Önceki tekrarların arşivi geri yüklenir mi: yalnız {@code extent.tekrar} verilmiş ve ilk tekrar
   * değilse ({@code 2/3}, {@code 3/3}). Sayı okunamayan boş olmayan değer tekrar sayılır.
   */
  public static boolean arsivGeriYuklenir(String tekrar) {
    if (tekrar == null || tekrar.isBlank()) {
      return false;
    }
    String sira = tekrar.trim().split("/", 2)[0].trim();
    try {
      return Integer.parseInt(sira) > 1;
    } catch (NumberFormatException e) {
      return true;
    }
  }

  private String tekrar() {
    return d.tekrar != null ? d.tekrar : System.getProperty("extent.tekrar");
  }

  private void baslat() throws IOException {
    synchronized (d) {
      if (d.rapor != null || d.kapali) {
        return;
      }
      d.dizin = d.dizinSecimi != null ? d.dizinSecimi : raporDizini();
      if (d.dizin == null) {
        d.kapali = true;
        return;
      }
      Files.createDirectories(d.dizin);
      ExtentReports r = new ExtentReports();
      Path arsiv = d.dizin.resolve(ARSIV);
      int onceki = 0;
      for (String gecici : List.of(YENI_RAPOR, YENI_ARSIV, RAPOR + ".tmp", UYARI)) {
        Files.deleteIfExists(d.dizin.resolve(gecici));
      }
      if (!arsivGeriYuklenir(tekrar())) {
        // Tekrarsız koşu / ilk tekrar: önceki koşunun arşivi ve raporu bu koşuya karışmaz (bu
        // koşunun raporu üretilemezse eski koşunun raporu geçerliymiş gibi kalmasın).
        Files.deleteIfExists(arsiv);
        Files.deleteIfExists(d.dizin.resolve(RAPOR));
      } else if (Files.isRegularFile(arsiv)) {
        try {
          r.createDomainFromJsonArchive(arsiv.toFile());
          onceki = ekranSayisi(r);
        } catch (IOException | RuntimeException e) {
          // Bozuk arşiv: önceki tekrarlar raporda görünmez; bu koşunun raporu yine üretilir.
          LOG.log(Level.WARNING, "Extent arşivi okunamadı; önceki tekrarlar rapora eklenmedi", e);
          r = new ExtentReports();
        }
      }
      // Spark ve arşiv geçici dosyalara yazar; tamamlanan çıktı taşınır (bkz. yaz).
      ExtentSparkReporter spark = new ExtentSparkReporter(d.dizin.resolve(YENI_RAPOR).toFile());
      // Çevrimdışı kip: css/js CDN yerine rapor dizinine kopyalanır (sonra index.html'e gömülür).
      spark.config().enableOfflineMode(true);
      spark.config().setEncoding(StandardCharsets.UTF_8.name());
      spark.config().setDocumentTitle("Bayi Sipariş Portalı — Extent raporu");
      spark.config().setReportName("Uygulama e2e (Appium + TestNG)");
      spark.config().setTimeStampFormat("dd.MM.yyyy HH:mm:ss");
      r.attachReporter(new JsonFormatter(d.dizin.resolve(YENI_ARSIV).toFile()), spark);
      String platform = ozellik("platform", "PLATFORM");
      if (platform != null) {
        r.setSystemInfo("Platform", kacis(platform));
      }
      String cihaz = ozellik("device.name", "DEVICE_NAME");
      if (cihaz != null) {
        r.setSystemInfo("Cihaz", kacis(cihaz));
      }
      r.setSystemInfo("Java", kacis(System.getProperty("java.version", "?")));
      r.setSystemInfo("İşletim sistemi", kacis(System.getProperty("os.name", "?")));
      d.rapor = r;
      d.gomuluEkran = onceki;
      d.yazilmayan = 0;
      d.sonYazim = System.nanoTime();
      kancaKur();
    }
  }

  /** Raporda (arşivden geri yüklenen testler dahil) bulunan ekran görüntüsü sayısı. */
  private static int ekranSayisi(ExtentReports r) {
    int n = 0;
    for (com.aventstack.extentreports.model.Test t : r.getReport().getTestList()) {
      n += ekranSayisi(t);
    }
    return n;
  }

  private static int ekranSayisi(com.aventstack.extentreports.model.Test t) {
    int n = 0;
    for (Media m : t.getMedia()) {
      n += m instanceof ScreenCapture ? 1 : 0;
    }
    for (Log l : t.getLogs()) {
      n += l.getMedia() instanceof ScreenCapture ? 1 : 0;
    }
    for (com.aventstack.extentreports.model.Test c : t.getChildren()) {
      n += ekranSayisi(c);
    }
    return n;
  }

  // ------------------------------------------------------------------ kesinti

  /** Kapanış kancasını kurar ({@code d} kilidi altında çağrılır). */
  private void kancaKur() {
    if (d.kanca != null) {
      return;
    }
    Thread k = new Thread(this::kesintideYaz, "extent-raporu-kesinti");
    try {
      Runtime.getRuntime().addShutdownHook(k);
      d.kanca = k;
    } catch (IllegalStateException | SecurityException e) {
      // JVM zaten kapanıyor ya da kanca kurulamıyor: kesintide yalnız son ara yazım kalır.
    }
  }

  /** Koşu normal bittiyse kancayı kaldırır ({@code d} kilidi altında çağrılır). */
  private void kancaKaldir() {
    Thread k = d.kanca;
    d.kanca = null;
    if (k == null || Thread.currentThread() == k) {
      return;
    }
    try {
      Runtime.getRuntime().removeShutdownHook(k);
    } catch (IllegalStateException | SecurityException e) {
      // JVM kapanıyor: kanca zaten çalışıyor/çalışacak; rapor kapalıysa hiçbir şey yazmaz.
    }
  }

  /**
   * Kesinti (SIGTERM / JVM kapanışı, koşu bitmeden): o ana kadarki testleri koşu sonu gibi yazar.
   * Yazım ayrı bir iş parçacığında en çok {@link #KESINTI_SURE_MS} ms beklenir (kapanış uzamaz);
   * {@link OutOfMemoryError} dahil hata önceki geçerli raporu bozmaz (atomik yazım). Kapanış
   * kancası çağırır; birim testleri doğrudan çağırabilir.
   */
  public void kesintideYaz() {
    Thread yazici =
        new Thread(
            () -> {
              try {
                synchronized (d) {
                  if (d.rapor == null || d.kapali) {
                    return;
                  }
                  d.kanca = null;
                  try {
                    yaz(true);
                  } finally {
                    d.rapor = null;
                    d.testler.clear();
                    d.kapali = true; // kapanış sürerken gelen olaylar raporu yeniden açmaz
                  }
                }
              } catch (Throwable e) {
                LOG.log(Level.WARNING, "Extent raporu kesintide yazılamadı", e);
                kapanisSayfasi(d.dizin, "kesinti", e);
              }
            },
            "extent-raporu-kesinti-yazim");
    yazici.setDaemon(true);
    yazici.start();
    try {
      yazici.join(KESINTI_SURE_MS);
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
    }
  }

  private static String ozellik(String sistem, String ortam) {
    String v = System.getProperty(sistem);
    if (v == null || v.isBlank()) {
      v = System.getenv(ortam);
    }
    return v == null || v.isBlank() ? null : v.trim();
  }

  private ExtentTest dugum(ITestResult sonuc) throws IOException {
    synchronized (d) {
      // İç içe koşunun (testin kendi çalıştırdığı TestNG) testleri rapora girmez: JUnit XML'de de yoklar.
      if (d.derinlik > 1) {
        return null;
      }
    }
    baslat();
    synchronized (d) {
      if (d.rapor == null) {
        return null;
      }
      ExtentTest t = d.testler.get(sonuc);
      if (t == null) {
        String sinif = sonuc.getTestClass() != null ? sonuc.getTestClass().getName() : "?";
        String metot = sonuc.getMethod().getMethodName();
        t =
            d.rapor.createTest(
                // Extent adı/alt bilgiyi kaçışsız gömer; açıklama case başlığından gelir.
                kacis(testAdi(sinif, metot, sonuc.getMethod().getDescription(), tekrar())),
                kacis(altBilgi(sinif, metot)));
        String[] gruplar = sonuc.getMethod().getGroups();
        List<String> kategoriler = TestGruplari.kategoriler(gruplar);
        if (!kategoriler.isEmpty()) {
          t.assignCategory(kategoriler.stream().map(ExtentRaporu::kacis).toArray(String[]::new));
        }
        for (String kimlik : TestGruplari.caseler(gruplar)) {
          t.info("Testing Probe case: " + kacis(kimlik));
        }
        String platform = ozellik("platform", "PLATFORM");
        if (platform != null) {
          t.assignDevice(kacis(platform));
        }
        d.testler.put(sonuc, t);
      }
      return t;
    }
  }

  private void bitir(ITestResult sonuc, Status durum) {
    guvenli(
        "test sonucu",
        () -> {
          ExtentTest t = dugum(sonuc);
          if (t == null) {
            return;
          }
          synchronized (d) {
            if (d.rapor == null) {
              return;
            }
            Throwable hata = sonuc.getThrowable();
            Object[] parametreler = sonuc.getParameters();
            if (parametreler != null && parametreler.length > 0) {
              t.info("Parametreler: " + kacis(Arrays.deepToString(parametreler)));
            }
            if (durum == Status.FAIL || durum == Status.WARNING) {
              ekranEkle(t, sonuc);
            }
            if (hata != null) {
              hatayiYaz(t, durum, hata);
            } else if (durum == Status.SKIP) {
              t.skip("Atlandı");
            } else {
              t.log(durum, durum == Status.PASS ? "Geçti" : "Başarısız");
            }
            if (sonuc.getStartMillis() > 0) {
              t.getModel().setStartTime(new Date(sonuc.getStartMillis()));
            }
            if (sonuc.getEndMillis() > 0) {
              t.getModel().setEndTime(new Date(sonuc.getEndMillis()));
            }
            d.testler.remove(sonuc);
            d.yazilmayan++;
            // Ara yazım seyrektir (her yazım tüm raporu yeniden üretir; her testte yazmak test
            // sayısıyla karesel büyür). Koşu süre sınırında kesilse de o ana kadarki rapor kalır.
            if (d.yazilmayan >= ARA_YAZIM_TEST
                || System.nanoTime() - d.sonYazim >= ARA_YAZIM_MS * 1_000_000L) {
              yaz(false);
            }
          }
        });
  }

  /**
   * Extent yığın izini kaçışsız bir {@code <textarea>} içine yazar; {@code <150,00 TL>} gibi metin
   * orada olduğu gibi görünür. Yalnızca {@code </textarea} içeren ileti (uygulamadan okunan metin
   * olabilir) alanı kapatıp rapora HTML sokabilir: o durumda iz kaçışlı kod bloğu olarak yazılır.
   */
  private static void hatayiYaz(ExtentTest t, Status durum, Throwable hata) {
    StringWriter iz = new StringWriter();
    hata.printStackTrace(new PrintWriter(iz, true));
    if (iz.toString().toLowerCase(Locale.ROOT).contains("</textarea")) {
      t.log(durum, MarkupHelper.createCodeBlock(kacis(iz.toString())));
    } else {
      t.log(durum, hata);
    }
  }

  /**
   * HTML metni ve öznitelik değeri için kaçış: {@code & < > " ' \}. Extent adı, alt bilgiyi,
   * kategorileri ve bilgi satırlarını kaçışsız gömer; Spark test adını ayrıca {@code <script>}
   * içinde çift tırnaklı bir JS dizesine yazar ({@code dashboard.ftl} zaman çizelgesi). Tırnak ve
   * ters bölü varlık olarak yazıldığından ad o dizeden çıkamaz, {@code <} ile {@code </script>}
   * de oluşamaz.
   */
  public static String kacis(String metin) {
    StringBuilder out = new StringBuilder(metin.length() + 16);
    for (int i = 0; i < metin.length(); i++) {
      char c = metin.charAt(i);
      switch (c) {
        case '&' -> out.append("&amp;");
        case '<' -> out.append("&lt;");
        case '>' -> out.append("&gt;");
        case '"' -> out.append("&quot;");
        case '\'' -> out.append("&#39;");
        case '\\' -> out.append("&#92;");
        default -> out.append(c);
      }
    }
    return out.toString();
  }

  /**
   * Bu testte toplanan kanıt ekran görüntüsünü ekler: koşu genelinde ilk
   * {@link #EN_COK_GOMULU_EKRAN} görüntü modele (ve arşive) rapor dizininden göreli <em>yol</em>
   * olarak girer — base64'e koşu sonunda {@link #tekDosya} çevirir; sonrakiler göreli bağlantı ve
   * açıklama satırıdır.
   */
  private void ekranEkle(ExtentTest t, ITestResult sonuc) throws IOException {
    Path png = ekranDosyasi(sonuc);
    if (png == null) {
      return;
    }
    String yol = goreliYol(d.dizin, png);
    if (d.gomuluEkran < EN_COK_GOMULU_EKRAN && GUVENLI_YOL_DESENI.matcher(yol).matches()) {
      t.addScreenCaptureFromPath(yol, "Ekran görüntüsü");
      d.gomuluEkran++;
      return;
    }
    t.info(
        "Ekran görüntüsü rapora gömülmedi (ilk "
            + EN_COK_GOMULU_EKRAN
            + " başarısız test gömülür); kanıt dosyası: <a href=\""
            + kacis(yol)
            + "\" target=\"_blank\">"
            + kacis(yol)
            + "</a>");
  }

  /** {@code dosya}'nın rapor dizininden göreli yolu ({@code /} ayraçlı); göreli olamıyorsa mutlak yol. */
  static String goreliYol(Path raporDizini, Path dosya) {
    Path hedef = dosya.toAbsolutePath().normalize();
    try {
      return raporDizini.toAbsolutePath().normalize().relativize(hedef).toString().replace('\\', '/');
    } catch (IllegalArgumentException e) {
      return hedef.toString().replace('\\', '/');
    }
  }

  /** Bu testte toplanan kanıt ekran görüntüsü dosyası; yoksa, boşsa, büyükse ya da eski koşudansa null. */
  private Path ekranDosyasi(ITestResult sonuc) {
    try {
      Class<?> sinif = sonuc.getTestClass().getRealClass();
      Path kok = d.kanitKoku != null ? d.kanitKoku : Path.of(System.getProperty("kanit.dizini", "target/kanit"));
      Path png = Kanit.dizin(kok, sinif.getSimpleName(), sonuc.getMethod().getMethodName()).resolve(Kanit.EKRAN);
      if (!Files.isRegularFile(png) || Files.size(png) == 0 || Files.size(png) > EN_BUYUK_EKRAN) {
        return null;
      }
      // Dosya saati saniyeye yuvarlanabilir: bir saniyelik pay.
      if (Files.getLastModifiedTime(png).toMillis() + 1000 < sonuc.getStartMillis()) {
        return null;
      }
      return png;
    } catch (IOException | RuntimeException e) {
      return null;
    }
  }

  /**
   * Raporu yazar; {@code son} ise (koşu sonu) tek dosyaya indirger ve gömülen kaynakların
   * dizinlerini siler. Ara yazım yalnız Extent'in kendi yazımıdır: ara rapor css/js'i yanındaki
   * dizinden okur (Extent çevrimdışı kaynakları yalnızca başlangıçta kopyalar; bu yüzden dizin
   * ancak koşu sonunda silinir).
   */
  private void yaz(boolean son) throws IOException {
    synchronized (d) {
      if (d.rapor == null) {
        return;
      }
      Path yeniRapor = d.dizin.resolve(YENI_RAPOR);
      Path yeniArsiv = d.dizin.resolve(YENI_ARSIV);
      Files.deleteIfExists(yeniRapor);
      Files.deleteIfExists(yeniArsiv);
      d.rapor.flush();
      d.yazilmayan = 0;
      d.sonYazim = System.nanoTime();
      // Extent yazım hatasını yalnız günlüğe yazar: yarım dosya önceki geçerli çıktının yerine geçmez.
      if (tamamlanmis(yeniArsiv, "]", "}")) {
        tasi(yeniArsiv, d.dizin.resolve(ARSIV));
      } else {
        Files.deleteIfExists(yeniArsiv);
        LOG.warning("Extent arşivi yazılamadı; önceki arşiv korunuyor");
      }
      if (!tamamlanmis(yeniRapor, "</html>")) {
        Files.deleteIfExists(yeniRapor);
        if (son) {
          throw new IOException("Spark raporu tamamlanamadı");
        }
        LOG.warning("Extent ara raporu yazılamadı; önceki rapor korunuyor");
        return;
      }
      if (son) {
        tekDosya(yeniRapor, d.dizin.resolve(RAPOR), true);
      } else {
        tasi(yeniRapor, d.dizin.resolve(RAPOR));
      }
    }
  }

  /** Dosya var ve (boşluklar hariç) verilen sonlardan biriyle bitiyor mu (yarım yazım değil). */
  private static boolean tamamlanmis(Path dosya, String... sonlar) throws IOException {
    if (!Files.isRegularFile(dosya)) {
      return false;
    }
    long boy = Files.size(dosya);
    if (boy == 0) {
      return false;
    }
    byte[] kuyruk = new byte[(int) Math.min(256, boy)];
    try (var k = java.nio.channels.FileChannel.open(dosya)) {
      java.nio.ByteBuffer b = java.nio.ByteBuffer.wrap(kuyruk);
      long konum = boy - kuyruk.length;
      while (b.hasRemaining() && k.read(b, konum + b.position()) > 0) {
        // kuyruğun tamamı okunana dek
      }
    }
    String son = new String(kuyruk, StandardCharsets.UTF_8).strip().toLowerCase(Locale.ROOT);
    for (String s : sonlar) {
      if (son.endsWith(s)) {
        return true;
      }
    }
    return false;
  }

  /** Atomik taşıma (dosya sistemi desteklemiyorsa yerine yazarak). */
  private static void tasi(Path kaynak, Path hedef) throws IOException {
    try {
      Files.move(kaynak, hedef, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
    } catch (java.nio.file.AtomicMoveNotSupportedException e) {
      Files.move(kaynak, hedef, StandardCopyOption.REPLACE_EXISTING);
    }
  }

  // ------------------------------------------------------------------ tek dosya

  /**
   * Çevrimdışı Spark raporunun yerel css/js dosyalarını (ve css içindeki yazı tipi/görselleri)
   * {@code index.html} içine gömer; {@code temizle} ise gömülen kaynakların dizinlerini siler.
   * Bulunamayan ya da rapor dizini dışına çıkan başvuruya dokunulmaz.
   */
  public static void tekDosya(Path html, boolean temizle) throws IOException {
    tekDosya(html, html, temizle);
  }

  /**
   * {@link #tekDosya(Path, boolean)}; {@code kaynak} raporu okunur, sonuç önce {@code <hedef>.tmp}'ye
   * yazılıp {@code hedef}'in yerine atomik taşınır (yarıda kalan yazım {@code hedef}'i bozmaz).
   * Modeldeki ekran görüntüsü yolları ({@code <img data-featherlight='yol' …>}) base64 gömülür:
   * yalnız rapor dizininin üst dizini altındaki {@link Kanit#EKRAN} dosyaları, en çok
   * {@link #EN_COK_GOMULU_EKRAN} tane.
   */
  static void tekDosya(Path kaynakHtml, Path hedef, boolean temizle) throws IOException {
    Path html = kaynakHtml;
    if (!Files.isRegularFile(html)) {
      return;
    }
    // Mutlak yol: rapor dizini göreli verilse de (-Dextent.rapor.dizini=target/…) başvurular çözülür.
    Path mutlak = html.toAbsolutePath().normalize();
    Path kok = mutlak.getParent();
    int ekranlar = 0;
    // Tek geçiş (bellek: kaynak metin + çıktı; ara kopya yok): css/js dosyaları gömülür, simge ve
    // satır içi stil başvuruları (logo) veri adresine çevrilir.
    String kaynak = Files.readString(html, StandardCharsets.UTF_8);
    Set<Path> gomulen = new LinkedHashSet<>();
    StringBuilder sonuc = new StringBuilder(kaynak.length() + 1024 * 1024);
    Matcher m = GOMULECEK.matcher(kaynak);
    int son = 0;
    while (m.find()) {
      String yeni = null;
      if (m.group("css") != null) {
        Path css = yerel(kok, kok, m.group("css"));
        if (css != null) {
          String icerik = cssGom(kok, css, Files.readString(css, StandardCharsets.UTF_8));
          gomulen.add(css);
          yeni = "<style>" + icerik.replace("</style", "<\\/style") + "</style>";
        }
      } else if (m.group("js") != null) {
        Path js = yerel(kok, kok, m.group("js"));
        if (js != null) {
          gomulen.add(js);
          // Grafik çizimi spark-script.js'tedir: zaman çizelgesi etiketleri ondan önce çözülür.
          String once = js.getFileName().toString().equals("spark-script.js") ? ZAMAN_CIZELGESI_COZUCU : "";
          yeni = once + "<script>" + Files.readString(js, StandardCharsets.UTF_8).replace("</script", "<\\/script") + "</script>";
        }
      } else if (m.group("ekran") != null) {
        Path png = ekranlar < EN_COK_GOMULU_EKRAN ? ekranYolu(kok, m.group("ekran")) : null;
        if (png != null) {
          ekranlar++;
          // Extent'in base64 ekran biçimi (tıklanınca büyür); veri tek kez yer alır.
          yeni =
              "<a href=\"data:image/png;base64,"
                  + Base64.getEncoder().encodeToString(Files.readAllBytes(png))
                  + "\" data-featherlight=\"image\"><span class=\"badge badge-gradient-primary\">base64 img</span></a>";
        }
      } else if (m.group("simge") != null) {
        Path simge = yerel(kok, kok, m.group("simge"));
        yeni = simge == null ? null : m.group("simgeOn") + veriAdresi(simge) + m.group("simgeSon");
      } else {
        yeni = cssUrl(kok, mutlak, m.group("url"));
      }
      sonuc.append(kaynak, son, m.start()).append(yeni != null ? yeni : m.group());
      son = m.end();
    }
    boolean ayni = mutlak.equals(hedef.toAbsolutePath().normalize());
    if (gomulen.isEmpty() && ekranlar == 0) {
      if (!ayni) {
        tasi(html, hedef);
      }
      return;
    }
    sonuc.append(kaynak, son, kaynak.length());
    kaynak = null; // yazım sırasında yalnız çıktı bellekte kalsın
    Path gecici = hedef.resolveSibling(hedef.getFileName() + ".tmp");
    try (Writer w = Files.newBufferedWriter(gecici, StandardCharsets.UTF_8)) {
      w.append(sonuc);
    }
    sonuc = null;
    tasi(gecici, hedef);
    if (!ayni) {
      Files.deleteIfExists(html);
    }
    if (!temizle) {
      return;
    }
    // Extent kaynakları rapor dizininin alt dizinlerine kopyalar; artık gerekmezler.
    for (Path p : gomulen) {
      Path ust = kok.resolve(kok.relativize(p).getName(0));
      if (Files.isDirectory(ust) && !ust.equals(kok)) {
        sil(ust);
      }
    }
  }

  /**
   * Modeldeki ekran görüntüsü yolunun dosyası: rapor dizinine göre çözülür; rapor dizininin üst
   * dizini dışına çıkan, {@link Kanit#EKRAN} adlı olmayan, eksik ya da büyük dosya → null.
   */
  private static Path ekranYolu(Path kok, String yol) throws IOException {
    Path sinir = kok.getParent() != null ? kok.getParent() : kok;
    Path p;
    try {
      p = kok.resolve(yol).normalize();
    } catch (InvalidPathException e) {
      return null;
    }
    if (!p.startsWith(sinir)
        || !Kanit.EKRAN.equals(String.valueOf(p.getFileName()))
        || !Files.isRegularFile(p)
        || Files.size(p) > EN_BUYUK_EKRAN) {
      return null;
    }
    return p;
  }

  private static String cssGom(Path kok, Path css, String icerik) throws IOException {
    return degistir(CSS_URL, icerik, m -> cssUrl(kok, css, m.group(1)));
  }

  /** {@code url(ham)} başvurusunun gömülü karşılığı ({@code css}: başvuruyu içeren dosya); null → dokunulmaz. */
  private static String cssUrl(Path kok, Path css, String basvuru) throws IOException {
    String ham = basvuru.trim();
    if (ham.startsWith("data:")) {
      return null;
    }
    Path dosya = yerel(kok, css.getParent(), ham);
    if (dosya == null) {
      return null;
    }
    // Aynı yazı tipinin woff2'si gömülüyorsa eski biçimler (eot/ttf/otf/woff/svg) gömülmez:
    // tarayıcı woff2'yi seçer, rapor ~1 MB küçülür.
    return eskiBicim(dosya) ? "url(data:,)" : "url(" + veriAdresi(dosya) + ")";
  }

  private static String veriAdresi(Path dosya) throws IOException {
    String veri = Base64.getEncoder().encodeToString(Files.readAllBytes(dosya));
    return "data:" + tur(dosya.getFileName().toString()) + ";base64," + veri;
  }

  private static boolean eskiBicim(Path dosya) {
    String ad = dosya.getFileName().toString();
    int nokta = ad.lastIndexOf('.');
    if (nokta < 0 || !ad.substring(nokta + 1).toLowerCase(Locale.ROOT).matches("eot|ttf|otf|woff|svg")) {
      return false;
    }
    return Files.isRegularFile(dosya.resolveSibling(ad.substring(0, nokta) + ".woff2"));
  }

  /** {@code basvuru}'nun rapor dizini içindeki gerçek dosyası; dış/eksik/büyük/dışarı taşan → null. */
  private static Path yerel(Path kok, Path taban, String basvuru) throws IOException {
    if (DIS_KAYNAK.matcher(basvuru).find()) {
      return null;
    }
    String yol = basvuru.split("[?#]", 2)[0];
    if (yol.isEmpty()) {
      return null;
    }
    Path p;
    try {
      p = taban.resolve(yol).normalize();
    } catch (InvalidPathException e) {
      return null;
    }
    if (!p.startsWith(kok) || !Files.isRegularFile(p) || Files.size(p) > EN_BUYUK_KAYNAK) {
      return null;
    }
    return p;
  }

  private static String tur(String ad) {
    String a = ad.toLowerCase(Locale.ROOT);
    if (a.endsWith(".woff2")) {
      return "font/woff2";
    } else if (a.endsWith(".woff")) {
      return "font/woff";
    } else if (a.endsWith(".ttf")) {
      return "font/ttf";
    } else if (a.endsWith(".otf")) {
      return "font/otf";
    } else if (a.endsWith(".eot")) {
      return "application/vnd.ms-fontobject";
    } else if (a.endsWith(".svg")) {
      return "image/svg+xml";
    } else if (a.endsWith(".png")) {
      return "image/png";
    } else if (a.endsWith(".gif")) {
      return "image/gif";
    } else if (a.endsWith(".jpg") || a.endsWith(".jpeg")) {
      return "image/jpeg";
    }
    return "application/octet-stream";
  }

  @FunctionalInterface
  private interface Donusum {
    /** Eşleşmenin yerine geçecek metin; null → eşleşme olduğu gibi kalır. */
    String uygula(Matcher m) throws IOException;
  }

  private static String degistir(Pattern desen, String metin, Donusum donusum) throws IOException {
    Matcher m = desen.matcher(metin);
    StringBuilder out = new StringBuilder(metin.length());
    int son = 0;
    while (m.find()) {
      String yeni = donusum.uygula(m);
      out.append(metin, son, m.start()).append(yeni != null ? yeni : m.group());
      son = m.end();
    }
    return out.append(metin, son, metin.length()).toString();
  }

  private static void sil(Path silinecek) throws IOException {
    try (Stream<Path> yollar = Files.walk(silinecek)) {
      for (Path p : yollar.sorted(Comparator.reverseOrder()).toList()) {
        Files.deleteIfExists(p);
      }
    }
  }

  // ------------------------------------------------------------------ hata yalıtımı

  @FunctionalInterface
  private interface Is {
    void yap() throws IOException;
  }

  /**
   * Raporlama hatası testi/koşuyu etkilemez: günlüğe yazılır, rapor bu JVM için kapatılır.
   * {@link OutOfMemoryError} de yakalanır (büyük rapor yazımı): rapor modeli bırakılınca bellek geri
   * döner, koşu ve Surefire JUnit XML'i sürer.
   */
  private void guvenli(String adim, Is is) {
    if (d.kapali()) {
      return;
    }
    try {
      is.yap();
    } catch (IOException | RuntimeException | LinkageError | OutOfMemoryError e) {
      Path dizin;
      synchronized (d) {
        d.kapali = true;
        d.rapor = null;
        d.testler.clear();
        dizin = d.dizin;
        kancaKaldir();
      }
      LOG.log(Level.WARNING, "Extent raporu devre dışı (" + adim + ")", e);
      kapanisSayfasi(dizin, adim, e);
    }
  }

  /**
   * Raporlama hatasında: önceki geçerli {@code index.html} (bu koşunun son ara yazımı ya da önceki
   * tekrar) varsa korunur ve yanına {@link #UYARI} yazılır; yoksa kısa bir açıklama sayfası
   * yazılır. Geçici dosyalar silinir. Yazılamazsa sessizce geçer (rapor dizini hiç oluşmamış
   * olabilir).
   */
  private static void kapanisSayfasi(Path dizin, String adim, Throwable hata) {
    if (dizin == null || !Files.isDirectory(dizin)) {
      return;
    }
    try {
      for (String gecici : List.of(RAPOR + ".tmp", YENI_RAPOR, YENI_ARSIV)) {
        Files.deleteIfExists(dizin.resolve(gecici));
      }
      if (Files.isRegularFile(dizin.resolve(RAPOR))) {
        Files.writeString(
            dizin.resolve(UYARI),
            "Extent raporu bu koşuda güncellenemedi ("
                + adim
                + ": "
                + hata.getClass().getSimpleName()
                + ").\nindex.html önceki geçerli raporu gösterir (bu koşunun son ara yazımı ya da önceki"
                + " tekrar); sonraki testler eksik olabilir.\nTest sonuçları etkilenmedi: JUnit XML"
                + " (surefire-reports) ve Allure sonuçlarına bakın.\n",
            StandardCharsets.UTF_8);
        return;
      }
      String sayfa =
          "<!doctype html><html lang=\"tr\"><head><meta charset=\"utf-8\"><title>Extent raporu üretilemedi</title>"
              + "</head><body><h1>Extent raporu üretilemedi</h1><p>Raporlama hatası ("
              + kacis(adim)
              + ": "
              + kacis(hata.getClass().getSimpleName())
              + ") nedeniyle rapor bu koşu için kapatıldı. Test sonuçları etkilenmedi: JUnit XML"
              + " (surefire-reports) ve Allure sonuçlarına bakın.</p></body></html>";
      Files.writeString(dizin.resolve(RAPOR), sayfa, StandardCharsets.UTF_8);
    } catch (IOException | RuntimeException | OutOfMemoryError e) {
      LOG.log(Level.FINE, "Extent açıklama sayfası yazılamadı", e);
    }
  }
}
