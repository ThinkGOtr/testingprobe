package com.antreklabs.tp.javaaraclar;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

/** Üretilen test koruması: geçerli dosya + uzun ihlal listesi (her biri beklenen kodla). */
class UretilenTestKoruyucuTest {
  static final Path KOK = Path.of("src/test/resources/e2e-app");
  static final String DOSYA = "src/test/java/com/antreklabs/bayi/uretilen/DEMO12C1_ab12cd34Test.java";
  static final String GIRIS = "girisEkrani().girisYap(\"bayi2\", \"Demo123!\");";
  static final String SEPETE = "katalogEkrani().sepeteEkle(\"P-001\", 7);";
  static final String BASLIK_TEST = "@Test(groups = {\"uretilen\", \"kampanya\"}, description = \"Kampanyalı ürün sepete eklenir\")";
  static final String SINIF = "public class DEMO12C1_ab12cd34Test extends TestTabani {";
  static final String METOT = "public void senaryo() {";
  static final String ARG = "girisYap(\"bayi2\"";

  static SembolCikarici.Tablo tablo;
  static String gecerli;

  @BeforeAll
  static void hazirla() throws IOException {
    tablo = SembolCikarici.cikar(KOK, Kaynaklar.TEST_KAYNAK);
    gecerli = Kaynaklar.oku(KOK.resolve(DOSYA));
  }

  static List<UretilenTestKoruyucu.Ihlal> denetle(String metin) {
    return UretilenTestKoruyucu.dosyaDenetle(DOSYA, metin, tablo);
  }

  @Test
  void gecerliDosyaIhlalsiz() {
    assertEquals(List.of(), denetle(gecerli));
  }

  @Test
  void bayiOpsiyonel() {
    String m = gecerli.replace("@Bayi(\"bayi2\")\n", "").replace("import com.antreklabs.bayi.altyapi.Bayi;\n", "");
    assertEquals(List.of(), denetle(m));
  }

  @Test
  void kacisliTersBoluUnicodeKacisiDegil() {
    // "\\u0041" Java'da ters bölü + "u0041" metnidir; kaçış değildir.
    String m = gecerli.replace("\"Demo123!\"", "\"Demo\\\\u0041\"");
    assertEquals(List.of(), denetle(m));
  }

  @Test
  void gizliTestVerisiOrtamdanOkunur() {
    // specs/013 K19: gizli test verisi yalnız System.getenv("TP_TESTVERI_…") doğrudan argümanı olarak.
    String m = gecerli.replace("\"Demo123!\"", "System.getenv(\"TP_TESTVERI_DEMO_PAROLA\")");
    assertTrue(!m.equals(gecerli));
    assertEquals(List.of(), denetle(m));
  }

  @Test
  void yanlisKonum() {
    List<UretilenTestKoruyucu.Ihlal> v = UretilenTestKoruyucu.dosyaDenetle(
        "src/test/java/com/antreklabs/bayi/testler/DEMO12C1_ab12cd34Test.java", gecerli, tablo);
    assertTrue(v.stream().anyMatch(i -> i.kod().equals("file_location")), v::toString);
    v = UretilenTestKoruyucu.dosyaDenetle("src/test/java/com/antreklabs/bayi/uretilen/Serbest.java",
        gecerli.replace("DEMO12C1_ab12cd34Test", "Serbest"), tablo);
    assertTrue(v.stream().anyMatch(i -> i.kod().equals("file_location")), v::toString);
  }

  static Stream<Arguments> ihlaller() {
    return Stream.of(
        // --- dal / döngü -----------------------------------------------------------------------
        Arguments.of("if", GIRIS, "if (true) { " + GIRIS + " }", "branch"),
        Arguments.of("switch", GIRIS, "switch (1) { default: " + GIRIS + " }", "branch"),
        Arguments.of("üçlü", ARG, "girisYap(" + "true ? \"bayi2\" : \"bayi1\"", "branch"),
        Arguments.of("for", GIRIS, "for (int i = 0; i < 2; i++) { " + GIRIS + " }", "loop"),
        Arguments.of("while", GIRIS, "while (true) { " + GIRIS + " }", "loop"),
        Arguments.of("do", GIRIS, "do { " + GIRIS + " } while (false);", "loop"),
        Arguments.of("foreach", GIRIS, "for (String s : new String[0]) { " + GIRIS + " }", "loop"),
        // --- lambda / new / dizi / metin bloğu -------------------------------------------------
        Arguments.of("lambda arg", ARG, "girisYap(" + "() -> \"bayi2\"", "lambda"),
        Arguments.of("metot başvurusu", ARG, "girisYap(" + "String::valueOf", "lambda"),
        Arguments.of("new arg", ARG, "girisYap(" + "new String(\"bayi2\")", "new"),
        Arguments.of("new deyim", GIRIS, "new Object();", "new"),
        Arguments.of("dizi arg", ARG, "girisYap(" + "new String[] {\"bayi2\"}", "array"),
        Arguments.of("metin bloğu", ARG, "girisYap(" + "\"\"\"\n      bayi2\"\"\"", "text_block"),
        // --- ham sürücü / statik çağrı / Thread.sleep / alan -----------------------------------
        Arguments.of("driver alanı", GIRIS, "driver.quit();", "raw_driver"),
        Arguments.of("driver erişimcisi", GIRIS, "driver().quit();", "raw_driver"),
        Arguments.of("driver zinciri", GIRIS, "driver.findElement(null).click();", "raw_driver"),
        // --- Playwright for Java tutamaçları (web projesi, 011 §2.6) ------------------------------
        Arguments.of("page erişimcisi", GIRIS, "page().navigate(\"/giris\");", "raw_driver"),
        Arguments.of("page alanı", GIRIS, "page.navigate(\"/giris\");", "raw_driver"),
        Arguments.of("page zinciri", GIRIS, "page().getByTestId(\"login-submit\").click();", "raw_driver"),
        Arguments.of("sayfa erişimcisi", GIRIS, "sayfa().reload();", "raw_driver"),
        Arguments.of("browser erişimcisi", GIRIS, "browser().close();", "raw_driver"),
        Arguments.of("context erişimcisi", GIRIS, "context().clearCookies();", "raw_driver"),
        Arguments.of("playwright alanı", GIRIS, "playwright.chromium().launch();", "raw_driver"),
        Arguments.of("playwright erişimcisi", GIRIS, "playwright().close();", "raw_driver"),
        Arguments.of("statik çağrı", GIRIS, "Kimlik.bul(\"login-username\");", "static_call"),
        Arguments.of("System.exit", GIRIS, "System.exit(0);", "static_call"),
        Arguments.of("Thread.sleep", GIRIS, "Thread.sleep(1000);", "thread_sleep"),
        Arguments.of("tam adlı Thread.sleep", GIRIS, "java.lang.Thread.sleep(1000);", "thread_sleep"),
        Arguments.of("alan arg", ARG, "girisYap(" + "Kimlikler.Giris.HATA", "field_access"),
        Arguments.of("değişken arg", ARG, "girisYap(" + "bayi", "field_access"),
        Arguments.of("alan üyesi", BASLIK_TEST, "private String x = \"a\";\n  " + BASLIK_TEST, "field"),
        Arguments.of("this", GIRIS, "this." + GIRIS, "this_super"),
        Arguments.of("super", GIRIS, "super." + GIRIS, "this_super"),
        Arguments.of("yerel değişken", GIRIS, "String a = \"x\";", "local_variable"),
        Arguments.of("var", GIRIS, "var a = 1;", "local_variable"),
        Arguments.of("atama", GIRIS, "driver = null;", "assignment"),
        // --- deyimler ---------------------------------------------------------------------------
        Arguments.of("return", GIRIS, "return;", "forbidden_statement"),
        Arguments.of("try", GIRIS, "try { " + GIRIS + " } catch (RuntimeException e) { }", "forbidden_statement"),
        Arguments.of("throw", GIRIS, "throw new IllegalStateException();", "forbidden_statement"),
        Arguments.of("synchronized", GIRIS, "synchronized (this) { }", "forbidden_statement"),
        Arguments.of("boş deyim", GIRIS, ";", "forbidden_statement"),
        Arguments.of("etiket", GIRIS, "etiket: " + GIRIS, "forbidden_statement"),
        Arguments.of("assert", GIRIS, "assert true;", "forbidden_statement"),
        Arguments.of("yerel sınıf", GIRIS, "class Y { }", "forbidden_statement"),
        Arguments.of("blok", GIRIS, "{ }", "forbidden_statement"),
        // --- çağrı biçimi -----------------------------------------------------------------------
        Arguments.of("zincir", GIRIS, "girisEkrani().girisYap(\"bayi2\", \"Demo123!\").toString();", "call_shape"),
        Arguments.of("kapsamsız çağrı", GIRIS, "girisYap(\"bayi2\", \"Demo123!\");", "call_shape"),
        Arguments.of("erişimci argümanlı", GIRIS, "girisEkrani(1).girisYap(\"bayi2\", \"Demo123!\");", "call_shape"),
        Arguments.of("tür argümanı", GIRIS, "girisEkrani().<String>girisYap(\"bayi2\", \"Demo123!\");", "call_shape"),
        Arguments.of("yansıma", GIRIS, "getClass().getName();", "unknown_accessor"),
        // --- sembol tablosu -----------------------------------------------------------------------
        Arguments.of("bilinmeyen metot", GIRIS, "girisEkrani().cikisYap();", "unknown_method"),
        Arguments.of("Object metodu", GIRIS, "girisEkrani().notify();", "unknown_method"),
        Arguments.of("bilinmeyen erişimci", GIRIS, "siparisEkrani().onayla();", "unknown_accessor"),
        Arguments.of("erişimci olmayan TestTabani metodu", GIRIS, "sepet().onayla();", "unknown_accessor"),
        Arguments.of("statik ekran metodu", GIRIS, "girisEkrani().surum();", "unknown_method"),
        Arguments.of("eksik argüman", GIRIS, "girisEkrani().girisYap(\"bayi2\");", "arg_count"),
        Arguments.of("fazla argüman", SEPETE, "katalogEkrani().sepeteEkle(\"P-001\", 7, 8);", "arg_count"),
        Arguments.of("string yerine int", SEPETE, "katalogEkrani().sepeteEkle(\"P-001\", \"7\");", "arg_type"),
        Arguments.of("int yerine double", SEPETE, "katalogEkrani().sepeteEkle(\"P-001\", 7.5);", "arg_type"),
        Arguments.of("int yerine long", SEPETE, "katalogEkrani().sepeteEkle(\"P-001\", 7L);", "arg_type"),
        Arguments.of("long yerine boolean", SEPETE, "katalogEkrani().urunAc(true);", "arg_type"),
        Arguments.of("boolean yerine string", SEPETE, "katalogEkrani().dogrulaIndirim(1.0, \"true\");", "arg_type"),
        Arguments.of("String yerine int", SEPETE, "sepetEkrani().dogrulaToplam(1250);", "arg_type"),
        // --- literal biçimi -----------------------------------------------------------------------
        Arguments.of("char", ARG, "girisYap(" + "'b'", "non_literal_argument"),
        Arguments.of("null", ARG, "girisYap(" + "null", "non_literal_argument"),
        Arguments.of("float", SEPETE, "katalogEkrani().dogrulaIndirim(1.5f, true);", "non_literal_argument"),
        Arguments.of("onaltılık", SEPETE, "katalogEkrani().sepeteEkle(\"P-001\", 0x10);", "non_literal_argument"),
        Arguments.of("alt çizgili sayı", SEPETE, "katalogEkrani().sepeteEkle(\"P-001\", 1_000);", "non_literal_argument"),
        Arguments.of("int taşması", SEPETE, "katalogEkrani().sepeteEkle(\"P-001\", 3000000000);", "non_literal_argument"),
        Arguments.of("çift eksi", SEPETE, "katalogEkrani().sepeteEkle(\"P-001\", - -1);", "non_literal_argument"),
        Arguments.of("artı", SEPETE, "katalogEkrani().sepeteEkle(\"P-001\", +1);", "non_literal_argument"),
        Arguments.of("parantez", ARG, "girisYap(" + "(\"bayi2\")", "non_literal_argument"),
        Arguments.of("birleştirme", ARG, "girisYap(" + "\"bay\" + \"i2\"", "non_literal_argument"),
        Arguments.of("eksi string", ARG, "girisYap(" + "-\"bayi2\"", "non_literal_argument"),
        // --- gizli test verisi (specs/013 K19) ----------------------------------------------------
        Arguments.of("getenv başka ad", ARG, "girisYap(" + "System.getenv(\"PATH\")", "static_call"),
        Arguments.of("getenv küçük harf", ARG, "girisYap(" + "System.getenv(\"TP_TESTVERI_x\")", "static_call"),
        Arguments.of("getenv boş ek", ARG, "girisYap(" + "System.getenv(\"TP_TESTVERI_\")", "static_call"),
        Arguments.of("getenv argümansız", ARG, "girisYap(" + "System.getenv()", "static_call"),
        Arguments.of("getenv iki argüman", ARG, "girisYap(" + "System.getenv(\"TP_TESTVERI_X\", \"Y\")", "static_call"),
        Arguments.of("getenv değişken", ARG, "girisYap(" + "System.getenv(x)", "static_call"),
        Arguments.of("getenv metin bloğu", ARG, "girisYap(" + "System.getenv(\"\"\"\n      TP_TESTVERI_X\"\"\")", "static_call"),
        Arguments.of("getenv tür argümanı", ARG, "girisYap(" + "System.<String>getenv(\"TP_TESTVERI_X\")", "static_call"),
        Arguments.of("getProperty", ARG, "girisYap(" + "System.getProperty(\"TP_TESTVERI_X\")", "static_call"),
        Arguments.of("tam adlı System", ARG, "girisYap(" + "java.lang.System.getenv(\"TP_TESTVERI_X\")", "static_call"),
        Arguments.of("başka kapsam", ARG, "girisYap(" + "Sistem.getenv(\"TP_TESTVERI_X\")", "static_call"),
        Arguments.of("getenv zinciri", ARG, "girisYap(" + "System.getenv(\"TP_TESTVERI_X\").trim()", "static_call"),
        Arguments.of("getenv parantez", ARG, "girisYap(" + "(System.getenv(\"TP_TESTVERI_X\"))", "static_call"),
        Arguments.of("getenv birleştirme", ARG, "girisYap(" + "\"a\" + System.getenv(\"TP_TESTVERI_X\")", "static_call"),
        Arguments.of("getenv deyim", GIRIS, "System.getenv(\"TP_TESTVERI_X\");", "static_call"),
        Arguments.of("getenv erişimci argümanı", GIRIS,
            "girisEkrani(System.getenv(\"TP_TESTVERI_X\")).girisYap(\"bayi2\", \"Demo123!\");", "static_call"),
        Arguments.of("getenv notasyonda", "@Bayi(\"bayi2\")", "@Bayi(System.getenv(\"TP_TESTVERI_X\"))", "static_call"),
        Arguments.of("getenv int parametreye", SEPETE,
            "katalogEkrani().sepeteEkle(\"P-001\", System.getenv(\"TP_TESTVERI_ADET\"));", "arg_type"),
        // --- import -------------------------------------------------------------------------------
        Arguments.of("ek import", "import org.testng.annotations.Test;\n",
            "import org.testng.annotations.Test;\nimport java.io.File;\n", "forbidden_import"),
        Arguments.of("statik import", "import org.testng.annotations.Test;\n",
            "import org.testng.annotations.Test;\nimport static java.lang.Thread.sleep;\n", "forbidden_import"),
        Arguments.of("joker import", "import org.testng.annotations.Test;\n", "import org.testng.annotations.*;\n", "forbidden_import"),
        Arguments.of("eksik import", "import org.testng.annotations.Test;\n", "", "missing_import"),
        Arguments.of("yinelenen import", "import org.testng.annotations.Test;\n",
            "import org.testng.annotations.Test;\nimport org.testng.annotations.Test;\n", "forbidden_import"),
        Arguments.of("Bayi importsuz", "import com.antreklabs.bayi.altyapi.Bayi;\n", "", "missing_import"),
        // --- notasyonlar --------------------------------------------------------------------------
        Arguments.of("Bayi değer=", "@Bayi(\"bayi2\")", "@Bayi(value = \"bayi2\")", "annotation"),
        Arguments.of("iki Bayi", "@Bayi(\"bayi2\")", "@Bayi(\"bayi2\")\n@Bayi(\"bayi1\")", "annotation"),
        Arguments.of("Bayi sabit", "@Bayi(\"bayi2\")", "@Bayi(Kimlikler.Giris.HATA)", "field_access"),
        Arguments.of("Bayi geçersiz", "@Bayi(\"bayi2\")", "@Bayi(\"bayi 2\")", "annotation"),
        Arguments.of("başka sınıf notasyonu", "@Bayi(\"bayi2\")", "@Bayi(\"bayi2\")\n@Listeners(X.class)", "annotation"),
        Arguments.of("metot notasyonu", BASLIK_TEST, BASLIK_TEST + "\n  @Deprecated", "annotation"),
        Arguments.of("@Test yok", BASLIK_TEST, "", "test_annotation"),
        Arguments.of("@Test işaret", BASLIK_TEST, "@Test", "test_annotation"),
        Arguments.of("groups yok", BASLIK_TEST, "@Test(description = \"x\")", "test_annotation"),
        Arguments.of("uretilen ilk değil", BASLIK_TEST, "@Test(groups = {\"kampanya\", \"uretilen\"})", "test_annotation"),
        Arguments.of("groups dizi değil", BASLIK_TEST, "@Test(groups = \"uretilen\")", "test_annotation"),
        Arguments.of("invocationCount", BASLIK_TEST, "@Test(groups = {\"uretilen\"}, invocationCount = 5)", "test_annotation"),
        Arguments.of("enabled", BASLIK_TEST, "@Test(groups = {\"uretilen\"}, enabled = false)", "test_annotation"),
        Arguments.of("description birleşik", BASLIK_TEST, "@Test(groups = {\"uretilen\"}, description = \"a\" + \"b\")", "test_annotation"),
        Arguments.of("iki @Test", BASLIK_TEST, BASLIK_TEST + "\n  " + BASLIK_TEST, "test_annotation"),
        Arguments.of("tam adlı @Test", BASLIK_TEST, "@org.testng.annotations.Test(groups = {\"uretilen\"})", "annotation"),
        // --- sınıf / metot biçimi -----------------------------------------------------------------
        Arguments.of("iki test metodu", "  }\n}\n", "  }\n  " + BASLIK_TEST + "\n  public void ikinci() {\n  }\n}\n", "test_method_count"),
        Arguments.of("yardımcı metot", "  }\n}\n", "  }\n  private void yardimci() {\n  }\n}\n", "test_method_count"),
        Arguments.of("kurucu", BASLIK_TEST, "public DEMO12C1_ab12cd34Test() { }\n  " + BASLIK_TEST, "forbidden_member"),
        Arguments.of("statik blok", BASLIK_TEST, "static { }\n  " + BASLIK_TEST, "forbidden_member"),
        Arguments.of("iç sınıf", BASLIK_TEST, "class Ic { }\n  " + BASLIK_TEST, "forbidden_member"),
        Arguments.of("ikinci üst düzey sınıf", "  }\n}\n", "  }\n}\nclass Ek { }\n", "top_level_type"),
        Arguments.of("arayüz", SINIF, "public interface DEMO12C1_ab12cd34Test extends TestTabani {", "top_level_type"),
        Arguments.of("başka taban", SINIF, "public class DEMO12C1_ab12cd34Test extends Object {", "class_shape"),
        Arguments.of("final sınıf", SINIF, "public final class DEMO12C1_ab12cd34Test extends TestTabani {", "class_shape"),
        Arguments.of("implements", SINIF, "public class DEMO12C1_ab12cd34Test extends TestTabani implements Runnable {", "class_shape"),
        Arguments.of("ad uyuşmazlığı", SINIF, "public class Baska extends TestTabani {", "class_shape"),
        Arguments.of("parametreli test", METOT, "public void senaryo(String x) {", "test_method"),
        Arguments.of("statik test", METOT, "public static void senaryo() {", "test_method"),
        Arguments.of("throws", METOT, "public void senaryo() throws Exception {", "test_method"),
        Arguments.of("dönüşlü test", METOT, "public int senaryo() {", "test_method"),
        Arguments.of("korumalı test", METOT, "protected void senaryo() {", "test_method"),
        Arguments.of("paket", "package com.antreklabs.bayi.uretilen;", "package com.antreklabs.bayi.testler;", "wrong_package"),
        Arguments.of("başlık yok", "// AI-generated — AI Testing Probe", "// Elle — AI Testing Probe", "missing_header"),
        // --- yorumlar ve karakterler --------------------------------------------------------------
        Arguments.of("blok yorum", "// Adım 1: Giriş yap", "/* Adım 1 */", "comment_form"),
        Arguments.of("javadoc", METOT, "/** Belge. */\n  " + METOT, "comment_form"),
        Arguments.of("yorumda unicode kaçışı", "// Adım 1: Giriş yap", "// Adım 1 \\u000a Thread.sleep(1);", "unicode_escape"),
        Arguments.of("literalde unicode kaçışı", "\"Demo123!\"", "\"Demo\\u0022\"", "unicode_escape"),
        Arguments.of("yorumda kontrol karakteri", "// Adım 1: Giriş yap", "// Adım 1\u0007", "forbidden_character"),
        Arguments.of("yön denetimi (Trojan Source)", "// Adım 1: Giriş yap", "// Adım 1 ‮", "forbidden_character"),
        Arguments.of("sıfır genişlik", "\"Demo123!\"", "\"Demo​123!\"", "forbidden_character"),
        Arguments.of("satır ayırıcı", "// Adım 1: Giriş yap", "// Adım 1   x", "forbidden_character"),
        Arguments.of("sözdizimi hatası", GIRIS, "girisEkrani().girisYap(\"bayi2\", \"Demo123!\"", "parse_error"));
  }

  @ParameterizedTest(name = "{0} → {3}")
  @MethodSource("ihlaller")
  void ihlalReddedilir(String ad, String eski, String yeni, String kod) {
    assertTrue(gecerli.contains(eski), "şablon parçası bulunamadı: " + eski);
    String metin = gecerli.replace(eski, yeni);
    List<UretilenTestKoruyucu.Ihlal> v = denetle(metin);
    assertTrue(v.stream().anyMatch(i -> i.kod().equals(kod)), ad + ": beklenen " + kod + ", bulunan " + v);
  }

  @Test
  void cliRaporuVeCikisKodlari() {
    ByteArrayOutputStream out = new ByteArrayOutputStream();
    ByteArrayOutputStream err = new ByteArrayOutputStream();
    int kod = Main.calistir(new String[] {"guard", "--root", KOK.toString(), "--kimlikler", DOSYA},
        new PrintStream(out, true, StandardCharsets.UTF_8), new PrintStream(err, true, StandardCharsets.UTF_8));
    String json = out.toString(StandardCharsets.UTF_8);
    assertEquals(0, kod, json + err);
    assertTrue(json.contains("\"ok\": true"));
    assertTrue(json.contains("\"violations\": []"));
    assertTrue(json.contains("\"tool\": \"java-araclar\""));

    out.reset();
    kod = Main.calistir(new String[] {"guard", "--root", KOK.toString(),
        "src/test/java/com/antreklabs/bayi/testler/ElleYazilmisTest.java"},
        new PrintStream(out, true, StandardCharsets.UTF_8), new PrintStream(err, true, StandardCharsets.UTF_8));
    assertEquals(1, kod);
    assertTrue(out.toString(StandardCharsets.UTF_8).contains("\"code\": \"loop\""));

    out.reset();
    kod = Main.calistir(new String[] {"guard", "--root", "yok/boyle/bir/dizin", DOSYA},
        new PrintStream(out, true, StandardCharsets.UTF_8), new PrintStream(err, true, StandardCharsets.UTF_8));
    assertEquals(2, kod);
    assertTrue(out.toString(StandardCharsets.UTF_8).contains("\"ok\": false"));

    kod = Main.calistir(new String[] {"guard", "--bilinmeyen"},
        new PrintStream(out, true, StandardCharsets.UTF_8), new PrintStream(err, true, StandardCharsets.UTF_8));
    assertEquals(2, kod);
  }

  @Test
  void kokDisiDosyaReddedilir() throws IOException {
    Map<String, Object> r = UretilenTestKoruyucu.denetle(KOK, List.of("../../../../pom.xml"), false);
    assertEquals(false, r.get("ok"));
    assertTrue(r.get("violations").toString().contains("file_location"));
  }

  @Test
  void kimlikSafligiDenetlenir() throws IOException {
    Map<String, Object> r = UretilenTestKoruyucu.denetle(Path.of("src/test/resources/e2e-app-hatali"), List.of(), true);
    assertEquals(false, r.get("ok"));
    String v = r.get("violations").toString();
    assertTrue(v.contains("forbidden_statement"), v);
    assertTrue(v.contains("non_literal_value"), v);
    assertTrue(v.contains("invalid_testid"), v);
    assertTrue(v.contains("duplicate_key"), v);
  }

  @Test
  void paketBilgisi() {
    String yol = UretilenTestKoruyucu.DIZIN + "package-info.java";
    String temiz = "/**\n * Üretilen testler.\n */\npackage com.antreklabs.bayi.uretilen;\n";
    assertEquals(List.of(), UretilenTestKoruyucu.dosyaDenetle(yol, temiz, tablo));
    for (String[] c : new String[][] {
        {temiz + "class X { static { System.exit(1); } }\n", "top_level_type"},
        {temiz.replace("package", "import java.io.File;\npackage"), "parse_error"},
        {temiz.replace("package com", "@Deprecated\npackage com"), "wrong_package"},
        {temiz.replace("uretilen;", "testler;"), "wrong_package"},
        {temiz.replace("Üretilen", "\\u002a/ x /*"), "unicode_escape"},
    }) {
      List<UretilenTestKoruyucu.Ihlal> v = UretilenTestKoruyucu.dosyaDenetle(yol, c[0], tablo);
      assertTrue(v.stream().anyMatch(i -> i.kod().equals(c[1])), c[1] + " beklenirken: " + v);
    }
    // Başka dizindeki package-info sıradan dosya gibi reddedilir.
    assertTrue(UretilenTestKoruyucu.dosyaDenetle("src/test/java/x/package-info.java", temiz, tablo).stream()
        .anyMatch(i -> i.kod().equals("file_location")));
  }

  /** Ş3'ün gerçek projesi (demo-app/e2e-app) varsa: tablo hatasız, altın üretilen test geçer. */
  @Test
  void gercekE2eApp() throws IOException {
    Path gercek = Path.of("../../demo-app/e2e-app");
    org.junit.jupiter.api.Assumptions.assumeTrue(java.nio.file.Files.isDirectory(gercek.resolve("src/test/java")));
    SembolCikarici.Tablo t = SembolCikarici.cikar(gercek, Kaynaklar.TEST_KAYNAK);
    assertEquals(List.of(), t.json().get("errors"));
    assertEquals(List.of("girisEkrani", "katalogEkrani", "onayEkrani", "sepetEkrani", "siparisEkrani"),
        t.json().get("fixtures"));
    List<String> uretilen = new java.util.ArrayList<>();
    try (Stream<Path> s = java.nio.file.Files.list(gercek.resolve(UretilenTestKoruyucu.DIZIN))) {
      s.filter(p -> p.toString().endsWith(".java")).sorted()
          .forEach(p -> uretilen.add(UretilenTestKoruyucu.DIZIN + p.getFileName()));
    }
    assertTrue(uretilen.contains(UretilenTestKoruyucu.DIZIN + "TPD1C3_0a1b2c3dTest.java"), uretilen.toString());
    Map<String, Object> r = UretilenTestKoruyucu.denetle(gercek, uretilen, true);
    assertEquals(true, r.get("ok"), r.toString());
  }

  @Test
  void dosyasizCagriNoop() throws IOException {
    Map<String, Object> r = UretilenTestKoruyucu.denetle(KOK, List.of(), false);
    assertEquals(true, r.get("ok"));
    assertEquals(true, r.get("noop"));
  }
}
