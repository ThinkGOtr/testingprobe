package com.antreklabs.tp.javaaraclar;

import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.ImportDeclaration;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.Parameter;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.expr.FieldAccessExpr;
import com.github.javaparser.ast.expr.NameExpr;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import java.util.regex.Pattern;

/**
 * Sembol tablosu çıkarıcı (009 plan §2.5, §2.8): TS {@code tp-symbols} ile AYNI şema.
 *
 * <p>Girdi: e2e-app kökü (içinde {@code src/test/java}). Ekran nesneleri = {@code ekranlar/}
 * altındaki, {@code Ekran}'dan (doğrudan ya da başka bir ekran üzerinden) türeyen üst düzey
 * sınıflar. Sembol tablosuna yalnız {@code public}, statik olmayan metotlar girer; {@code dogrula}
 * ile başlayan metot {@code kind: "expect"}, diğerleri {@code "action"}. Her ekranın
 * {@code locators}'ı, sınıfın kaynakta başvurduğu {@code Kimlikler} sabitleridir (anahtar
 * {@code Giris.KULLANICI_ADI}). Fikstür adı = {@code TestTabani} erişimcisi
 * ({@code lowerCamel(Sınıf)()}); bulunan erişimciler ek {@code fixtures} alanında listelenir.
 *
 * <p>Sözleşme dışı imzalar (void olmayan dönüş, desteklenmeyen parametre türü, aşırı yükleme)
 * tabloda kalır ama {@code errors}'a yazılır; kod üretimi ve koruma onları reddeder.
 */
public final class SembolCikarici {
  public static final int SCHEMA_VERSION = 1;
  public static final String TABAN_EKRAN = "Ekran";
  public static final String TEST_TABANI = "TestTabani";
  public static final String EKRAN_DIZINI = "ekranlar";
  public static final String DOGRULAMA_ONEKI = "dogrula";
  /** Sözleşmenin izin verdiği parametre türleri (§2.8). */
  public static final Set<String> PARAMETRE_TURLERI = Set.of("String", "int", "long", "double", "boolean");

  private static final Pattern NOKTALI_AD = Pattern.compile("^[A-Za-z_$][\\w$]*(\\.[A-Za-z_$][\\w$]*)*$");

  /** Metot imzası (koruyucunun kullandığı yapılandırılmış biçim). */
  public record Metot(String ad, List<String> parametreTurleri, String donus, String tur) {}

  /** Çıkarım sonucu: JSON tablosu + koruyucu için yapılandırılmış görünüm. */
  public record Tablo(
      Map<String, Object> json,
      Map<String, List<Metot>> metotlar,
      Map<String, String> erisimciler,
      boolean testTabaniVar,
      Map<String, KimlikDosyasi.Sonuc> kimlikDosyalari) {}

  private SembolCikarici() {}

  private record Dosya(Path yol, String gorel, CompilationUnit birim) {}

  public static Tablo cikar(Path kok, String kaynakDizini) throws IOException {
    Path root = kok.toAbsolutePath().normalize();
    Path src = root.resolve(kaynakDizini).normalize();
    if (!src.startsWith(root)) throw new IOException("kaynak dizini kök dışında: " + kaynakDizini);
    if (!Files.isDirectory(src)) {
      throw new IOException("kaynak dizini okunamadı: " + kaynakDizini);
    }
    List<Map<String, Object>> hatalar = new ArrayList<>();

    // 1) Ayrıştırılacak dosyalar: ekranlar/ altındakiler + TestTabani.java (TS: yalnızca pages/).
    List<Dosya> dosyalar = new ArrayList<>();
    for (Path p : Kaynaklar.javaDosyalari(src)) {
      String gorel = Kaynaklar.gorel(root, p);
      boolean ekran = Arrays.asList(gorel.split("/")).contains(EKRAN_DIZINI);
      boolean taban = p.getFileName().toString().equals(TEST_TABANI + ".java");
      if (!ekran && !taban) continue;
      String metin;
      try {
        metin = Kaynaklar.oku(p);
      } catch (IOException e) {
        hatalar.add(hata(gorel, 0, "okunamadı: " + e.getMessage()));
        continue;
      }
      Kaynaklar.Ayristirma a = Kaynaklar.ayristir(metin, gorel);
      hatalar.addAll(a.hatalar());
      if (a.birim() != null) dosyalar.add(new Dosya(p, gorel, a.birim()));
    }

    // 2) Kimlikler (saf veri).
    Map<String, KimlikDosyasi.Sonuc> kimlikDosyalari = new LinkedHashMap<>();
    Map<String, KimlikDosyasi.Kimlik> kimlikler = new LinkedHashMap<>();
    Map<String, String> kimlikDosyasi = new LinkedHashMap<>();
    for (Dosya d : dosyalar) {
      if (!KimlikDosyasi.kimlikDosyasiMi(d.gorel())) continue;
      KimlikDosyasi.Sonuc s = KimlikDosyasi.coz(d.birim());
      kimlikDosyalari.put(d.gorel(), s);
      for (KimlikDosyasi.Hata h : s.hatalar()) hatalar.add(hata(d.gorel(), h.satir(), h.mesaj()));
      for (KimlikDosyasi.Kimlik k : s.kimlikler().values()) {
        if (kimlikler.containsKey(k.anahtar())) {
          hatalar.add(hata(d.gorel(), k.satir(), k.anahtar() + ": başka bir Kimlikler dosyasında da tanımlı"));
          continue;
        }
        kimlikler.put(k.anahtar(), k);
        kimlikDosyasi.put(k.anahtar(), d.gorel());
      }
    }

    // 3) Ekran sınıfları (Ekran'dan doğrudan ya da dolaylı türeyen, ekranlar/ altındaki).
    Map<String, ClassOrInterfaceDeclaration> ekranAday = new TreeMap<>();
    Map<String, Dosya> sinifDosyasi = new LinkedHashMap<>();
    Map<String, String> ust = new LinkedHashMap<>();
    for (Dosya d : dosyalar) {
      if (KimlikDosyasi.kimlikDosyasiMi(d.gorel())) continue;
      if (!Arrays.asList(d.gorel().split("/")).contains(EKRAN_DIZINI)) continue;
      for (TypeDeclaration<?> t : d.birim().getTypes()) {
        if (!(t instanceof ClassOrInterfaceDeclaration c) || c.isInterface()) continue;
        if (c.getExtendedTypes().size() != 1) continue;
        String ad = c.getNameAsString();
        if (ekranAday.containsKey(ad)) {
          hatalar.add(hata(d.gorel(), Kaynaklar.satir(c), ad + ": aynı adlı ikinci ekran sınıfı (yok sayıldı)"));
          continue;
        }
        ekranAday.put(ad, c);
        sinifDosyasi.put(ad, d);
        ust.put(ad, c.getExtendedTypes().get(0).getNameAsString());
      }
    }
    Set<String> ekranlar = new TreeSet<>();
    for (String ad : ekranAday.keySet()) {
      Set<String> gorulen = new LinkedHashSet<>();
      String cur = ad;
      while (cur != null && gorulen.add(cur)) {
        String u = ust.get(cur);
        if (TABAN_EKRAN.equals(u)) {
          ekranlar.add(ad);
          break;
        }
        cur = u;
      }
    }

    // 4) TestTabani erişimcileri: lowerCamel(Sınıf)() → Sınıf.
    Map<String, String> erisimciler = new TreeMap<>();
    boolean testTabaniVar = false;
    for (Dosya d : dosyalar) {
      for (TypeDeclaration<?> t : d.birim().getTypes()) {
        if (!(t instanceof ClassOrInterfaceDeclaration c) || !c.getNameAsString().equals(TEST_TABANI)) continue;
        testTabaniVar = true;
        for (MethodDeclaration m : c.getMethods()) {
          if (m.isStatic() || m.isPrivate() || !m.getParameters().isEmpty()) continue;
          if (!(m.getType() instanceof ClassOrInterfaceType rt)) continue;
          String sinif = rt.getNameAsString();
          if (ekranlar.contains(sinif) && m.getNameAsString().equals(Kaynaklar.kucukDeve(sinif))) {
            erisimciler.put(m.getNameAsString(), sinif);
          }
        }
      }
    }
    if (!testTabaniVar && !ekranlar.isEmpty()) {
      hatalar.add(hata(kaynakDizini, 0, TEST_TABANI + " sınıfı bulunamadı: fikstür erişimcileri doğrulanamıyor"));
    }

    // 5) Ekran nesneleri.
    List<Map<String, Object>> sayfalar = new ArrayList<>();
    Map<String, List<Metot>> metotlar = new TreeMap<>();
    for (String ad : ekranlar) {
      ClassOrInterfaceDeclaration c = ekranAday.get(ad);
      Dosya d = sinifDosyasi.get(ad);
      List<Map<String, Object>> ms = new ArrayList<>();
      List<Metot> imzalar = new ArrayList<>();
      Map<String, Integer> adSayisi = new LinkedHashMap<>();
      for (MethodDeclaration m : c.getMethods()) {
        if (!m.isPublic() || m.isStatic()) continue;
        adSayisi.merge(m.getNameAsString(), 1, Integer::sum);
        ms.add(metotSembolu(m, d.gorel(), hatalar));
        List<String> turler = new ArrayList<>();
        for (Parameter p : m.getParameters()) turler.add(parametreTuru(p));
        imzalar.add(new Metot(m.getNameAsString(), turler, m.getType().asString(), tur(m.getNameAsString())));
      }
      for (Map.Entry<String, Integer> e : adSayisi.entrySet()) {
        if (e.getValue() > 1) {
          hatalar.add(hata(d.gorel(), Kaynaklar.satir(c), ad + "." + e.getKey() + ": aşırı yükleme (overload) desteklenmez"));
        }
      }
      if (testTabaniVar && !erisimciler.containsKey(Kaynaklar.kucukDeve(ad))) {
        hatalar.add(hata(d.gorel(), Kaynaklar.satir(c),
            ad + ": " + TEST_TABANI + "'nda fikstür erişimcisi yok (" + Kaynaklar.kucukDeve(ad) + "())"));
      }
      Map<String, Object> locators = new LinkedHashMap<>();
      Set<String> kullanilan = kullanilanKimlikler(d.birim(), kimlikler);
      for (KimlikDosyasi.Kimlik k : kimlikler.values()) {
        if (kullanilan.contains(k.anahtar())) locators.put(k.anahtar(), locatorSembolu(k, kimlikDosyasi.get(k.anahtar())));
      }
      Map<String, Object> po = new LinkedHashMap<>();
      po.put("class", ad);
      po.put("file", d.gorel());
      po.put("doc", Kaynaklar.ilkCumle(c));
      po.put("methods", ms);
      po.put("locators", locators);
      sayfalar.add(po);
      metotlar.put(ad, imzalar);
    }
    sayfalar.sort(Comparator.<Map<String, Object>, String>comparing(p -> (String) p.get("file"))
        .thenComparing(p -> (String) p.get("class")));

    List<Map<String, Object>> locatorFiles = new ArrayList<>();
    for (Map.Entry<String, KimlikDosyasi.Sonuc> e : new TreeMap<>(kimlikDosyalari).entrySet()) {
      Map<String, Object> lf = new LinkedHashMap<>();
      lf.put("file", e.getKey());
      lf.put("exports", new ArrayList<>(e.getValue().gruplar()));
      locatorFiles.add(lf);
    }

    Map<String, Object> json = new LinkedHashMap<>();
    json.put("schema_version", SCHEMA_VERSION);
    json.put("root", kaynakDizini.replace('\\', '/'));
    json.put("page_objects", sayfalar);
    json.put("locator_files", locatorFiles);
    json.put("errors", hatalar);
    json.put("fixtures", new ArrayList<>(erisimciler.keySet()));
    return new Tablo(json, metotlar, erisimciler, testTabaniVar, kimlikDosyalari);
  }

  /**
   * Doğrulama metodu: Türkçe {@code dogrula…} (uygulama ekranları) ya da TS sözleşmesiyle aynı adlı
   * web page object'lerinde {@code expect} / {@code expect<Büyük harf|rakam|_>…} (TS kuralı
   * {@code /^expect(?:$|[A-Z0-9_])/}; {@code expected…} gibi adlar eylemdir).
   */
  static String tur(String metotAdi) {
    return metotAdi.startsWith(DOGRULAMA_ONEKI) || EXPECT.matcher(metotAdi).find() ? "expect" : "action";
  }

  private static final Pattern EXPECT = Pattern.compile("^expect(?:$|[A-Z0-9_])");

  static String parametreTuru(Parameter p) {
    return p.getType().asString() + (p.isVarArgs() ? "..." : "");
  }

  private static Map<String, Object> metotSembolu(MethodDeclaration m, String dosya, List<Map<String, Object>> hatalar) {
    String ad = m.getNameAsString();
    List<Map<String, Object>> params = new ArrayList<>();
    for (Parameter p : m.getParameters()) {
      String tip = parametreTuru(p);
      Map<String, Object> ps = new LinkedHashMap<>();
      ps.put("name", p.getNameAsString());
      ps.put("type", tip);
      ps.put("optional", false);
      params.add(ps);
      if (!PARAMETRE_TURLERI.contains(tip)) {
        hatalar.add(hata(dosya, Kaynaklar.satir(p), ad + "(" + p.getNameAsString() + "): desteklenmeyen parametre türü " + tip
            + " (yalnız String, int, long, double, boolean)"));
      }
    }
    if (!m.getType().isVoidType()) {
      hatalar.add(hata(dosya, Kaynaklar.satir(m), ad + ": ekran metodu void dönmeli (" + m.getType().asString() + ")"));
    }
    if (!m.getTypeParameters().isEmpty()) {
      hatalar.add(hata(dosya, Kaynaklar.satir(m), ad + ": tür parametreli metot desteklenmez"));
    }
    Map<String, Object> out = new LinkedHashMap<>();
    out.put("name", ad);
    out.put("params", params);
    out.put("returns", m.getType().asString());
    out.put("kind", tur(ad));
    out.put("async", false);
    out.put("doc", Kaynaklar.ilkCumle(m));
    out.put("line", Kaynaklar.satir(m));
    return out;
  }

  private static Map<String, Object> locatorSembolu(KimlikDosyasi.Kimlik k, String dosya) {
    Map<String, Object> out = new LinkedHashMap<>();
    out.put("testId", k.testId());
    out.put("role", "");
    out.put("name", "");
    out.put("intent", k.niyet());
    out.put("prefix", k.onek());
    out.put("file", dosya);
    out.put("line", k.satir());
    return out;
  }

  /**
   * Ekran dosyasının başvurduğu kimlik anahtarları: {@code Kimlikler.Giris.X}, içe aktarılmış grup
   * ({@code import ….Kimlikler.Giris;} → {@code Giris.X}) ya da statik içe aktarma
   * ({@code import static ….Kimlikler.Giris.X;} / {@code ….Giris.*} → {@code X}).
   */
  static Set<String> kullanilanKimlikler(CompilationUnit cu, Map<String, KimlikDosyasi.Kimlik> kimlikler) {
    Map<String, String> grupTakma = new LinkedHashMap<>(); // yerel ad → grup yolu
    Map<String, String> statikAd = new LinkedHashMap<>(); // yerel sabit adı → anahtar
    for (ImportDeclaration imp : cu.getImports()) {
      List<String> parca = Arrays.asList(imp.getNameAsString().split("\\."));
      int i = parca.indexOf(KimlikDosyasi.SINIF);
      if (i < 0) continue;
      String sonra = String.join(".", parca.subList(i + 1, parca.size()));
      if (imp.isAsterisk()) {
        String onek = sonra.isEmpty() ? "" : sonra + ".";
        for (String anahtar : kimlikler.keySet()) {
          if (!anahtar.startsWith(onek)) continue;
          String kalan = anahtar.substring(onek.length());
          if (imp.isStatic() && !kalan.contains(".")) statikAd.put(kalan, anahtar);
          // Grup içe aktarımı (Kimlikler.* ya da statik iç sınıf): ilk bileşen bir grup adıdır.
          if (kalan.contains(".")) grupTakma.put(kalan.substring(0, kalan.indexOf('.')), onek + kalan.substring(0, kalan.indexOf('.')));
        }
      } else if (!sonra.isEmpty()) {
        String yerel = parca.get(parca.size() - 1);
        if (kimlikler.containsKey(sonra)) {
          statikAd.put(yerel, sonra);
        } else {
          grupTakma.put(yerel, sonra);
        }
      }
    }
    Set<String> out = new LinkedHashSet<>();
    for (FieldAccessExpr fa : cu.findAll(FieldAccessExpr.class)) {
      if (fa.getParentNode().filter(p -> p instanceof FieldAccessExpr).isPresent()) continue;
      cozumle(fa.toString(), grupTakma, statikAd, kimlikler, out);
    }
    for (NameExpr ne : cu.findAll(NameExpr.class)) {
      Node p = ne.getParentNode().orElse(null);
      if (p instanceof FieldAccessExpr) continue;
      cozumle(ne.getNameAsString(), grupTakma, statikAd, kimlikler, out);
    }
    return out;
  }

  private static void cozumle(
      String metin,
      Map<String, String> grupTakma,
      Map<String, String> statikAd,
      Map<String, KimlikDosyasi.Kimlik> kimlikler,
      Set<String> out) {
    if (!NOKTALI_AD.matcher(metin).matches()) return;
    List<String> s = Arrays.asList(metin.split("\\."));
    int i = s.indexOf(KimlikDosyasi.SINIF);
    String aday = null;
    if (i >= 0) {
      aday = String.join(".", s.subList(i + 1, s.size()));
    } else if (grupTakma.containsKey(s.get(0)) && s.size() > 1) {
      aday = grupTakma.get(s.get(0)) + "." + String.join(".", s.subList(1, s.size()));
    } else if (s.size() == 1 && statikAd.containsKey(s.get(0))) {
      aday = statikAd.get(s.get(0));
    }
    if (aday != null && kimlikler.containsKey(aday)) out.add(aday);
  }

  static Map<String, Object> hata(String dosya, int satir, String mesaj) {
    Map<String, Object> h = new LinkedHashMap<>();
    h.put("file", dosya);
    if (satir > 0) h.put("line", satir);
    h.put("message", mesaj);
    return h;
  }
}
