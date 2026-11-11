package com.antreklabs.bayi.altyapi;

import com.aventstack.extentreports.ExtentReports;
import com.aventstack.extentreports.ExtentTest;
import com.aventstack.extentreports.Status;
import com.aventstack.extentreports.markuputils.MarkupHelper;
import com.aventstack.extentreports.reporter.ExtentSparkReporter;
import com.aventstack.extentreports.reporter.JsonFormatter;
import java.io.IOException;
import java.io.PrintWriter;
import java.io.StringWriter;
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
 *       ekran.png}; bu testte yazıldıysa) rapora base64 gömülür.
 *   <li><b>Tekrarlı koşu:</b> her tekrar ayrı JVM'dir; önceki tekrarların testleri rapor
 *       dizinindeki {@code extent.json} arşivinden geri yüklenir, rapor tekrarları birlikte
 *       gösterir ({@code -Dextent.tekrar=2/3} test adına eklenir).
 *   <li><b>İç içe koşu:</b> bir testin kendi başlattığı TestNG koşusunun testleri rapora girmez
 *       (JUnit XML ile aynı test listesi).
 *   <li><b>İş parçacığı güvenliği:</b> test düğümleri sonuç nesnesine göre eşlenir; rapora yazım
 *       tek kilit altındadır.
 *   <li><b>Koşuyu düşürmez:</b> raporlama hatası yalnızca günlüğe yazılır ve rapor kapatılır.
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

  private static final Logger LOG = Logger.getLogger(ExtentRaporu.class.getName());
  /** Süreç genelinde tek rapor: TestNG dinleyiciyi her (iç içe) koşu için yeniden örnekler. */
  private static final Durum ORTAK = new Durum(null, null, null);

  private static final Pattern STIL = Pattern.compile("<link\\b[^>]*\\bhref=\"([^\"]+\\.css)\"[^>]*>");
  private static final Pattern SIMGE =
      Pattern.compile("(<link\\b[^>]*\\bhref=\")([^\"]+\\.(?:png|ico|svg))(\"[^>]*>)");
  private static final Pattern BETIK = Pattern.compile("<script\\b[^>]*\\bsrc=\"([^\"]+\\.js)\"[^>]*>\\s*</script>");
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

  /** Rapordaki test adı: {@code Sınıf › metot} (+ {@code (tekrar 2/3)}); JUnit kimliğiyle aynı biçim. */
  public static String testAdi(String sinif, String metot, String tekrar) {
    String basit = sinif.substring(sinif.lastIndexOf('.') + 1);
    String ad = basit + " › " + metot;
    return tekrar == null || tekrar.isBlank() ? ad : ad + " (tekrar " + tekrar.trim() + ")";
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
      if (Files.isRegularFile(arsiv)) {
        try {
          r.createDomainFromJsonArchive(arsiv.toFile());
        } catch (IOException | RuntimeException e) {
          // Bozuk arşiv: önceki tekrarlar raporda görünmez; bu koşunun raporu yine üretilir.
          LOG.log(Level.WARNING, "Extent arşivi okunamadı; önceki tekrarlar rapora eklenmedi", e);
          r = new ExtentReports();
        }
      }
      ExtentSparkReporter spark = new ExtentSparkReporter(d.dizin.resolve(RAPOR).toFile());
      // Çevrimdışı kip: css/js CDN yerine rapor dizinine kopyalanır (sonra index.html'e gömülür).
      spark.config().enableOfflineMode(true);
      spark.config().setEncoding(StandardCharsets.UTF_8.name());
      spark.config().setDocumentTitle("Bayi Sipariş Portalı — Extent raporu");
      spark.config().setReportName("Uygulama e2e (Appium + TestNG)");
      spark.config().setTimeStampFormat("dd.MM.yyyy HH:mm:ss");
      r.attachReporter(new JsonFormatter(arsiv.toFile()), spark);
      String platform = ozellik("platform", "PLATFORM");
      if (platform != null) {
        r.setSystemInfo("Platform", platform);
      }
      String cihaz = ozellik("device.name", "DEVICE_NAME");
      if (cihaz != null) {
        r.setSystemInfo("Cihaz", cihaz);
      }
      r.setSystemInfo("Java", System.getProperty("java.version", "?"));
      r.setSystemInfo("İşletim sistemi", System.getProperty("os.name", "?"));
      d.rapor = r;
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
        String tekrar = d.tekrar != null ? d.tekrar : System.getProperty("extent.tekrar");
        t = d.rapor.createTest(testAdi(sinif, sonuc.getMethod().getMethodName(), tekrar));
        String[] gruplar = sonuc.getMethod().getGroups();
        if (gruplar != null && gruplar.length > 0) {
          t.assignCategory(gruplar);
        }
        String platform = ozellik("platform", "PLATFORM");
        if (platform != null) {
          t.assignDevice(platform);
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
              String ekran = ekranGoruntusu(sonuc);
              if (ekran != null) {
                t.addScreenCaptureFromBase64String(ekran, "Ekran görüntüsü");
              }
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
          }
          // Her testten sonra yazılır: koşu süre sınırında kesilse de o ana kadarki rapor kalır.
          yaz(false);
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

  private static String kacis(String metin) {
    return metin.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
  }

  /** Bu testte toplanan kanıt ekran görüntüsü (base64); yoksa ya da eski bir koşudansa null. */
  private String ekranGoruntusu(ITestResult sonuc) {
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
      return Base64.getEncoder().encodeToString(Files.readAllBytes(png));
    } catch (IOException | RuntimeException e) {
      return null;
    }
  }

  /**
   * Raporu yazar ve tek dosyaya indirger. Extent çevrimdışı kaynakları yalnızca başlangıçta
   * kopyalar; bu yüzden kaynak dizini ancak koşu sonunda ({@code temizle}) silinir.
   */
  private void yaz(boolean temizle) throws IOException {
    synchronized (d) {
      if (d.rapor == null) {
        return;
      }
      d.rapor.flush();
      tekDosya(d.dizin.resolve(RAPOR), temizle);
    }
  }

  // ------------------------------------------------------------------ tek dosya

  /**
   * Çevrimdışı Spark raporunun yerel css/js dosyalarını (ve css içindeki yazı tipi/görselleri)
   * {@code index.html} içine gömer; {@code temizle} ise gömülen kaynakların dizinlerini siler.
   * Bulunamayan ya da rapor dizini dışına çıkan başvuruya dokunulmaz.
   */
  public static void tekDosya(Path html, boolean temizle) throws IOException {
    if (!Files.isRegularFile(html)) {
      return;
    }
    // Mutlak yol: rapor dizini göreli verilse de (-Dextent.rapor.dizini=target/…) başvurular çözülür.
    Path mutlak = html.toAbsolutePath().normalize();
    Path kok = mutlak.getParent();
    // Önce sayfanın kendi satır içi stil başvuruları (logo), sonra css/js dosyaları.
    String kaynak = cssGom(kok, mutlak, Files.readString(html, StandardCharsets.UTF_8));
    Set<Path> gomulen = new LinkedHashSet<>();

    String sonuc =
        degistir(
            STIL,
            kaynak,
            m -> {
              Path css = yerel(kok, kok, m.group(1));
              if (css == null) {
                return null;
              }
              String icerik = cssGom(kok, css, Files.readString(css, StandardCharsets.UTF_8));
              gomulen.add(css);
              return "<style>" + icerik.replace("</style", "<\\/style") + "</style>";
            });
    sonuc =
        degistir(
            BETIK,
            sonuc,
            m -> {
              Path js = yerel(kok, kok, m.group(1));
              if (js == null) {
                return null;
              }
              gomulen.add(js);
              return "<script>" + Files.readString(js, StandardCharsets.UTF_8).replace("</script", "<\\/script") + "</script>";
            });
    if (gomulen.isEmpty()) {
      return;
    }
    sonuc =
        degistir(
            SIMGE,
            sonuc,
            m -> {
              Path simge = yerel(kok, kok, m.group(2));
              return simge == null ? null : m.group(1) + veriAdresi(simge) + m.group(3);
            });
    Path gecici = html.resolveSibling(RAPOR + ".tmp");
    Files.writeString(gecici, sonuc, StandardCharsets.UTF_8);
    Files.move(gecici, html, StandardCopyOption.REPLACE_EXISTING);
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

  private static String cssGom(Path kok, Path css, String icerik) throws IOException {
    return degistir(
        CSS_URL,
        icerik,
        m -> {
          String ham = m.group(1).trim();
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
        });
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

  /** Raporlama hatası testi/koşuyu etkilemez: günlüğe yazılır, rapor bu JVM için kapatılır. */
  private void guvenli(String adim, Is is) {
    if (d.kapali()) {
      return;
    }
    try {
      is.yap();
    } catch (IOException | RuntimeException | LinkageError e) {
      synchronized (d) {
        d.kapali = true;
        d.rapor = null;
      }
      LOG.log(Level.WARNING, "Extent raporu devre dışı (" + adim + ")", e);
    }
  }
}
