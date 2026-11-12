package com.antreklabs.tp.javaaraclar;

import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.ImportDeclaration;
import com.github.javaparser.ast.Modifier;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.BodyDeclaration;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.FieldDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.comments.Comment;
import com.github.javaparser.ast.comments.LineComment;
import com.github.javaparser.ast.expr.AnnotationExpr;
import com.github.javaparser.ast.expr.ArrayAccessExpr;
import com.github.javaparser.ast.expr.ArrayCreationExpr;
import com.github.javaparser.ast.expr.ArrayInitializerExpr;
import com.github.javaparser.ast.expr.AssignExpr;
import com.github.javaparser.ast.expr.BooleanLiteralExpr;
import com.github.javaparser.ast.expr.ConditionalExpr;
import com.github.javaparser.ast.expr.DoubleLiteralExpr;
import com.github.javaparser.ast.expr.Expression;
import com.github.javaparser.ast.expr.FieldAccessExpr;
import com.github.javaparser.ast.expr.IntegerLiteralExpr;
import com.github.javaparser.ast.expr.LambdaExpr;
import com.github.javaparser.ast.expr.LongLiteralExpr;
import com.github.javaparser.ast.expr.MemberValuePair;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.expr.MethodReferenceExpr;
import com.github.javaparser.ast.expr.NameExpr;
import com.github.javaparser.ast.expr.NormalAnnotationExpr;
import com.github.javaparser.ast.expr.ObjectCreationExpr;
import com.github.javaparser.ast.expr.SingleMemberAnnotationExpr;
import com.github.javaparser.ast.expr.StringLiteralExpr;
import com.github.javaparser.ast.expr.SuperExpr;
import com.github.javaparser.ast.expr.SwitchExpr;
import com.github.javaparser.ast.expr.TextBlockLiteralExpr;
import com.github.javaparser.ast.expr.ThisExpr;
import com.github.javaparser.ast.expr.UnaryExpr;
import com.github.javaparser.ast.expr.VariableDeclarationExpr;
import com.github.javaparser.ast.stmt.DoStmt;
import com.github.javaparser.ast.stmt.ExpressionStmt;
import com.github.javaparser.ast.stmt.ForEachStmt;
import com.github.javaparser.ast.stmt.ForStmt;
import com.github.javaparser.ast.stmt.IfStmt;
import com.github.javaparser.ast.stmt.Statement;
import com.github.javaparser.ast.stmt.SwitchStmt;
import com.github.javaparser.ast.stmt.WhileStmt;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import java.io.IOException;
import java.math.BigInteger;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Üretilen test AST koruması (009 plan §2.4, §2.8) — İZİN LİSTESİ.
 *
 * <p>Dosyanın taşıyabileceği tek biçim:
 *
 * <pre>
 * // AI-generated — …                       (yalnızca // satır yorumları)
 * package com.antreklabs.bayi.uretilen;
 * import com.antreklabs.bayi.altyapi.Bayi;        (yalnız bu üç import)
 * import com.antreklabs.bayi.altyapi.TestTabani;
 * import org.testng.annotations.Test;
 * &#64;Bayi("bayi2")                                 (en çok bir kez, tek string literal)
 * public class &lt;Ad&gt;Test extends TestTabani {
 *   &#64;Test(groups = {"uretilen", …}, description = "…")
 *   public void senaryo() {
 *     &lt;erişimci&gt;().&lt;metot&gt;(&lt;literal&gt;, …);       (yalnız bu deyim)
 *   }
 * }
 * </pre>
 *
 * Erişimci ve metot sembol tablosunda olmalı; argüman sayısı ve türü imzaya uymalı. Başka her şey
 * bir ihlaldir. Çıktı TS ast-guard raporuyla aynı biçimdedir ({@code violations[].code/file/line/
 * message}, {@code ok}, {@code summary}); çıkış kodu 0 geçti · 1 ihlal · 2 hata.
 */
public final class UretilenTestKoruyucu {
  public static final String TEMEL_PAKET = "com.antreklabs.bayi";
  public static final String PAKET = TEMEL_PAKET + ".uretilen";
  public static final String DIZIN = Kaynaklar.TEST_KAYNAK + "/" + PAKET.replace('.', '/') + "/";
  public static final Set<String> IZINLI_IMPORTLAR = Set.of(
      TEMEL_PAKET + ".altyapi.Bayi", TEMEL_PAKET + ".altyapi.TestTabani", "org.testng.annotations.Test");
  public static final Set<String> ZORUNLU_IMPORTLAR = Set.of(
      TEMEL_PAKET + ".altyapi.TestTabani", "org.testng.annotations.Test");
  public static final String BASLIK = "// AI-generated";
  public static final String PAKET_BILGISI = "package-info.java";
  public static final String URETILEN_GRUBU = "uretilen";
  static final Pattern DOSYA_ADI = Pattern.compile("^[A-Za-z][A-Za-z0-9]*C[0-9]+_[0-9a-f]{8}Test\\.java$");
  static final Pattern BAYI = Pattern.compile("^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$");
  static final Pattern GRUP = Pattern.compile("^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$");
  /** Gizli test verisi ortam değişkeni adı (specs/013 K19). */
  static final Pattern GIZLI_VERI = Pattern.compile("^TP_TESTVERI_[A-Z0-9_]{1,64}$");
  static final Pattern INT = Pattern.compile("^(0|[1-9][0-9]*)$");
  static final Pattern LONG = Pattern.compile("^(0|[1-9][0-9]*)[lL]$");
  static final Pattern DOUBLE = Pattern.compile("^[0-9]+(\\.[0-9]+([eE][+-]?[0-9]+)?[dD]?|[eE][+-]?[0-9]+[dD]?|[dD])$");
  /**
   * Ham sürücü adları ({@code raw_driver}): Appium/Selenium sürücüsü (uygulama projesi) ve Playwright
   * for Java tutamaçları (web projesi, 011 §2.6: {@code page()}, {@code browser()}, {@code context()},
   * {@code playwright()} ve Türkçe karşılıkları). Üretilen test bunlara erişemez; yalnızca ekran
   * erişimcilerini çağırır.
   */
  static final Set<String> SURUCU = Set.of(
      "driver", "surucu", "getDriver", "webDriver", "appiumDriver",
      "page", "getPage", "sayfa", "browser", "getBrowser", "tarayici", "context", "browserContext",
      "getContext", "baglam", "playwright", "getPlaywright");

  /** İhlal. */
  public record Ihlal(String kod, String dosya, int satir, String mesaj) {
    Map<String, Object> json() {
      Map<String, Object> m = new LinkedHashMap<>();
      m.put("code", kod);
      m.put("file", dosya);
      if (satir > 0) m.put("line", satir);
      m.put("message", mesaj);
      return m;
    }
  }

  private UretilenTestKoruyucu() {}

  /**
   * {@code dosyalar}: e2e-app köküne göre (ya da kök içinde mutlak) üretilen test yolları.
   * {@code kimlikler}: {@code ekranlar/Kimlikler.java} saflığını da denetle (TS pr modunun
   * {@code locators.ts} saf veri denetiminin karşılığı).
   */
  public static Map<String, Object> denetle(Path kok, List<String> dosyalar, boolean kimlikler) throws IOException {
    Path root = kok.toAbsolutePath().normalize();
    SembolCikarici.Tablo tablo = SembolCikarici.cikar(root, Kaynaklar.TEST_KAYNAK);
    List<Ihlal> ihlaller = new ArrayList<>();
    List<String> denetlenen = new ArrayList<>();
    for (String d : dosyalar) {
      Path p = Path.of(d);
      Path abs = (p.isAbsolute() ? p : root.resolve(p)).normalize();
      if (!abs.startsWith(root)) {
        ihlaller.add(new Ihlal("file_location", d, 0, "dosya e2e-app kökü dışında"));
        continue;
      }
      String gorel = Kaynaklar.gorel(root, abs);
      denetlenen.add(gorel);
      if (Files.isSymbolicLink(abs) || !Files.isRegularFile(abs, LinkOption.NOFOLLOW_LINKS)) {
        ihlaller.add(new Ihlal("file_location", gorel, 0, "dosya yok ya da düzenli dosya değil"));
        continue;
      }
      String metin;
      try {
        metin = Kaynaklar.oku(abs);
      } catch (IOException e) {
        ihlaller.add(new Ihlal("parse_error", gorel, 0, "okunamadı: " + e.getMessage()));
        continue;
      }
      ihlaller.addAll(dosyaDenetle(gorel, metin, tablo));
    }
    List<String> kimlikDosyalari = new ArrayList<>();
    if (kimlikler) {
      for (Map.Entry<String, KimlikDosyasi.Sonuc> e : tablo.kimlikDosyalari().entrySet()) {
        kimlikDosyalari.add(e.getKey());
        Path abs = root.resolve(e.getKey());
        KimlikDosyasi.Sonuc s = KimlikDosyasi.coz(Kaynaklar.oku(abs));
        for (KimlikDosyasi.Hata h : s.hatalar()) {
          ihlaller.add(new Ihlal(h.kod(), e.getKey(), h.satir(), "Kimlikler saf veri değil: " + h.mesaj()));
        }
      }
      if (tablo.kimlikDosyalari().isEmpty()) {
        ihlaller.add(new Ihlal("locator_file_missing", Kaynaklar.TEST_KAYNAK, 0, "ekranlar/Kimlikler.java bulunamadı"));
      }
    }
    Map<String, Object> rapor = new LinkedHashMap<>();
    rapor.put("tool", "java-araclar");
    rapor.put("schema_version", 1);
    rapor.put("mode", "generated");
    rapor.put("ok", ihlaller.isEmpty());
    rapor.put("noop", denetlenen.isEmpty() && !kimlikler && ihlaller.isEmpty());
    rapor.put("root", ".");
    rapor.put("files", denetlenen);
    rapor.put("locator_files", kimlikDosyalari);
    rapor.put("changed_files", List.of());
    rapor.put("testid_changes", List.of());
    rapor.put("added_entries", List.of());
    rapor.put("removed_entries", List.of());
    List<Map<String, Object>> v = new ArrayList<>();
    for (Ihlal i : ihlaller) v.add(i.json());
    rapor.put("violations", v);
    rapor.put("summary", ihlaller.isEmpty()
        ? "Java üretilen test koruması geçti · dosya: " + denetlenen.size()
        : "Java üretilen test koruması başarısız · dosya: " + denetlenen.size() + " · ihlal: " + ihlaller.size());
    return rapor;
  }

  /** Tek dosyanın denetimi (sembol tablosu verilir). */
  public static List<Ihlal> dosyaDenetle(String gorel, String metin, SembolCikarici.Tablo tablo) {
    Denetim d = new Denetim(gorel, tablo);
    d.calis(metin);
    return d.ihlaller;
  }

  private static final class Denetim {
    final String dosya;
    final SembolCikarici.Tablo tablo;
    final List<Ihlal> ihlaller = new ArrayList<>();

    Denetim(String dosya, SembolCikarici.Tablo tablo) {
      this.dosya = dosya;
      this.tablo = tablo;
    }

    void ekle(String kod, Node n, String mesaj) {
      ihlaller.add(new Ihlal(kod, dosya, n == null ? 0 : Kaynaklar.satir(n), mesaj));
    }

    void ekle(String kod, int satir, String mesaj) {
      ihlaller.add(new Ihlal(kod, dosya, satir, mesaj));
    }

    void calis(String metin) {
      String ad = dosya.substring(dosya.lastIndexOf('/') + 1);
      if (ad.equals(PAKET_BILGISI) && dosya.equals(DIZIN + PAKET_BILGISI)) {
        paketBilgisi(metin);
        return;
      }
      if (!dosya.startsWith(DIZIN) || dosya.substring(DIZIN.length()).contains("/") || !DOSYA_ADI.matcher(ad).matches()) {
        // 009 §2.4: dosya adı platform adını da taşır (`TPD1AndroidC3_0a1b2c3dTest.java`);
        // DOSYA_ADI kalıbı ikisini de kabul eder, mesaj üretilen biçimi gösterir.
        ekle("file_location", 0, "üretilen test " + DIZIN
            + "<Story><Platform>C<sıra>_<uuid8>Test.java olmalı (ör. TPD1AndroidC3_0a1b2c3dTest.java)");
      }
      for (KarakterDenetimi.Bulgu b : KarakterDenetimi.denetle(metin)) ekle(b.kod(), b.satir(), b.mesaj());
      if (!metin.startsWith(BASLIK)) {
        ekle("missing_header", 1, "dosya '" + BASLIK + " — …' başlık yorumuyla başlamalı");
      }
      Kaynaklar.Ayristirma a = Kaynaklar.ayristir(metin, dosya);
      if (!a.temiz()) {
        for (Map<String, Object> h : a.hatalar()) {
          Object s = h.get("line");
          ekle("parse_error", s instanceof Integer i ? i : 0, (String) h.get("message"));
        }
        return;
      }
      birim(a.birim(), ad.endsWith(".java") ? ad.substring(0, ad.length() - 5) : ad);
    }

    /**
     * {@code uretilen/package-info.java}: yalnızca belge yorumu + {@code package} bildirimi (sınıf,
     * import, paket notasyonu yok). Kod taşıyamaz; yine de karakter denetimi uygulanır.
     */
    void paketBilgisi(String metin) {
      for (KarakterDenetimi.Bulgu b : KarakterDenetimi.denetle(metin)) ekle(b.kod(), b.satir(), b.mesaj());
      Kaynaklar.Ayristirma a = Kaynaklar.ayristir(metin, dosya);
      if (!a.temiz()) {
        for (Map<String, Object> h : a.hatalar()) {
          Object s = h.get("line");
          ekle("parse_error", s instanceof Integer i ? i : 0, (String) h.get("message"));
        }
        return;
      }
      CompilationUnit cu = a.birim();
      cu.getModule().ifPresent(m -> ekle("forbidden_statement", m, "modül bildirimi yasak"));
      if (cu.getPackageDeclaration().isEmpty()
          || !cu.getPackageDeclaration().get().getNameAsString().equals(PAKET)
          || !cu.getPackageDeclaration().get().getAnnotations().isEmpty()) {
        ekle("wrong_package", 1, PAKET_BILGISI + " yalnızca 'package " + PAKET + ";' taşır (notasyonsuz)");
      }
      cu.getImports().forEach(i -> ekle("forbidden_import", i, PAKET_BILGISI + " içinde import yasak"));
      cu.getTypes().forEach(t -> ekle("top_level_type", t, PAKET_BILGISI + " içinde tür bildirimi yasak"));
    }

    void birim(CompilationUnit cu, String beklenenSinif) {
      cu.getModule().ifPresent(m -> ekle("forbidden_statement", m, "modül bildirimi yasak"));
      for (Comment c : cu.getAllComments()) {
        if (!(c instanceof LineComment)) ekle("comment_form", c, "yalnızca // satır yorumu kullanılabilir");
      }
      if (cu.getPackageDeclaration().isEmpty()
          || !cu.getPackageDeclaration().get().getNameAsString().equals(PAKET)
          || !cu.getPackageDeclaration().get().getAnnotations().isEmpty()) {
        ekle("wrong_package", cu.getPackageDeclaration().map(Kaynaklar::satir).orElse(1), "paket '" + PAKET + "' olmalı");
      }
      Set<String> gorulen = new LinkedHashSet<>();
      for (ImportDeclaration imp : cu.getImports()) {
        String ad = imp.getNameAsString();
        if (imp.isStatic() || imp.isAsterisk() || !IZINLI_IMPORTLAR.contains(ad)) {
          ekle("forbidden_import", imp, "izinsiz import: " + (imp.isStatic() ? "static " : "") + ad + (imp.isAsterisk() ? ".*" : "")
              + " (yalnız " + String.join(", ", IZINLI_IMPORTLAR.stream().sorted().toList()) + ")");
        } else if (!gorulen.add(ad)) {
          ekle("forbidden_import", imp, "aynı import iki kez: " + ad);
        }
      }
      for (String z : ZORUNLU_IMPORTLAR.stream().sorted().toList()) {
        if (!gorulen.contains(z)) ekle("missing_import", 1, "zorunlu import yok: " + z);
      }
      if (cu.getTypes().size() != 1) {
        ekle("top_level_type", cu.getTypes().isEmpty() ? null : cu.getType(1 % cu.getTypes().size()),
            "dosyada tam olarak bir üst düzey sınıf olmalı (" + cu.getTypes().size() + " bulundu)");
      }
      if (cu.getTypes().isEmpty()) return;
      TypeDeclaration<?> t = cu.getType(0);
      if (!(t instanceof ClassOrInterfaceDeclaration c) || c.isInterface()) {
        ekle("top_level_type", t, "üst düzey tür bir sınıf olmalı (arayüz/enum/record/notasyon yasak)");
        return;
      }
      sinif(c, gorulen.contains(TEMEL_PAKET + ".altyapi.Bayi"));
      if (!c.getNameAsString().equals(beklenenSinif)) {
        ekle("class_shape", c, "sınıf adı dosya adıyla aynı olmalı (" + beklenenSinif + ")");
      }
    }

    void sinif(ClassOrInterfaceDeclaration c, boolean bayiImport) {
      if (!KimlikDosyasi.anahtarlar(c.getModifiers()).equals(EnumSet.of(Modifier.Keyword.PUBLIC))) {
        ekle("class_shape", c, "sınıf yalnızca 'public' niteleyicisini taşır");
      }
      boolean tabanUygun = c.getExtendedTypes().size() == 1 && duzAd(c.getExtendedTypes().get(0), SembolCikarici.TEST_TABANI);
      if (!tabanUygun) ekle("class_shape", c, "sınıf yalnızca 'extends TestTabani' ile türemeli");
      if (!c.getImplementedTypes().isEmpty() || !c.getPermittedTypes().isEmpty() || !c.getTypeParameters().isEmpty()) {
        ekle("class_shape", c, "implements/permits/tür parametresi yasak");
      }
      int bayi = 0;
      for (AnnotationExpr an : c.getAnnotations()) {
        if (an instanceof SingleMemberAnnotationExpr s && s.getNameAsString().equals("Bayi")) {
          bayi++;
          if (bayi > 1) {
            ekle("annotation", an, "@Bayi en çok bir kez kullanılabilir");
          } else if (!(s.getMemberValue() instanceof StringLiteralExpr lit) || s.getMemberValue() instanceof TextBlockLiteralExpr
              || !BAYI.matcher(lit.asString()).matches()) {
            ekle(kodu(s.getMemberValue(), "annotation"), an, "@Bayi tek string literal (bayi kullanıcı adı) alır");
          } else if (!bayiImport) {
            ekle("missing_import", an, "@Bayi için import " + TEMEL_PAKET + ".altyapi.Bayi gerekli");
          }
        } else {
          ekle("annotation", an, "sınıfta yalnızca @Bayi(\"…\") notasyonu kullanılabilir (" + an.getNameAsString() + ")");
        }
      }
      List<MethodDeclaration> metotlar = new ArrayList<>();
      for (BodyDeclaration<?> u : c.getMembers()) {
        if (u instanceof MethodDeclaration m) {
          metotlar.add(m);
        } else if (u instanceof FieldDeclaration) {
          ekle("field", u, "üretilen testte alan (field) yasak");
        } else {
          ekle("forbidden_member", u, "üretilen testte yalnızca tek @Test metodu bulunur (kurucu, blok, iç sınıf yasak)");
        }
      }
      if (metotlar.size() != 1) {
        ekle("test_method_count", c, "tam olarak bir @Test metodu olmalı (" + metotlar.size() + " bulundu)");
      }
      for (MethodDeclaration m : metotlar) metot(m);
    }

    void metot(MethodDeclaration m) {
      if (!KimlikDosyasi.anahtarlar(m.getModifiers()).equals(EnumSet.of(Modifier.Keyword.PUBLIC))) {
        ekle("test_method", m, "test metodu yalnızca 'public' niteleyicisini taşır");
      }
      if (!m.getType().isVoidType()) ekle("test_method", m, "test metodu void dönmeli");
      if (!m.getParameters().isEmpty()) ekle("test_method", m, "test metodu parametresiz olmalı");
      if (!m.getThrownExceptions().isEmpty()) ekle("test_method", m, "test metodunda throws yasak");
      if (!m.getTypeParameters().isEmpty()) ekle("test_method", m, "test metodunda tür parametresi yasak");
      int test = 0;
      for (AnnotationExpr an : m.getAnnotations()) {
        if (an.getNameAsString().equals("Test")) {
          test++;
          if (test > 1) {
            ekle("test_annotation", an, "@Test bir kez kullanılabilir");
          } else {
            testNotasyonu(an);
          }
        } else {
          ekle("annotation", an, "test metodunda yalnızca @Test notasyonu kullanılabilir (" + an.getNameAsString() + ")");
        }
      }
      if (test == 0) ekle("test_annotation", m, "test metodu @Test(groups = {\"uretilen\", …}) taşımalı");
      if (m.getBody().isEmpty()) {
        ekle("test_method", m, "test metodunun gövdesi olmalı");
        return;
      }
      for (Statement s : m.getBody().get().getStatements()) deyim(s);
    }

    void testNotasyonu(AnnotationExpr an) {
      if (!(an instanceof NormalAnnotationExpr n)) {
        ekle("test_annotation", an, "@Test(groups = {\"uretilen\", …}[, description = \"…\"]) biçiminde olmalı");
        return;
      }
      Set<String> adlar = new LinkedHashSet<>();
      boolean gruplar = false;
      for (MemberValuePair p : n.getPairs()) {
        String ad = p.getNameAsString();
        if (!adlar.add(ad)) {
          ekle("test_annotation", p, "@Test özniteliği iki kez: " + ad);
          continue;
        }
        if (ad.equals("groups")) {
          gruplar = true;
          if (!(p.getValue() instanceof ArrayInitializerExpr dizi) || dizi.getValues().isEmpty()) {
            ekle("test_annotation", p, "groups bir string literal dizisi olmalı: {\"uretilen\", …}");
            continue;
          }
          for (int i = 0; i < dizi.getValues().size(); i++) {
            Expression e = dizi.getValues().get(i);
            if (!(e instanceof StringLiteralExpr s) || e instanceof TextBlockLiteralExpr || !GRUP.matcher(s.asString()).matches()) {
              ekle(kodu(e, "test_annotation"), e, "groups öğeleri yalnızca string literal (etiket) olabilir");
            } else if (i == 0 && !s.asString().equals(URETILEN_GRUBU)) {
              ekle("test_annotation", e, "groups ilk öğesi \"" + URETILEN_GRUBU + "\" olmalı");
            }
          }
        } else if (ad.equals("description")) {
          if (!(p.getValue() instanceof StringLiteralExpr) || p.getValue() instanceof TextBlockLiteralExpr) {
            ekle(kodu(p.getValue(), "test_annotation"), p, "description tek string literal olmalı");
          }
        } else {
          ekle("test_annotation", p, "@Test özniteliği yasak: " + ad + " (yalnız groups, description)");
        }
      }
      if (!gruplar) ekle("test_annotation", an, "@Test groups = {\"uretilen\", …} taşımalı");
    }

    void deyim(Statement s) {
      if (!(s instanceof ExpressionStmt es) || !(es.getExpression() instanceof MethodCallExpr cagri)) {
        siniflandir(s, "forbidden_statement", "gövdede yalnızca <erişimci>().<metot>(<literal>…); deyimleri bulunur");
        return;
      }
      Optional<Expression> kapsam = cagri.getScope();
      if (kapsam.isEmpty()
          || !(kapsam.get() instanceof MethodCallExpr erisim)
          || erisim.getScope().isPresent()
          || !erisim.getArguments().isEmpty()
          || erisim.getTypeArguments().isPresent()
          || cagri.getTypeArguments().isPresent()) {
        siniflandir(s, "call_shape", "çağrı <erişimci>().<metot>(<literal>…) biçiminde olmalı");
        return;
      }
      List<String> turler = new ArrayList<>();
      boolean argOk = true;
      for (Expression arg : cagri.getArguments()) {
        String t = gizliVeri(arg) ? "String" : literalTuru(arg);
        if (t == null) {
          argOk = false;
          siniflandir(arg, "non_literal_argument",
              "argüman yalnızca string/int/long/double/boolean literal olabilir (negatif sayı için tekli eksi)");
        }
        turler.add(t);
      }
      sembol(cagri, erisim.getNameAsString(), cagri.getNameAsString(), argOk ? turler : null);
    }

    void sembol(MethodCallExpr cagri, String erisimci, String metot, List<String> argTurleri) {
      if (SURUCU.contains(erisimci)) {
        ekle("raw_driver", cagri, "ham sürücüye erişim yasak (" + erisimci + "()); yalnızca ekran erişimcileri");
        return;
      }
      String sinif = tablo.erisimciler().get(erisimci);
      if (sinif == null && !tablo.testTabaniVar()) {
        for (String s : tablo.metotlar().keySet()) {
          if (Kaynaklar.kucukDeve(s).equals(erisimci)) sinif = s;
        }
      }
      if (sinif == null) {
        ekle("unknown_accessor", cagri, erisimci + "() TestTabani'nda bir ekran erişimcisi değil");
        return;
      }
      List<SembolCikarici.Metot> adaylar = new ArrayList<>();
      for (SembolCikarici.Metot m : tablo.metotlar().getOrDefault(sinif, List.of())) {
        if (m.ad().equals(metot)) adaylar.add(m);
      }
      if (adaylar.isEmpty()) {
        ekle("unknown_method", cagri, sinif + "." + metot + " ekran nesnesinde yok (public, statik olmayan metot)");
        return;
      }
      if (adaylar.size() > 1) {
        ekle("unknown_method", cagri, sinif + "." + metot + " aşırı yüklenmiş (overload); üretilen test kullanamaz");
        return;
      }
      SembolCikarici.Metot m = adaylar.get(0);
      if (!m.donus().equals("void")) {
        ekle("unknown_method", cagri, sinif + "." + metot + " void dönmüyor (" + m.donus() + ")");
      }
      if (m.parametreTurleri().size() != cagri.getArguments().size()) {
        ekle("arg_count", cagri, sinif + "." + metot + " " + m.parametreTurleri().size() + " argüman bekler, "
            + cagri.getArguments().size() + " verildi");
        return;
      }
      if (argTurleri == null) return; // literal olmayan argüman zaten bildirildi
      for (int i = 0; i < argTurleri.size(); i++) {
        String p = m.parametreTurleri().get(i);
        String a = argTurleri.get(i);
        if (!SembolCikarici.PARAMETRE_TURLERI.contains(p)) {
          ekle("arg_type", cagri.getArgument(i), sinif + "." + metot + " parametre " + (i + 1) + " türü desteklenmiyor: " + p);
        } else if (!uyumlu(p, a)) {
          ekle("arg_type", cagri.getArgument(i), sinif + "." + metot + " parametre " + (i + 1) + " (" + p
              + ") için tür uyumsuz literal (" + a + "): " + Kaynaklar.tekSatir(cagri.getArgument(i).toString(), 80));
        }
      }
    }

    /** Ad kapsamsız, tür argümansız düz ad mı ({@code TestTabani}). */
    static boolean duzAd(ClassOrInterfaceType t, String ad) {
      return t.getNameAsString().equals(ad) && t.getScope().isEmpty() && t.getTypeArguments().isEmpty()
          && t.getAnnotations().isEmpty();
    }

    /**
     * Gizli test verisi (specs/013 K19): yalnızca ekran çağrısının doğrudan argümanı olarak
     * {@code System.getenv("TP_TESTVERI_…")} — kapsam niteliksiz düz {@code System}, tür argümanı yok,
     * tek argüman metin bloğu olmayan string literal. Türü String sayılır; başka her biçim reddedilir.
     */
    static boolean gizliVeri(Expression e) {
      return e instanceof MethodCallExpr m
          && m.getNameAsString().equals("getenv")
          && m.getTypeArguments().isEmpty()
          && m.getScope().filter(k -> k instanceof NameExpr ne && ne.getNameAsString().equals("System")).isPresent()
          && m.getArguments().size() == 1
          && m.getArgument(0) instanceof StringLiteralExpr s // metin bloğu ayrı türdür (TextBlockLiteralExpr)
          && GIZLI_VERI.matcher(s.asString()).matches();
    }

    /** İzinli literal ise Java türü (String/int/long/double/boolean), değilse null. */
    static String literalTuru(Expression e) {
      if (e instanceof TextBlockLiteralExpr) return null;
      if (e instanceof StringLiteralExpr) return "String";
      if (e instanceof BooleanLiteralExpr) return "boolean";
      boolean eksi = false;
      if (e instanceof UnaryExpr u) {
        if (u.getOperator() != UnaryExpr.Operator.MINUS) return null;
        e = u.getExpression();
        eksi = true;
        if (!(e instanceof IntegerLiteralExpr || e instanceof LongLiteralExpr || e instanceof DoubleLiteralExpr)) return null;
      }
      if (e instanceof IntegerLiteralExpr i) {
        String v = i.getValue();
        if (!INT.matcher(v).matches()) return null;
        BigInteger b = new BigInteger(v);
        BigInteger sinir = BigInteger.valueOf(Integer.MAX_VALUE).add(eksi ? BigInteger.ONE : BigInteger.ZERO);
        return b.compareTo(sinir) <= 0 ? "int" : null;
      }
      if (e instanceof LongLiteralExpr l) {
        String v = l.getValue();
        if (!LONG.matcher(v).matches()) return null;
        BigInteger b = new BigInteger(v.substring(0, v.length() - 1));
        BigInteger sinir = BigInteger.valueOf(Long.MAX_VALUE).add(eksi ? BigInteger.ONE : BigInteger.ZERO);
        return b.compareTo(sinir) <= 0 ? "long" : null;
      }
      if (e instanceof DoubleLiteralExpr d) {
        String v = d.getValue();
        if (!DOUBLE.matcher(v).matches()) return null;
        double x = Double.parseDouble(v.replaceAll("[dD]$", ""));
        return Double.isFinite(x) ? "double" : null;
      }
      return null;
    }

    /** Java yöntem çağrısı dönüşümü: genişletme (int → long → double) izinli. */
    static boolean uyumlu(String param, String arg) {
      return switch (param) {
        case "String" -> arg.equals("String");
        case "boolean" -> arg.equals("boolean");
        case "int" -> arg.equals("int");
        case "long" -> arg.equals("int") || arg.equals("long");
        case "double" -> arg.equals("int") || arg.equals("long") || arg.equals("double");
        default -> false;
      };
    }

    /** Düğümdeki ilk dikkat çekici yasak yapı için özel kodla ihlal ekler; yoksa varsayılan kod. */
    void siniflandir(Node n, String varsayilanKod, String varsayilanMesaj) {
      Node bulunan = ilkYasak(n);
      if (bulunan == null) {
        ekle(varsayilanKod, n, varsayilanMesaj);
      } else {
        ekle(kodu(bulunan, varsayilanKod), bulunan, mesaj(bulunan, varsayilanMesaj));
      }
    }

    static String kodu(Node n, String varsayilan) {
      Node b = ilkYasak(n);
      if (b == null) return varsayilan;
      return yasakKodu(b);
    }

    static Node ilkYasak(Node n) {
      if (yasakKodu(n) != null) return n;
      for (Node c : n.getChildNodes()) {
        Node b = ilkYasak(c);
        if (b != null) return b;
      }
      return null;
    }

    static String yasakKodu(Node n) {
      if (n instanceof IfStmt || n instanceof SwitchStmt || n instanceof SwitchExpr || n instanceof ConditionalExpr) return "branch";
      if (n instanceof ForStmt || n instanceof ForEachStmt || n instanceof WhileStmt || n instanceof DoStmt) return "loop";
      if (n instanceof LambdaExpr || n instanceof MethodReferenceExpr) return "lambda";
      if (n instanceof ObjectCreationExpr) return "new";
      if (n instanceof ArrayCreationExpr || n instanceof ArrayInitializerExpr || n instanceof ArrayAccessExpr) return "array";
      if (n instanceof TextBlockLiteralExpr) return "text_block";
      if (n instanceof ThisExpr || n instanceof SuperExpr) return "this_super";
      if (n instanceof VariableDeclarationExpr) return "local_variable";
      if (n instanceof AssignExpr) return "assignment";
      if (n instanceof MethodCallExpr m) {
        if (m.getNameAsString().equals("sleep")
            && m.getScope().filter(s -> s.toString().equals("Thread") || s.toString().endsWith(".Thread")).isPresent()) {
          return "thread_sleep";
        }
        if (SURUCU.contains(m.getNameAsString()) && m.getScope().isEmpty()) return "raw_driver";
        if (m.getScope().filter(s -> s instanceof NameExpr || s instanceof FieldAccessExpr).isPresent()) {
          String kapsam = m.getScope().get().toString();
          return SURUCU.contains(kapsam) || kapsam.endsWith(".driver") ? "raw_driver" : "static_call";
        }
        return null;
      }
      if (n instanceof NameExpr ne) return SURUCU.contains(ne.getNameAsString()) ? "raw_driver" : "field_access";
      if (n instanceof FieldAccessExpr) return "field_access";
      if (n instanceof Statement && !(n instanceof ExpressionStmt) && !(n instanceof com.github.javaparser.ast.stmt.BlockStmt)) {
        return "forbidden_statement";
      }
      return null;
    }

    static String mesaj(Node n, String varsayilan) {
      return switch (yasakKodu(n)) {
        case "branch" -> "dal (if/switch/?:) yasak: üretilen test doğrusal olmalı";
        case "loop" -> "döngü yasak: üretilen test doğrusal olmalı";
        case "lambda" -> "lambda / metot başvurusu yasak";
        case "new" -> "nesne oluşturma (new) yasak";
        case "array" -> "dizi yasak";
        case "text_block" -> "metin bloğu (\"\"\") yasak";
        case "this_super" -> "this / super yasak";
        case "local_variable" -> "yerel değişken yasak";
        case "assignment" -> "atama yasak";
        case "thread_sleep" -> "Thread.sleep yasak (deterministik bekleme ekran nesnesindedir)";
        case "raw_driver" -> "ham sürücüye erişim yasak; yalnızca ekran erişimcileri";
        case "static_call" -> "statik / alan üzerinden çağrı yasak (" + Kaynaklar.tekSatir(n.toString(), 60) + ")";
        case "field_access" -> "alan / değişken erişimi yasak (" + Kaynaklar.tekSatir(n.toString(), 60) + ")";
        case "forbidden_statement" -> "deyim yasak (" + n.getClass().getSimpleName() + "): " + varsayilan;
        default -> varsayilan;
      };
    }
  }
}
