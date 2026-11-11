package com.antreklabs.bayi.birim;

import static org.testng.Assert.assertEquals;
import static org.testng.Assert.assertFalse;
import static org.testng.Assert.assertTrue;

import com.antreklabs.bayi.altyapi.ExtentRaporu;
import com.antreklabs.bayi.altyapi.Kanit;
import java.lang.reflect.Proxy;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.regex.Pattern;
import org.testng.IClass;
import org.testng.ITestNGMethod;
import org.testng.ITestResult;
import org.testng.annotations.Test;

/**
 * Extent raporu dinleyicisi: tek dosyalı çevrimdışı rapor, kanıt ekran görüntüsü, tekrarların
 * birleşmesi, iç içe koşu, iş parçacığı güvenliği ve hata yalıtımı. Süreç genelindeki gerçek rapor
 * yerine geçici dizine yazan ayrı bir dinleyici örneği kullanılır.
 */
public class ExtentRaporuBirimTesti {

  private static final byte[] PNG = {(byte) 0x89, 'P', 'N', 'G', 13, 10, 26, 10, 1, 2, 3, 4, 5, 6, 7, 8};
  private static final String PNG_B64 = Base64.getEncoder().encodeToString(PNG);
  /** Sayfanın yüklediği dış kaynak (CDN css/js/görsel); lisans yorumlarındaki adresler sayılmaz. */
  private static final Pattern DIS_YUKLEME =
      Pattern.compile("(?:src|href)\\s*=\\s*[\"'](?:https?:)?//|url\\(\\s*[\"']?(?:https?:)?//");

  /** Sahte TestNG sonucu: {@code a.b.Sinif#metot} (açıklamasız, grup {@code duman}). */
  private static ITestResult sonuc(Class<?> sinif, String metot, Throwable hata, long baslangic) {
    return sonuc(sinif, metot, null, new String[] {"duman"}, hata, baslangic);
  }

  /** Sahte TestNG sonucu: açıklama ve gruplarla. */
  private static ITestResult sonuc(
      Class<?> sinif, String metot, String aciklama, String[] gruplar, Throwable hata, long baslangic) {
    ClassLoader cl = ExtentRaporuBirimTesti.class.getClassLoader();
    IClass testSinifi =
        (IClass)
            Proxy.newProxyInstance(
                cl,
                new Class<?>[] {IClass.class},
                (v, m, a) ->
                    switch (m.getName()) {
                      case "getName" -> sinif.getName();
                      case "getRealClass" -> sinif;
                      case "hashCode" -> System.identityHashCode(v);
                      case "equals" -> v == a[0];
                      default -> null;
                    });
    ITestNGMethod testMetodu =
        (ITestNGMethod)
            Proxy.newProxyInstance(
                cl,
                new Class<?>[] {ITestNGMethod.class},
                (v, m, a) ->
                    switch (m.getName()) {
                      case "getMethodName" -> metot;
                      case "getGroups" -> gruplar;
                      case "getDescription" -> aciklama;
                      case "hashCode" -> System.identityHashCode(v);
                      case "equals" -> v == a[0];
                      default -> m.getReturnType() == boolean.class ? Boolean.FALSE : m.getReturnType().isPrimitive() ? 0 : null;
                    });
    return (ITestResult)
        Proxy.newProxyInstance(
            cl,
            new Class<?>[] {ITestResult.class},
            (v, m, a) ->
                switch (m.getName()) {
                  case "getTestClass" -> testSinifi;
                  case "getMethod" -> testMetodu;
                  case "getThrowable" -> hata;
                  case "getParameters" -> new Object[0];
                  case "getStartMillis" -> baslangic;
                  case "getEndMillis" -> baslangic + 1500;
                  case "hashCode" -> System.identityHashCode(v);
                  case "equals" -> v == a[0];
                  default -> m.getReturnType() == boolean.class ? Boolean.FALSE : m.getReturnType().isPrimitive() ? 0 : null;
                });
  }

  private static String oku(Path dizin) throws Exception {
    return Files.readString(dizin.resolve("index.html"), StandardCharsets.UTF_8);
  }

  private static List<String> dosyalar(Path dizin) throws Exception {
    try (var s = Files.walk(dizin)) {
      return s.filter(Files::isRegularFile).map(p -> dizin.relativize(p).toString()).sorted().toList();
    }
  }

  @Test(groups = "birim")
  public void testAdiJunitKimligiBicimindedir() {
    assertEquals(ExtentRaporu.testAdi("a.b.SepetTesti", "kampanya", null), "SepetTesti › kampanya");
    assertEquals(ExtentRaporu.testAdi("Paketsiz", "m", " "), "Paketsiz › m");
    assertEquals(ExtentRaporu.testAdi("a.b.SepetTesti", "kampanya", "2/3"), "SepetTesti › kampanya (tekrar 2/3)");
  }

  @Test(groups = "birim")
  public void testAdiAciklamadirAltBilgiSinifMetot() {
    assertEquals(ExtentRaporu.testAdi("a.b.SepetTesti", "kampanya", " 7 adette 1 bedava ", null), "7 adette 1 bedava");
    assertEquals(ExtentRaporu.testAdi("a.b.SepetTesti", "kampanya", "7 adette 1 bedava", "2/3"), "7 adette 1 bedava (tekrar 2/3)");
    assertEquals(ExtentRaporu.testAdi("a.b.SepetTesti", "kampanya", " ", null), "SepetTesti › kampanya");
    assertEquals(ExtentRaporu.altBilgi("a.b.SepetTesti", "kampanya"), "SepetTesti.kampanya");
  }

  @Test(groups = "birim")
  public void arsivYalnizSonrakiTekrarlardaGeriYuklenir() {
    assertFalse(ExtentRaporu.arsivGeriYuklenir(null));
    assertFalse(ExtentRaporu.arsivGeriYuklenir(" "));
    assertFalse(ExtentRaporu.arsivGeriYuklenir("1/3"), "ilk tekrar temiz başlar");
    assertTrue(ExtentRaporu.arsivGeriYuklenir("2/3"));
    assertTrue(ExtentRaporu.arsivGeriYuklenir(" 3 / 3 "));
    assertTrue(ExtentRaporu.arsivGeriYuklenir("x"), "okunamayan tekrar değeri arşivi korur");
  }

  @Test(groups = "birim")
  public void tekrarsizYenidenKosuEskiSonuclariGetirmez() throws Exception {
    Path rapor = Files.createTempDirectory("extent-birim-");
    // 1. koşu (clean yok): kırmızı.
    ExtentRaporu ilk = new ExtentRaporu(rapor, rapor.resolve("kanit"), null);
    ilk.onExecutionStart();
    ITestResult eski = sonuc(ExtentRaporuBirimTesti.class, "eskiKirmizi", new AssertionError("eski koşu kaldı"), System.currentTimeMillis());
    ilk.onTestStart(eski);
    ilk.onTestFailure(eski);
    ilk.onExecutionFinish();
    assertTrue(Files.exists(rapor.resolve(ExtentRaporu.ARSIV)));
    // 2. koşu aynı dizine, extent.tekrar yok: rapor yalnız bu koşudur.
    ExtentRaporu ikinci = new ExtentRaporu(rapor, rapor.resolve("kanit"), null);
    ikinci.onExecutionStart();
    ITestResult yeni = sonuc(ExtentRaporuBirimTesti.class, "yesil", null, System.currentTimeMillis());
    ikinci.onTestStart(yeni);
    ikinci.onTestSuccess(yeni);
    ikinci.onExecutionFinish();
    String html = oku(rapor);
    assertTrue(html.contains("ExtentRaporuBirimTesti › yesil"));
    assertFalse(html.contains("eskiKirmizi"), "önceki koşunun testi rapora karışmamalı");
    assertFalse(html.contains("eski koşu kaldı"));
  }

  @Test(groups = "birim")
  public void aciklamaAdOlurCaseGrubuKategoriOlmaz() throws Exception {
    Path rapor = Files.createTempDirectory("extent-birim-");
    ExtentRaporu d = new ExtentRaporu(rapor, rapor.resolve("kanit"), null);
    d.onExecutionStart();
    String uuid = "3f9b1c2e-0000-5000-8000-0000000000c2";
    ITestResult s =
        sonuc(
            ExtentRaporuBirimTesti.class,
            "senaryo",
            "7 adet kampanyalı üründe 1 adet bedava verilir",
            new String[] {"uretilen", "web", "tp-case-" + uuid, "TPD-1"},
            null,
            System.currentTimeMillis());
    d.onTestStart(s);
    d.onTestSuccess(s);
    d.onExecutionFinish();
    String html = oku(rapor);
    assertTrue(html.contains("7 adet kampanyalı üründe 1 adet bedava verilir"), "ad = açıklama");
    assertTrue(html.contains("ExtentRaporuBirimTesti.senaryo"), "alt bilgi = Sınıf.metot");
    assertFalse(html.contains("ExtentRaporuBirimTesti › senaryo"), "açıklama varken Sınıf › metot ad olmaz");
    assertTrue(html.contains("Testing Probe case: " + uuid), "case kimliği ayrıntıda görünür");
    assertFalse(html.contains("tp-case-" + uuid), "tp-case grubu kategori olmaz");
    assertTrue(html.contains("TPD-1"), "story grubu kategoridir");
    assertTrue(html.contains("uretilen"), "diğer gruplar kategoridir");
  }

  @Test(groups = "birim")
  public void aciklamaRaporaHtmlSokamaz() throws Exception {
    Path rapor = Files.createTempDirectory("extent-birim-");
    ExtentRaporu d = new ExtentRaporu(rapor, rapor.resolve("kanit"), null);
    d.onExecutionStart();
    ITestResult s =
        sonuc(ExtentRaporuBirimTesti.class, "m", "<img src=x onerror=alert(1)> başlık", new String[] {"tp-case-<b>x</b>"}, null, System.currentTimeMillis());
    d.onTestStart(s);
    d.onTestSuccess(s);
    d.onExecutionFinish();
    String html = oku(rapor);
    assertFalse(html.contains("<img src=x"), "açıklama HTML olarak gömülmemeli");
    assertFalse(html.contains("<b>x</b>"), "case kimliği HTML olarak gömülmemeli");
  }

  @Test(groups = "birim")
  public void tekDosyaCevrimdisiRaporVeKanit() throws Exception {
    Path kok = Files.createTempDirectory("extent-birim-");
    Path rapor = kok.resolve("extent-report");
    Path kanit = kok.resolve("kanit");
    long simdi = System.currentTimeMillis();
    Path kirmiziKanit = Kanit.dizin(kanit, "ExtentRaporuBirimTesti", "kirmizi");
    Files.createDirectories(kirmiziKanit);
    Files.write(kirmiziKanit.resolve(Kanit.EKRAN), PNG);

    ExtentRaporu d = new ExtentRaporu(rapor, kanit, null);
    d.onExecutionStart();
    ITestResult yesil = sonuc(ExtentRaporuBirimTesti.class, "yesil", null, simdi);
    d.onTestStart(yesil);
    d.onTestSuccess(yesil);
    // Her testten sonra yazılır: koşu yarıda kesilse de o ana kadarki rapor tek dosya ve çevrimdışıdır.
    assertFalse(DIS_YUKLEME.matcher(oku(rapor)).find());
    assertFalse(oku(rapor).contains("spark/"));
    ITestResult kirmizi =
        sonuc(ExtentRaporuBirimTesti.class, "kirmizi", new AssertionError("'cart-total' metni: beklenen <150,00 TL>"), simdi);
    d.onTestStart(kirmizi);
    d.onTestFailure(kirmizi);
    ITestResult atlanan = sonuc(ExtentRaporuBirimTesti.class, "atlanan", null, simdi);
    d.onTestSkipped(atlanan);
    d.onExecutionFinish();

    String html = oku(rapor);
    assertTrue(html.contains("ExtentRaporuBirimTesti › yesil"), "geçen test");
    assertTrue(html.contains("ExtentRaporuBirimTesti › kirmizi"), "kalan test");
    assertTrue(html.contains("ExtentRaporuBirimTesti › atlanan"), "atlanan test");
    assertTrue(html.contains("beklenen <150,00 TL>"), "hata iletisi");
    assertTrue(html.contains(PNG_B64), "kanıt ekran görüntüsü gömülü");
    assertFalse(DIS_YUKLEME.matcher(html).find(), "dış kaynak yüklenmez");
    assertFalse(html.contains("spark/"), "yerel kaynak başvurusu kalmaz");
    assertTrue(html.contains("data:font/woff2;base64,"), "simge yazı tipi gömülü");
    // Rapor dizini: yalnızca rapor + tekrar arşivi (css/js/yazı tipi dosyaları silinmiş).
    assertEquals(dosyalar(rapor), List.of("extent.json", "index.html"));
  }

  @Test(groups = "birim")
  public void hataMetniRaporunHtmliniBozamaz() throws Exception {
    Path rapor = Files.createTempDirectory("extent-birim-");
    ExtentRaporu d = new ExtentRaporu(rapor, rapor.resolve("kanit"), null);
    d.onExecutionStart();
    // Uygulamadan okunan metin hata iletisine girer; Extent yığın izini kaçışsız <textarea>'ya yazar.
    ITestResult s =
        sonuc(ExtentRaporuBirimTesti.class, "kirmizi", new AssertionError("görülen <</TextArea><script>alert(1)</script>>"), System.currentTimeMillis());
    d.onTestStart(s);
    d.onTestFailure(s);
    d.onExecutionFinish();
    String html = oku(rapor);
    assertFalse(html.contains("<script>alert(1)"), "hata metni betik olarak gömülmemeli");
    assertTrue(html.contains("&lt;script&gt;alert(1)"), "hata metni kaçışlı görünmeli");
  }

  @Test(groups = "birim")
  public void eskiKosununEkranGoruntusuEklenmez() throws Exception {
    Path kok = Files.createTempDirectory("extent-birim-");
    Path kanit = kok.resolve("kanit");
    Path eski = Kanit.dizin(kanit, "ExtentRaporuBirimTesti", "kirmizi");
    Files.createDirectories(eski);
    Files.write(eski.resolve(Kanit.EKRAN), PNG);
    ExtentRaporu d = new ExtentRaporu(kok.resolve("r"), kanit, null);
    d.onExecutionStart();
    // Test, dosyadan bir saat SONRA başlamış: görüntü bu teste ait değil.
    ITestResult kirmizi =
        sonuc(ExtentRaporuBirimTesti.class, "kirmizi", new AssertionError("x"), System.currentTimeMillis() + 3_600_000);
    d.onTestStart(kirmizi);
    d.onTestFailure(kirmizi);
    d.onExecutionFinish();
    assertFalse(oku(kok.resolve("r")).contains(PNG_B64));
  }

  @Test(groups = "birim")
  public void tekrarlarTekRapordaBirlesir() throws Exception {
    Path kok = Files.createTempDirectory("extent-birim-");
    Path rapor = kok.resolve("extent-report");
    Path kanit = kok.resolve("kanit");
    Path kirmiziKanit = Kanit.dizin(kanit, "ExtentRaporuBirimTesti", "kirmizi");
    Files.createDirectories(kirmiziKanit);
    Files.write(kirmiziKanit.resolve(Kanit.EKRAN), PNG);
    for (String tekrar : List.of("1/2", "2/2")) {
      // Her tekrar ayrı JVM'dir: yeni dinleyici, aynı rapor dizini.
      ExtentRaporu d = new ExtentRaporu(rapor, kanit, tekrar);
      d.onExecutionStart();
      boolean ilk = tekrar.startsWith("1");
      ITestResult s =
          sonuc(ExtentRaporuBirimTesti.class, "kirmizi", ilk ? new AssertionError("ilk tekrar kaldı") : null, System.currentTimeMillis());
      d.onTestStart(s);
      if (ilk) {
        d.onTestFailure(s);
      } else {
        d.onTestSuccess(s);
      }
      d.onExecutionFinish();
    }
    String html = oku(rapor);
    assertTrue(html.contains("ExtentRaporuBirimTesti › kirmizi (tekrar 1/2)"));
    assertTrue(html.contains("ExtentRaporuBirimTesti › kirmizi (tekrar 2/2)"));
    assertTrue(html.contains("ilk tekrar kaldı"), "önceki tekrarın hatası korunur");
    assertTrue(html.contains(PNG_B64), "önceki tekrarın ekran görüntüsü korunur");
    assertFalse(html.contains("spark/"));
    assertEquals(dosyalar(rapor), List.of("extent.json", "index.html"));
  }

  @Test(groups = "birim")
  public void bozukArsivRaporuEngellemez() throws Exception {
    Path rapor = Files.createTempDirectory("extent-birim-");
    Files.writeString(rapor.resolve("extent.json"), "{bozuk", StandardCharsets.UTF_8);
    // Arşiv yalnız sonraki tekrarlarda okunur.
    ExtentRaporu d = new ExtentRaporu(rapor, rapor.resolve("kanit"), "2/2");
    d.onExecutionStart();
    ITestResult s = sonuc(ExtentRaporuBirimTesti.class, "yesil", null, System.currentTimeMillis());
    d.onTestStart(s);
    d.onTestSuccess(s);
    d.onExecutionFinish();
    assertTrue(oku(rapor).contains("ExtentRaporuBirimTesti › yesil (tekrar 2/2)"));
  }

  @Test(groups = "birim")
  public void icIceKosununTestleriRaporaGirmez() throws Exception {
    Path rapor = Files.createTempDirectory("extent-birim-");
    ExtentRaporu d = new ExtentRaporu(rapor, rapor.resolve("kanit"), null);
    d.onExecutionStart();
    ITestResult dis = sonuc(ExtentRaporuBirimTesti.class, "dis", null, System.currentTimeMillis());
    d.onTestStart(dis);
    // Test kendi içinde TestNG çalıştırır (TestTabaniBirimTesti böyle yapar).
    d.onExecutionStart();
    ITestResult ic = sonuc(ExtentRaporuBirimTesti.class, "ic", new AssertionError("iç koşu"), System.currentTimeMillis());
    d.onTestStart(ic);
    d.onTestFailure(ic);
    d.onExecutionFinish();
    d.onTestSuccess(dis);
    d.onExecutionFinish();
    String html = oku(rapor);
    assertTrue(html.contains("ExtentRaporuBirimTesti › dis"));
    assertFalse(html.contains("ExtentRaporuBirimTesti › ic"), "iç koşunun testi raporda olmamalı");
    assertFalse(html.contains("spark/"), "iç koşunun bitişi raporu erken kapatmamalı");
  }

  @Test(groups = "birim")
  public void paralelTestlerinHepsiRaporda() throws Exception {
    Path rapor = Files.createTempDirectory("extent-birim-");
    ExtentRaporu d = new ExtentRaporu(rapor, rapor.resolve("kanit"), null);
    d.onExecutionStart();
    ExecutorService havuz = Executors.newFixedThreadPool(8);
    try {
      List<Future<?>> isler = new ArrayList<>();
      for (int i = 0; i < 40; i++) {
        String ad = "paralel" + i;
        boolean kalir = i % 5 == 0;
        isler.add(
            havuz.submit(
                () -> {
                  ITestResult s =
                      sonuc(ExtentRaporuBirimTesti.class, ad, kalir ? new AssertionError(ad) : null, System.currentTimeMillis());
                  d.onTestStart(s);
                  if (kalir) {
                    d.onTestFailure(s);
                  } else {
                    d.onTestSuccess(s);
                  }
                }));
      }
      for (Future<?> f : isler) {
        f.get();
      }
    } finally {
      havuz.shutdownNow();
    }
    d.onExecutionFinish();
    assertFalse(d.kapali(), "raporlama hatasız tamamlanmalı");
    String html = oku(rapor);
    for (int i = 0; i < 40; i++) {
      assertTrue(html.contains("ExtentRaporuBirimTesti › paralel" + i + "<"), "paralel" + i);
    }
  }

  @Test(groups = "birim")
  public void raporlamaHatasiKosuyuDusurmez() throws Exception {
    // Rapor dizini bir DOSYANIN altında: oluşturulamaz. Dinleyici hiçbir olayda hata fırlatmamalı.
    Path dosya = Files.createTempFile("extent-birim-", ".txt");
    ExtentRaporu d = new ExtentRaporu(dosya.resolve("extent-report"), dosya.resolve("kanit"), null);
    d.onExecutionStart();
    ITestResult s = sonuc(ExtentRaporuBirimTesti.class, "kirmizi", new AssertionError("x"), System.currentTimeMillis());
    d.onTestStart(s);
    d.onTestFailure(s);
    d.onTestSkipped(s);
    d.onExecutionFinish();
    assertTrue(d.kapali());
  }

  @Test(groups = "birim")
  public void tekDosyaYalnizRaporDizinindekiKaynaklariGomer() throws Exception {
    Path kok = Files.createTempDirectory("extent-birim-");
    Path rapor = kok.resolve("extent-report");
    Files.createDirectories(rapor.resolve("spark"));
    Files.writeString(kok.resolve("disari.css"), "body{color:red}");
    Files.writeString(
        rapor.resolve("spark/a.css"),
        "@font-face{src:url('f.eot?v=1');src:url('f.woff2?v=1') format('woff2'),url(f.ttf) format('truetype')}"
            + ".x{background:url(data:image/png;base64,AAAA)}.y{background:url(https://ornek.test/y.png)}");
    Files.write(rapor.resolve("spark/f.woff2"), new byte[] {1, 2, 3});
    Files.write(rapor.resolve("spark/f.eot"), new byte[] {4});
    Files.write(rapor.resolve("spark/f.ttf"), new byte[] {5});
    Files.write(rapor.resolve("spark/logo.png"), PNG);
    Files.writeString(rapor.resolve("spark/b.js"), "var s='</script>';");
    Path html = rapor.resolve("index.html");
    Files.writeString(
        html,
        "<html><head><link rel=\"shortcut icon\" href=\"spark/logo.png\">"
            + "<link rel=\"stylesheet\" href=\"spark/a.css\">"
            + "<link rel=\"stylesheet\" href=\"../disari.css\">"
            + "<link rel=\"stylesheet\" href=\"https://cdn.ornek.test/x.css\">"
            + "</head><body><div style=\"background-image: url('spark/logo.png')\"></div>"
            + "<script src=\"spark/b.js\"></script><script src=\"yok.js\"></script></body></html>");

    // Rapor dizini çoğu zaman göreli verilir (-Dextent.rapor.dizini=target/…): göreli yolla çağrılır.
    ExtentRaporu.tekDosya(Path.of("").toAbsolutePath().relativize(html.toAbsolutePath()), true);

    String s = Files.readString(html, StandardCharsets.UTF_8);
    assertFalse(s.contains("spark/"), s);
    assertTrue(s.contains("url(data:font/woff2;base64,AQID) format('woff2')"), s);
    assertTrue(s.contains("src:url(data:,);"), "eski biçim gömülmez: " + s);
    assertTrue(s.contains("url(data:image/png;base64,AAAA)"), "veri adresi değişmez");
    assertTrue(s.contains("href=\"data:image/png;base64," + PNG_B64 + "\""), s);
    assertTrue(s.contains("background-image: url(data:image/png;base64," + PNG_B64 + ")"), s);
    assertTrue(s.contains("var s='<\\/script>';"), "gömülü betik etiketi kapatamaz: " + s);
    // Rapor dizini dışı, dış adres ve eksik dosya başvurularına dokunulmaz.
    assertTrue(s.contains("href=\"../disari.css\""));
    assertTrue(s.contains("href=\"https://cdn.ornek.test/x.css\""));
    assertTrue(s.contains("url(https://ornek.test/y.png)"));
    assertTrue(s.contains("<script src=\"yok.js\"></script>"));
    assertFalse(Files.exists(rapor.resolve("spark")), "gömülen kaynak dizini silinir");
    assertTrue(Files.exists(kok.resolve("disari.css")));
  }
}
