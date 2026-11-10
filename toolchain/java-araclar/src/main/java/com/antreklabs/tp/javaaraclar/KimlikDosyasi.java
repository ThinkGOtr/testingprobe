package com.antreklabs.tp.javaaraclar;

import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Modifier;
import com.github.javaparser.ast.NodeList;
import com.github.javaparser.ast.body.BodyDeclaration;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import com.github.javaparser.ast.body.FieldDeclaration;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.body.VariableDeclarator;
import com.github.javaparser.ast.expr.StringLiteralExpr;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * {@code ekranlar/Kimlikler.java} — SAF VERİ (009 plan §2.8).
 *
 * <p>Dosyada yalnızca: {@code package}, tek üst düzey {@code public final class Kimlikler}, onun
 * {@code private Kimlikler() {}} kurucusu, iç içe {@code public static final class} grupları ve
 * {@code public static final String AD = "literal";} sabitleri. Başka her şey (import, metot,
 * statik blok, başka tür, birleştirme, metin bloğu, notasyon …) bir HATA'dır ve o öğe atlanır.
 * Javadoc ilk cümlesi = {@code intent}; {@code _ONEK} ile biten sabit önektir.
 *
 * <p>Anahtar: grup yolu + sabit adı, noktayla ({@code Giris.KULLANICI_ADI}).
 */
public final class KimlikDosyasi {
  public static final String DOSYA_ADI = "Kimlikler.java";
  public static final String SINIF = "Kimlikler";
  public static final String ONEK_SONEKI = "_ONEK";
  /** data-testid / erişilebilirlik kimliği biçimi (TS ast-guard ile aynı). */
  public static final Pattern TESTID = Pattern.compile("^[A-Za-z0-9][A-Za-z0-9_.:-]*$");

  /** Tek kimlik sabiti. */
  public record Kimlik(
      String anahtar, String testId, boolean onek, String niyet, int satir, StringLiteralExpr literal) {}

  /** Saflık ihlali. */
  public record Hata(String kod, int satir, String mesaj) {}

  /** Ayrıştırma sonucu (gruplar = üst düzey grup adları, kaynak sırasıyla). */
  public record Sonuc(List<String> gruplar, Map<String, Kimlik> kimlikler, List<Hata> hatalar) {
    public boolean saf() {
      return hatalar.isEmpty();
    }
  }

  private KimlikDosyasi() {}

  public static boolean kimlikDosyasiMi(String gorelYol) {
    return gorelYol.endsWith("/ekranlar/" + DOSYA_ADI) || gorelYol.equals("ekranlar/" + DOSYA_ADI);
  }

  /** Metni karakter denetimi + AST ile çözer (sözdizimi hatası da bir saflık hatasıdır). */
  public static Sonuc coz(String metin) {
    List<Hata> hatalar = new ArrayList<>();
    for (KarakterDenetimi.Bulgu b : KarakterDenetimi.denetle(metin)) {
      hatalar.add(new Hata(b.kod(), b.satir(), b.mesaj()));
    }
    Kaynaklar.Ayristirma a = Kaynaklar.ayristir(metin, DOSYA_ADI);
    for (Map<String, Object> h : a.hatalar()) {
      Object satir = h.get("line");
      hatalar.add(new Hata("parse_error", satir instanceof Integer i ? i : 0, (String) h.get("message")));
    }
    if (a.birim() == null) {
      return new Sonuc(List.of(), new LinkedHashMap<>(), hatalar);
    }
    Sonuc s = coz(a.birim());
    hatalar.addAll(s.hatalar());
    return new Sonuc(s.gruplar(), s.kimlikler(), hatalar);
  }

  public static Sonuc coz(CompilationUnit cu) {
    List<Hata> hatalar = new ArrayList<>();
    Map<String, Kimlik> kimlikler = new LinkedHashMap<>();
    List<String> gruplar = new ArrayList<>();
    cu.getModule().ifPresent(m -> hatalar.add(new Hata("forbidden_statement", Kaynaklar.satir(m), "modül bildirimi yasak")));
    cu.getPackageDeclaration()
        .filter(p -> !p.getAnnotations().isEmpty())
        .ifPresent(p -> hatalar.add(new Hata("forbidden_statement", Kaynaklar.satir(p), "paket notasyonu yasak")));
    cu.getImports()
        .forEach(i -> hatalar.add(new Hata("forbidden_statement", Kaynaklar.satir(i),
            "Kimlikler saf veridir: içe aktarma yasak (" + i.getNameAsString() + ")")));
    ClassOrInterfaceDeclaration kok = null;
    for (TypeDeclaration<?> t : cu.getTypes()) {
      if (kok == null && t instanceof ClassOrInterfaceDeclaration c && c.getNameAsString().equals(SINIF)) {
        kok = c;
      } else {
        hatalar.add(new Hata("forbidden_statement", Kaynaklar.satir(t),
            "Kimlikler.java'da tek üst düzey tür olmalı: public final class Kimlikler (" + t.getNameAsString() + ")"));
      }
    }
    if (kok == null) {
      hatalar.add(new Hata("forbidden_statement", 1, "public final class Kimlikler bulunamadı"));
      return new Sonuc(gruplar, kimlikler, hatalar);
    }
    sinifBasligi(kok, EnumSet.of(Modifier.Keyword.PUBLIC, Modifier.Keyword.FINAL), "Kimlikler", hatalar);
    uyeler(kok, List.of(), true, gruplar, kimlikler, hatalar);
    return new Sonuc(gruplar, kimlikler, hatalar);
  }

  private static void sinifBasligi(
      ClassOrInterfaceDeclaration c, Set<Modifier.Keyword> beklenen, String yol, List<Hata> hatalar) {
    int satir = Kaynaklar.satir(c);
    if (c.isInterface()) hatalar.add(new Hata("forbidden_statement", satir, yol + ": arayüz değil sınıf olmalı"));
    if (!anahtarlar(c.getModifiers()).equals(beklenen)) {
      hatalar.add(new Hata("forbidden_statement", satir, yol + ": niteleyiciler "
          + beklenen.stream().map(Modifier.Keyword::asString).collect(Collectors.joining(" ")) + " olmalı"));
    }
    if (!c.getAnnotations().isEmpty()) hatalar.add(new Hata("forbidden_statement", satir, yol + ": notasyon yasak"));
    if (!c.getExtendedTypes().isEmpty() || !c.getImplementedTypes().isEmpty() || !c.getPermittedTypes().isEmpty()) {
      hatalar.add(new Hata("forbidden_statement", satir, yol + ": extends/implements/permits yasak"));
    }
    if (!c.getTypeParameters().isEmpty()) hatalar.add(new Hata("forbidden_statement", satir, yol + ": tür parametresi yasak"));
  }

  private static void uyeler(
      ClassOrInterfaceDeclaration sinif,
      List<String> yol,
      boolean kok,
      List<String> gruplar,
      Map<String, Kimlik> kimlikler,
      List<Hata> hatalar) {
    for (BodyDeclaration<?> uye : sinif.getMembers()) {
      int satir = Kaynaklar.satir(uye);
      String konum = yol.isEmpty() ? SINIF : String.join(".", yol);
      if (uye instanceof ConstructorDeclaration k && kok) {
        if (!anahtarlar(k.getModifiers()).equals(EnumSet.of(Modifier.Keyword.PRIVATE))
            || !k.getParameters().isEmpty()
            || !k.getBody().getStatements().isEmpty()
            || !k.getAnnotations().isEmpty()
            || !k.getThrownExceptions().isEmpty()
            || !k.getTypeParameters().isEmpty()) {
          hatalar.add(new Hata("forbidden_statement", satir, "Kimlikler kurucusu yalnızca 'private Kimlikler() {}' olabilir"));
        }
      } else if (uye instanceof ClassOrInterfaceDeclaration g) {
        List<String> altYol = new ArrayList<>(yol);
        altYol.add(g.getNameAsString());
        String ad = String.join(".", altYol);
        int once = hatalar.size();
        sinifBasligi(g, EnumSet.of(Modifier.Keyword.PUBLIC, Modifier.Keyword.STATIC, Modifier.Keyword.FINAL), ad, hatalar);
        if (hatalar.size() > once) continue;
        if (kok) {
          if (gruplar.contains(g.getNameAsString())) {
            hatalar.add(new Hata("duplicate_key", satir, ad + ": grup birden çok kez tanımlı"));
            continue;
          }
          gruplar.add(g.getNameAsString());
        }
        uyeler(g, altYol, false, gruplar, kimlikler, hatalar);
      } else if (uye instanceof FieldDeclaration f) {
        sabit(f, yol, konum, kimlikler, hatalar);
      } else {
        hatalar.add(new Hata("forbidden_statement", satir,
            konum + ": beklenmeyen öğe (yalnızca iç içe public static final class ve public static final String sabiti)"));
      }
    }
  }

  private static void sabit(
      FieldDeclaration f, List<String> yol, String konum, Map<String, Kimlik> kimlikler, List<Hata> hatalar) {
    int satir = Kaynaklar.satir(f);
    if (!anahtarlar(f.getModifiers()).equals(
            EnumSet.of(Modifier.Keyword.PUBLIC, Modifier.Keyword.STATIC, Modifier.Keyword.FINAL))
        || !f.getAnnotations().isEmpty()) {
      hatalar.add(new Hata("forbidden_statement", satir, konum + ": sabit 'public static final String' olmalı (notasyonsuz)"));
      return;
    }
    if (f.getVariables().size() != 1) {
      hatalar.add(new Hata("forbidden_statement", satir, konum + ": bildirim başına tek sabit"));
      return;
    }
    VariableDeclarator v = f.getVariable(0);
    String ad = v.getNameAsString();
    if (!(v.getType() instanceof ClassOrInterfaceType t)
        || !t.getNameAsString().equals("String")
        || t.getScope().isPresent()
        || t.getTypeArguments().isPresent()
        || !t.getAnnotations().isEmpty()) {
      hatalar.add(new Hata("forbidden_statement", satir, konum + "." + ad + ": tür String olmalı"));
      return;
    }
    if (v.getInitializer().isEmpty() || !(v.getInitializer().get() instanceof StringLiteralExpr lit)) {
      hatalar.add(new Hata("non_literal_value", satir, konum + "." + ad + ": değer yalnızca string literal olabilir"));
      return;
    }
    List<String> tam = new ArrayList<>(yol);
    tam.add(ad);
    String anahtar = String.join(".", tam);
    if (kimlikler.containsKey(anahtar)) {
      hatalar.add(new Hata("duplicate_key", satir, anahtar + ": birden çok kez tanımlı"));
      return;
    }
    String deger = lit.asString();
    if (!TESTID.matcher(deger).matches()) {
      hatalar.add(new Hata("invalid_testid", satir, anahtar + ": geçersiz kimlik değeri '" + Kaynaklar.tekSatir(deger, 80) + "'"));
    }
    kimlikler.put(anahtar,
        new Kimlik(anahtar, deger, ad.endsWith(ONEK_SONEKI), Kaynaklar.ilkCumle(f), Kaynaklar.satir(f), lit));
  }

  static Set<Modifier.Keyword> anahtarlar(NodeList<Modifier> m) {
    Set<Modifier.Keyword> s = EnumSet.noneOf(Modifier.Keyword.class);
    for (Modifier x : m) s.add(x.getKeyword());
    return s;
  }
}
