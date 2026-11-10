package com.antreklabs.tp.javaaraclar;

import com.github.javaparser.JavaToken;
import com.github.javaparser.ast.CompilationUnit;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Kimlik onarımı (009 plan §2.2 "yalnızca kimlik değeri değişir"; TS karşılığı core
 * {@code repair/locators.py patch_testid} + ast-guard {@code repair} modu).
 *
 * <ul>
 *   <li>{@code bul}: bir kimlik değerini taşıyan sabitler.
 *   <li>{@code yamala}: {@code Kimlikler.java}'da YALNIZCA o sabitin string literal içeriğini
 *       değiştirir; sonuç belirteç (token) düzeyinde yeniden doğrulanır.
 *   <li>{@code fark}: iki {@code Kimlikler.java} sürümü arasında yalnızca kimlik literal'lerinin
 *       değiştiğini doğrular (repair modu AST koruması).
 * </ul>
 */
public final class KimlikYamasi {
  private KimlikYamasi() {}

  /** Yama reddedildi (güvenle üretilemedi). */
  public static final class YamaHatasi extends Exception {
    private static final long serialVersionUID = 1L;

    public YamaHatasi(String mesaj) {
      super(mesaj);
    }
  }

  /** Kök altındaki {@code ekranlar/Kimlikler.java} dosyaları (göreli, sıralı). */
  public static List<String> kimlikDosyalari(Path kok) throws IOException {
    Path root = kok.toAbsolutePath().normalize();
    Path src = root.resolve(Kaynaklar.TEST_KAYNAK);
    if (!Files.isDirectory(src)) throw new IOException("kaynak dizini okunamadı: " + Kaynaklar.TEST_KAYNAK);
    List<String> out = new ArrayList<>();
    for (Path p : Kaynaklar.javaDosyalari(src)) {
      String g = Kaynaklar.gorel(root, p);
      if (KimlikDosyasi.kimlikDosyasiMi(g)) out.add(g);
    }
    return out;
  }

  // ------------------------------------------------------------------------------------- bul

  public static Map<String, Object> bul(Path kok, String testId) throws IOException {
    List<Map<String, Object>> eslesen = new ArrayList<>();
    for (String g : kimlikDosyalari(kok)) {
      KimlikDosyasi.Sonuc s = KimlikDosyasi.coz(Kaynaklar.oku(kok.resolve(g)));
      for (KimlikDosyasi.Kimlik k : s.kimlikler().values()) {
        boolean tam = k.testId().equals(testId);
        boolean onekle = k.onek() && testId.startsWith(k.testId());
        if (!tam && !onekle) continue;
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("key", k.anahtar());
        m.put("testId", k.testId());
        m.put("prefix", k.onek());
        m.put("intent", k.niyet());
        m.put("file", g);
        m.put("line", k.satir());
        eslesen.add(m);
      }
    }
    Map<String, Object> out = new LinkedHashMap<>();
    out.put("ok", true);
    out.put("test_id", testId);
    out.put("matches", eslesen);
    return out;
  }

  // ---------------------------------------------------------------------------------- yamala

  /**
   * {@code eski} kimlik değerini taşıyan TEK sabit literal'ini {@code yeni} yapar.
   *
   * @param anahtar isteğe bağlı: {@code Giris.KULLANICI_ADI} ya da {@code KULLANICI_ADI}
   * @param onekYol birleşik farktaki yol öneki (ör. {@code demo-app/e2e-app}); boş = kök göreli
   */
  public static Map<String, Object> yamala(Path kok, String eski, String yeni, String anahtar, String onekYol)
      throws IOException, YamaHatasi {
    if (eski == null || !KimlikDosyasi.TESTID.matcher(eski).matches()) throw new YamaHatasi("eski kimlik geçersiz: " + eski);
    if (yeni == null || !KimlikDosyasi.TESTID.matcher(yeni).matches()) throw new YamaHatasi("yeni kimlik geçersiz: " + yeni);
    if (eski.equals(yeni)) throw new YamaHatasi("eski ve yeni kimlik aynı");

    record Aday(String dosya, String metin, KimlikDosyasi.Kimlik kimlik) {}
    List<Aday> adaylar = new ArrayList<>();
    List<KimlikDosyasi.Kimlik> hepsi = new ArrayList<>();
    Map<String, String> metinler = new LinkedHashMap<>();
    for (String g : kimlikDosyalari(kok)) {
      String metin = Kaynaklar.oku(kok.toAbsolutePath().normalize().resolve(g));
      metinler.put(g, metin);
      KimlikDosyasi.Sonuc s = KimlikDosyasi.coz(metin);
      hepsi.addAll(s.kimlikler().values());
      for (KimlikDosyasi.Kimlik k : s.kimlikler().values()) {
        if (!k.testId().equals(eski)) continue;
        if (anahtar != null && !anahtar.isEmpty()
            && !(k.anahtar().equals(anahtar) || k.anahtar().endsWith("." + anahtar))) {
          continue;
        }
        if (!s.saf()) {
          throw new YamaHatasi(g + " saf veri değil (" + s.hatalar().get(0).mesaj() + "); yama üretilmez");
        }
        adaylar.add(new Aday(g, metin, k));
      }
    }
    if (adaylar.isEmpty()) throw new YamaHatasi("'" + eski + "' kimliğini taşıyan sabit bulunamadı");
    if (adaylar.size() > 1) {
      throw new YamaHatasi("'" + eski + "' birden çok sabitte geçiyor ("
          + String.join(", ", adaylar.stream().map(a -> a.kimlik().anahtar()).toList()) + "); --key ile seçin");
    }
    Aday a = adaylar.get(0);
    KimlikDosyasi.Kimlik k = a.kimlik();
    if (k.onek()) throw new YamaHatasi(k.anahtar() + " önek kimliktir (_ONEK); onarım kapsamı dışı");
    for (KimlikDosyasi.Kimlik d : hepsi) {
      if (d == k) continue;
      if (d.testId().equals(yeni) || (d.onek() && yeni.startsWith(d.testId()))) {
        throw new YamaHatasi("'" + yeni + "' başka bir kimliğin değeri ya da öneki (" + d.anahtar() + ")");
      }
    }

    CompilationUnit cu = Kaynaklar.ayristirici().parse(a.metin()).getResult()
        .orElseThrow(() -> new YamaHatasi("Kimlikler.java ayrıştırılamadı"));
    KimlikDosyasi.Sonuc s = KimlikDosyasi.coz(cu);
    KimlikDosyasi.Kimlik hedef = s.kimlikler().get(k.anahtar());
    if (hedef == null) throw new YamaHatasi("anahtar yeniden bulunamadı: " + k.anahtar());
    JavaToken literal = hedef.literal().getTokenRange().orElseThrow().getBegin();
    if (!literal.getText().equals("\"" + eski + "\"")) {
      throw new YamaHatasi(k.anahtar() + " literal'i kaçış dizisi içeriyor; metin düzeyinde güvenle değiştirilemez");
    }
    List<JavaToken> belirtecler = belirtecler(cu);
    if (!birlestir(belirtecler, null, null).equals(a.metin())) {
      throw new YamaHatasi("kaynak belirteçlerden aynen yeniden kurulamadı; yama üretilmez");
    }
    String sonuc = birlestir(belirtecler, literal, "\"" + yeni + "\"");

    // Yeniden doğrulama: sonuç saf veri, aynı anahtarlar, yalnızca bu kimlik farklı, tek satır farkı.
    Map<String, Object> fark = fark(a.metin(), sonuc, a.dosya());
    if (!Boolean.TRUE.equals(fark.get("ok"))) {
      throw new YamaHatasi("yama doğrulanamadı: " + fark.get("summary"));
    }
    String[] once = satirlar(a.metin());
    String[] sonra = satirlar(sonuc);
    if (once.length != sonra.length) throw new YamaHatasi("yama satır sayısını değiştirdi");
    int degisen = -1;
    for (int i = 0; i < once.length; i++) {
      if (!once[i].equals(sonra[i])) {
        if (degisen >= 0) throw new YamaHatasi("yama birden çok satırı değiştirdi");
        degisen = i;
      }
    }
    if (degisen < 0) throw new YamaHatasi("yama hiçbir satırı değiştirmedi");
    String yol = onekYol == null || onekYol.isEmpty() ? a.dosya() : onekYol.replaceAll("/+$", "") + "/" + a.dosya();

    Map<String, Object> out = new LinkedHashMap<>();
    out.put("ok", true);
    out.put("file", a.dosya());
    out.put("key", k.anahtar());
    out.put("line", degisen + 1);
    out.put("before", eski);
    out.put("after", yeni);
    out.put("diff", birlesikFark(yol, once, sonra, degisen));
    out.put("content", sonuc);
    return out;
  }

  // ------------------------------------------------------------------------------------- fark

  /** İki Kimlikler.java sürümü: yalnızca kimlik literal'leri değişebilir (TS repair modu). */
  public static Map<String, Object> fark(String taban, String bas, String dosya) {
    List<Map<String, Object>> ihlaller = new ArrayList<>();
    List<Map<String, Object>> degisimler = new ArrayList<>();
    KimlikDosyasi.Sonuc ts = KimlikDosyasi.coz(taban);
    KimlikDosyasi.Sonuc hs = KimlikDosyasi.coz(bas);
    if (!ts.saf()) {
      ihlaller.add(ihlal("base_not_pure", dosya, ts.hatalar().get(0).satir(), "taban Kimlikler.java saf veri değil: " + ts.hatalar().get(0).mesaj()));
    }
    for (KimlikDosyasi.Hata h : hs.hatalar()) ihlaller.add(ihlal(h.kod(), dosya, h.satir(), h.mesaj()));
    if (ihlaller.isEmpty()) {
      CompilationUnit tcu = Kaynaklar.ayristirici().parse(taban).getResult().orElseThrow();
      CompilationUnit hcu = Kaynaklar.ayristirici().parse(bas).getResult().orElseThrow();
      Map<JavaToken, KimlikDosyasi.Kimlik> tlit = literaller(KimlikDosyasi.coz(tcu));
      Map<JavaToken, KimlikDosyasi.Kimlik> hlit = literaller(KimlikDosyasi.coz(hcu));
      List<JavaToken> a = belirtecler(tcu);
      List<JavaToken> b = belirtecler(hcu);
      if (!birlestir(a, null, null).equals(taban) || !birlestir(b, null, null).equals(bas)) {
        ihlaller.add(ihlal("parse_error", dosya, 0, "kaynak belirteçlerden aynen yeniden kurulamadı"));
      } else {
        int n = Math.min(a.size(), b.size());
        for (int i = 0; i < n; i++) {
          JavaToken x = a.get(i);
          JavaToken y = b.get(i);
          if (x.getText().equals(y.getText())) continue;
          KimlikDosyasi.Kimlik kx = tlit.get(x);
          KimlikDosyasi.Kimlik ky = hlit.get(y);
          int satir = y.getRange().map(r -> r.begin.line).orElse(0);
          if (kx == null || ky == null || !kx.anahtar().equals(ky.anahtar())) {
            ihlaller.add(ihlal("non_testid_change", dosya, satir,
                "kimlik literal'i dışında değişiklik: '" + Kaynaklar.tekSatir(x.getText(), 60) + "' → '"
                    + Kaynaklar.tekSatir(y.getText(), 60) + "'"));
            break;
          }
          if (kx.onek()) {
            ihlaller.add(ihlal("prefix_changed", dosya, satir, kx.anahtar() + ": önek kimlik (_ONEK) onarımla değiştirilemez"));
          }
          Map<String, Object> d = new LinkedHashMap<>();
          d.put("file", dosya);
          d.put("entry", kx.anahtar());
          d.put("before", kx.testId());
          d.put("after", ky.testId());
          degisimler.add(d);
        }
        if (a.size() != b.size() && ihlaller.stream().noneMatch(v -> "non_testid_change".equals(v.get("code")))) {
          ihlaller.add(ihlal("non_testid_change", dosya, 0, "belirteç sayısı değişti (yapı değişikliği)"));
        }
      }
    }
    boolean noop = taban.equals(bas);
    Map<String, Object> rapor = new LinkedHashMap<>();
    rapor.put("tool", "java-araclar");
    rapor.put("schema_version", 1);
    rapor.put("mode", "repair");
    rapor.put("ok", ihlaller.isEmpty());
    rapor.put("noop", noop);
    rapor.put("root", ".");
    List<Map<String, Object>> cf = new ArrayList<>();
    if (!noop) {
      Map<String, Object> c = new LinkedHashMap<>();
      c.put("path", dosya);
      c.put("status", "modified");
      c.put("locator", true);
      cf.add(c);
    }
    rapor.put("changed_files", cf);
    rapor.put("testid_changes", degisimler);
    rapor.put("added_entries", List.of());
    rapor.put("removed_entries", List.of());
    rapor.put("violations", ihlaller);
    rapor.put("summary", (ihlaller.isEmpty() ? "Kimlik koruması geçti (mod: repair)" : "Kimlik koruması başarısız (mod: repair)")
        + " · kimlik değişikliği: " + degisimler.size() + (ihlaller.isEmpty() ? "" : " · ihlal: " + ihlaller.size()));
    return rapor;
  }

  // ------------------------------------------------------------------------------- yardımcı

  private static Map<JavaToken, KimlikDosyasi.Kimlik> literaller(KimlikDosyasi.Sonuc s) {
    Map<JavaToken, KimlikDosyasi.Kimlik> m = new IdentityHashMap<>();
    for (KimlikDosyasi.Kimlik k : s.kimlikler().values()) {
      k.literal().getTokenRange().ifPresent(r -> m.put(r.getBegin(), k));
    }
    return m;
  }

  /** Birimin tüm belirteçleri (boşluk ve yorumlar dahil), dosya başından sonuna. */
  static List<JavaToken> belirtecler(CompilationUnit cu) {
    JavaToken t = cu.getTokenRange().orElseThrow().getBegin();
    while (t.getPreviousToken().isPresent()) t = t.getPreviousToken().get();
    List<JavaToken> out = new ArrayList<>();
    for (JavaToken c = t; c != null; c = c.getNextToken().orElse(null)) out.add(c);
    return out;
  }

  static String birlestir(List<JavaToken> belirtecler, JavaToken degisen, String yeniMetin) {
    StringBuilder sb = new StringBuilder();
    for (JavaToken t : belirtecler) sb.append(t == degisen ? yeniMetin : t.getText());
    return sb.toString();
  }

  /** Satır sonlarını koruyarak satırlara böler (Python {@code splitlines(keepends=True)} gibi). */
  static String[] satirlar(String s) {
    List<String> out = new ArrayList<>();
    int bas = 0;
    for (int i = 0; i < s.length(); i++) {
      char c = s.charAt(i);
      if (c == '\n' || c == '\r') {
        if (c == '\r' && i + 1 < s.length() && s.charAt(i + 1) == '\n') i++;
        out.add(s.substring(bas, i + 1));
        bas = i + 1;
      }
    }
    if (bas < s.length()) out.add(s.substring(bas));
    return out.toArray(new String[0]);
  }

  /** Tek satırlık değişiklik için birleşik fark (difflib {@code unified_diff(n=1)} biçimi). */
  static String birlesikFark(String yol, String[] once, String[] sonra, int i) {
    int bas = Math.max(0, i - 1);
    int son = Math.min(once.length, i + 2);
    StringBuilder sb = new StringBuilder();
    sb.append("--- a/").append(yol).append('\n');
    sb.append("+++ b/").append(yol).append('\n');
    String aralik = (son - bas == 1) ? String.valueOf(bas + 1) : (bas + 1) + "," + (son - bas);
    sb.append("@@ -").append(aralik).append(" +").append(aralik).append(" @@\n");
    for (int j = bas; j < son; j++) {
      if (j == i) {
        sb.append('-').append(sonSatir(once[j]));
        sb.append('+').append(sonSatir(sonra[j]));
      } else {
        sb.append(' ').append(sonSatir(once[j]));
      }
    }
    return sb.toString();
  }

  private static String sonSatir(String satir) {
    return satir.endsWith("\n") || satir.endsWith("\r") ? satir : satir + "\n\\ No newline at end of file\n";
  }

  private static Map<String, Object> ihlal(String kod, String dosya, int satir, String mesaj) {
    Map<String, Object> m = new LinkedHashMap<>();
    m.put("code", kod);
    m.put("file", dosya);
    if (satir > 0) m.put("line", satir);
    m.put("message", mesaj);
    return m;
  }
}
