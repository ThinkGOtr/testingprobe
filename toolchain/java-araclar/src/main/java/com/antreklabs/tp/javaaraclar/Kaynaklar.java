package com.antreklabs.tp.javaaraclar;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ParseResult;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.Problem;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.comments.JavadocComment;
import com.github.javaparser.ast.nodeTypes.NodeWithJavadoc;
import java.io.IOException;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Stream;

/**
 * Ortak yardımcılar: dosya gezme, ayrıştırma, göreli yol, Javadoc ilk cümlesi.
 *
 * <p>Kaynak yalnızca AYRIŞTIRILIR (JavaParser); hiçbir dosya derlenmez ya da çalıştırılmaz. Kod
 * güvenilmeyen girdidir.
 */
public final class Kaynaklar {
  private Kaynaklar() {}

  /** Taranmayan dizinler (derleme çıktısı, VCS, IDE). */
  static final Set<String> YOK_SAYILAN = Set.of("target", ".git", ".mvn", ".idea", "build", "out");

  /** Java test kaynak kökü (e2e-app köküne göre). */
  public static final String TEST_KAYNAK = "src/test/java";

  /** Java 17 sözdizimi; Unicode kaçışları ön işlenmez (koruyucu onları ayrıca reddeder). */
  public static JavaParser ayristirici() {
    ParserConfiguration cfg = new ParserConfiguration();
    cfg.setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_17);
    cfg.setAttributeComments(true);
    cfg.setPreprocessUnicodeEscapes(false);
    cfg.setStoreTokens(true);
    return new JavaParser(cfg);
  }

  /** Ayrıştırma sonucu: birim (sözdizimi hatası varsa null olabilir) + hatalar. */
  public record Ayristirma(CompilationUnit birim, List<Map<String, Object>> hatalar) {
    public boolean temiz() {
      return birim != null && hatalar.isEmpty();
    }
  }

  /** UTF-8 metni katı çözer (geçersiz bayt dizisi = hata). */
  public static String oku(Path dosya) throws IOException {
    byte[] b = Files.readAllBytes(dosya);
    try {
      return StandardCharsets.UTF_8
          .newDecoder()
          .onMalformedInput(CodingErrorAction.REPORT)
          .onUnmappableCharacter(CodingErrorAction.REPORT)
          .decode(java.nio.ByteBuffer.wrap(b))
          .toString();
    } catch (CharacterCodingException e) {
      throw new IOException("dosya geçerli UTF-8 değil");
    }
  }

  public static Ayristirma ayristir(String metin, String gorelDosya) {
    ParseResult<CompilationUnit> sonuc = ayristirici().parse(metin);
    List<Map<String, Object>> hatalar = new ArrayList<>();
    for (Problem p : sonuc.getProblems()) {
      Map<String, Object> h = new LinkedHashMap<>();
      h.put("file", gorelDosya);
      p.getLocation()
          .flatMap(l -> l.getBegin().getRange())
          .ifPresent(r -> h.put("line", r.begin.line));
      h.put("message", "sözdizimi: " + tekSatir(p.getMessage(), 300));
      hatalar.add(h);
    }
    return new Ayristirma(sonuc.getResult().orElse(null), hatalar);
  }

  /** {@code dizin} altındaki .java dosyaları (sembolik bağlar izlenmez), sıralı. */
  public static List<Path> javaDosyalari(Path dizin) throws IOException {
    List<Path> out = new ArrayList<>();
    gez(dizin, out);
    return out;
  }

  private static void gez(Path dizin, List<Path> out) throws IOException {
    List<Path> cocuklar;
    try (Stream<Path> s = Files.list(dizin)) {
      cocuklar = s.sorted((a, b) -> a.getFileName().toString().compareTo(b.getFileName().toString())).toList();
    }
    for (Path c : cocuklar) {
      if (Files.isSymbolicLink(c)) continue;
      String ad = c.getFileName().toString();
      if (Files.isDirectory(c, LinkOption.NOFOLLOW_LINKS)) {
        if (!YOK_SAYILAN.contains(ad)) gez(c, out);
      } else if (Files.isRegularFile(c, LinkOption.NOFOLLOW_LINKS) && ad.endsWith(".java")) {
        out.add(c);
      }
    }
  }

  /** {@code kok}'e göre POSIX yolu. */
  public static String gorel(Path kok, Path dosya) {
    Path r = kok.toAbsolutePath().normalize().relativize(dosya.toAbsolutePath().normalize());
    return r.toString().replace('\\', '/');
  }

  public static int satir(Node n) {
    return n.getBegin().map(p -> p.line).orElse(0);
  }

  /** {@code GirisEkrani} → {@code girisEkrani} (TS {@code fixture_name} ile aynı kural). */
  public static String kucukDeve(String sinif) {
    if (sinif.isEmpty()) return sinif;
    return sinif.substring(0, 1).toLowerCase(java.util.Locale.ROOT) + sinif.substring(1);
  }

  /** Javadoc'un ilk cümlesi (boşluklar teke indirilir); Javadoc yoksa boş. */
  public static String ilkCumle(NodeWithJavadoc<?> n) {
    return n.getJavadocComment().map(Kaynaklar::ilkCumle).orElse("");
  }

  public static String ilkCumle(JavadocComment jd) {
    String aciklama = jd.parse().getDescription().toText();
    String tek = aciklama.replaceAll("\\s+", " ").strip();
    // Javadoc kuralı: ilk cümle, ardından boşluk (ya da metin sonu) gelen ilk noktada biter.
    for (int i = 0; i < tek.length(); i++) {
      if (tek.charAt(i) == '.' && (i + 1 == tek.length() || tek.charAt(i + 1) == ' ')) {
        return tek.substring(0, i + 1);
      }
    }
    return tek;
  }

  static String tekSatir(String s, int sinir) {
    String t = s.replaceAll("\\s+", " ").strip();
    return t.length() <= sinir ? t : t.substring(0, sinir) + "…";
  }
}
