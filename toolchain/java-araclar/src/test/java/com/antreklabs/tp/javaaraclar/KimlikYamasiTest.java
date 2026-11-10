package com.antreklabs.tp.javaaraclar;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/** Kimlik yaması (yalnız literal değişir) ve repair modu farkı. */
class KimlikYamasiTest {
  static final Path KAYNAK = Path.of("src/test/resources/e2e-app");
  static final String KIMLIK = "src/test/java/com/antreklabs/bayi/ekranlar/Kimlikler.java";

  @TempDir Path gecici;
  Path kok;
  String orijinal;

  @BeforeEach
  void kopyala() throws IOException {
    kok = gecici.resolve("e2e-app");
    Path hedef = kok.resolve(KIMLIK);
    Files.createDirectories(hedef.getParent());
    orijinal = Files.readString(KAYNAK.resolve(KIMLIK), StandardCharsets.UTF_8);
    Files.writeString(hedef, orijinal, StandardCharsets.UTF_8);
  }

  void yaz(String metin) throws IOException {
    Files.writeString(kok.resolve(KIMLIK), metin, StandardCharsets.UTF_8);
  }

  @Test
  void yalnizcaLiteralDegisir() throws Exception {
    Map<String, Object> m = KimlikYamasi.yamala(kok, "login-submit", "login-submit-btn", null, "demo-app/e2e-app");
    String sonuc = (String) m.get("content");
    assertEquals(orijinal.replace("\"login-submit\"", "\"login-submit-btn\""), sonuc);
    assertEquals("Giris.GONDER", m.get("key"));
    assertEquals(14, m.get("line"));
    String fark = (String) m.get("diff");
    assertEquals(String.join("\n",
        "--- a/demo-app/e2e-app/" + KIMLIK,
        "+++ b/demo-app/e2e-app/" + KIMLIK,
        "@@ -13,3 +13,3 @@",
        "     /** Giriş yap butonu. */",
        "-    public static final String GONDER = \"login-submit\";",
        "+    public static final String GONDER = \"login-submit-btn\";",
        "     /** Hata mesajı. */",
        ""), fark);
    // Dosyaya yazmaz.
    assertEquals(orijinal, Files.readString(kok.resolve(KIMLIK), StandardCharsets.UTF_8));
    // Fark, repair modunda geçer ve değişikliği raporlar.
    Map<String, Object> r = KimlikYamasi.fark(orijinal, sonuc, KIMLIK);
    assertEquals(true, r.get("ok"), r.toString());
    assertEquals(List.of(Map.of("file", KIMLIK, "entry", "Giris.GONDER", "before", "login-submit", "after", "login-submit-btn")),
        r.get("testid_changes"));
  }

  @Test
  void anahtarlaSecim() throws Exception {
    yaz(orijinal.replace("\"cart-total\"", "\"login-error\""));
    KimlikYamasi.YamaHatasi e = assertThrows(KimlikYamasi.YamaHatasi.class,
        () -> KimlikYamasi.yamala(kok, "login-error", "login-err", null, null));
    assertTrue(e.getMessage().contains("birden çok"), e.getMessage());
    Map<String, Object> m = KimlikYamasi.yamala(kok, "login-error", "login-err", "Sepet.TOPLAM", null);
    assertEquals("Sepet.TOPLAM", m.get("key"));
    m = KimlikYamasi.yamala(kok, "login-error", "login-err", "HATA", null);
    assertEquals("Giris.HATA", m.get("key"));
  }

  @Test
  void retler() throws IOException {
    assertRet("önek", () -> KimlikYamasi.yamala(kok, "product-card-", "pc-", null, null));
    assertRet("bulunamadı", () -> KimlikYamasi.yamala(kok, "yok-boyle", "x", null, null));
    assertRet("aynı", () -> KimlikYamasi.yamala(kok, "login-error", "login-error", null, null));
    assertRet("geçersiz", () -> KimlikYamasi.yamala(kok, "login-error", "login error", null, null));
    assertRet("geçersiz", () -> KimlikYamasi.yamala(kok, "login-error", "a\"b", null, null));
    assertRet("başka bir kimliğin", () -> KimlikYamasi.yamala(kok, "login-error", "cart-total", null, null));
    assertRet("başka bir kimliğin", () -> KimlikYamasi.yamala(kok, "login-error", "product-card-x", null, null));
    yaz(orijinal.replace("\"login-error\"", "\"login\\055error\""));
    assertRet("kaçış", () -> KimlikYamasi.yamala(kok, "login-error", "login-err", null, null));
    yaz(orijinal.replace("private Kimlikler() {}", "private Kimlikler() {}\n  static { System.exit(1); }"));
    assertRet("saf veri değil", () -> KimlikYamasi.yamala(kok, "login-error", "login-err", null, null));
  }

  static void assertRet(String parca, org.junit.jupiter.api.function.Executable e) {
    KimlikYamasi.YamaHatasi h = assertThrows(KimlikYamasi.YamaHatasi.class, e);
    assertTrue(h.getMessage().contains(parca), parca + " beklenirken: " + h.getMessage());
  }

  @Test
  void bul() throws IOException {
    Map<String, Object> r = KimlikYamasi.bul(kok, "product-card-P-001");
    assertEquals("[{key=Katalog.URUN_KARTI_ONEK, testId=product-card-, prefix=true, intent=Ürün kartı (ürün kodu eklenir)., file="
        + KIMLIK + ", line=22}]", r.get("matches").toString());
    assertEquals(1, ((List<?>) KimlikYamasi.bul(kok, "cart-total").get("matches")).size());
  }

  @Test
  void farkLiteralDisiDegisikligiReddeder() {
    for (String[] c : new String[][] {
        {"/** Hata mesajı. */", "/** Hata iletisi. */"},            // yorum (niyet) değişti
        {"public static final String HATA", "public static final String HATA2"}, // anahtar adı
        {"    public static final String HATA = \"login-error\";\n", ""},          // giriş silindi
        {"  private Kimlikler() {}", "  private Kimlikler() {}\n  static { }"},    // kod eklendi
        {"\"login-error\";", "\"login-error\" ;"},                                // biçim
    }) {
      Map<String, Object> r = KimlikYamasi.fark(orijinal, orijinal.replace(c[0], c[1]), KIMLIK);
      assertEquals(false, r.get("ok"), c[1] + " → " + r);
    }
  }

  @Test
  void farkOnekVeUnicodeKacisi() {
    Map<String, Object> r = KimlikYamasi.fark(orijinal, orijinal.replace("\"product-card-\"", "\"pc-\""), KIMLIK);
    assertTrue(r.get("violations").toString().contains("prefix_changed"), r.toString());
    r = KimlikYamasi.fark(orijinal, orijinal.replace("/** Hata mesajı. */", "/** Hata \\u002a/ static {} /* */"), KIMLIK);
    assertTrue(r.get("violations").toString().contains("unicode_escape"), r.toString());
    r = KimlikYamasi.fark(orijinal, orijinal, KIMLIK);
    assertEquals(true, r.get("ok"));
    assertEquals(true, r.get("noop"));
  }

  @Test
  void cliYamaVeFark(@TempDir Path d) throws IOException {
    java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
    java.io.PrintStream o = new java.io.PrintStream(out, true, StandardCharsets.UTF_8);
    java.io.PrintStream e = new java.io.PrintStream(new java.io.ByteArrayOutputStream(), true, StandardCharsets.UTF_8);
    assertEquals(0, Main.calistir(new String[] {"locators", "patch", "--root", kok.toString(), "--old", "login-error", "--new", "login-err"}, o, e));
    assertTrue(out.toString(StandardCharsets.UTF_8).startsWith("{\"ok\":true,"));
    out.reset();
    assertEquals(1, Main.calistir(new String[] {"locators", "patch", "--root", kok.toString(), "--old", "product-card-", "--new", "x"}, o, e));
    assertTrue(out.toString(StandardCharsets.UTF_8).startsWith("{\"ok\":false,\"error\":"));
    Path a = d.resolve("a.java");
    Path b = d.resolve("b.java");
    Files.writeString(a, orijinal, StandardCharsets.UTF_8);
    Files.writeString(b, orijinal.replace("\"cart-total\"", "\"cart-sum\""), StandardCharsets.UTF_8);
    assertEquals(0, Main.calistir(new String[] {"locators", "diff", "--base", a.toString(), "--head", b.toString(), "--file", KIMLIK}, o, e));
    Files.writeString(b, orijinal.replace("Sepet toplamı", "Toplam"), StandardCharsets.UTF_8);
    assertEquals(1, Main.calistir(new String[] {"locators", "diff", "--base", a.toString(), "--head", b.toString()}, o, e));
    assertEquals(2, Main.calistir(new String[] {"locators", "diff", "--base", a.toString()}, o, e));
    assertEquals(0, Main.calistir(new String[] {"locators", "find", "--root", kok.toString(), "--test-id", "cart-total"}, o, e));
  }
}
