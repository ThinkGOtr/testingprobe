package com.antreklabs.bayi.altyapi;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * e2e bayi kullanıcıları ve testin bayisini seçme kuralı (web: tests/fixtures.ts {@code DEALERS},
 * {@code pickDealer}).
 */
public final class Bayiler {

  /** Bir bayi kullanıcısı. */
  public static final class BayiBilgisi {
    private final String kullaniciAdi;
    private final String parola;
    private final String ad;

    public BayiBilgisi(String kullaniciAdi, String parola, String ad) {
      this.kullaniciAdi = kullaniciAdi;
      this.parola = parola;
      this.ad = ad;
    }

    public String kullaniciAdi() {
      return kullaniciAdi;
    }

    public String parola() {
      return parola;
    }

    /** Arayüzde gösterilen bayi adı (ör. "Merkez Bayi"). */
    public String ad() {
      return ad;
    }

    @Override
    public String toString() {
      return kullaniciAdi;
    }
  }

  /**
   * e2e bayileri (paralel işçi başına bir bayi). Parola seed verisidir (demo-app/api seed.py),
   * sır değildir; web e2e ile aynıdır.
   */
  public static final List<BayiBilgisi> E2E =
      List.of(
          new BayiBilgisi("bayi1", "Demo123!", "Merkez Bayi"),
          new BayiBilgisi("bayi2", "Demo123!", "Sahil Bayi"));

  /** Doğrulama ajanının (playwright-mcp / app-mcp) bayisi; e2e testleri kullanamaz ve sıfırlamaz. */
  public static final String AJAN_BAYISI = "bayi3";

  private Bayiler() {}

  /**
   * Testin bayisi: {@code sabit} verilmişse o, yoksa işçi sırasının bayisi (parola koşu ortamından,
   * yoksa seed).
   *
   * @param sabit {@code @Bayi} değeri (yoksa null)
   * @param isciSirasi paralel işçi sırası (tek iş parçacığında 0)
   */
  public static BayiBilgisi sec(String sabit, int isciSirasi) {
    if (sabit != null) {
      for (BayiBilgisi b : E2E) {
        if (b.kullaniciAdi().equals(sabit)) {
          return kosuParolasiyla(b);
        }
      }
      String ayrilmis = AJAN_BAYISI.equals(sabit) ? " (doğrulama ajanına ayrılmıştır)" : "";
      throw new IllegalArgumentException(
          "@Bayi(\"" + sabit + "\") bir e2e bayisi değil" + ayrilmis + "; izinli: " + izinliler());
    }
    if (isciSirasi < 0 || isciSirasi >= E2E.size()) {
      throw new IllegalArgumentException(
          "En fazla " + E2E.size() + " paralel işçi desteklenir (bayi kullanıcısı sayısı); işçi sırası " + isciSirasi);
    }
    return kosuParolasiyla(E2E.get(isciSirasi));
  }

  /** Test sınıfının bayisi: sınıftaki (ya da üst sınıftaki) {@link Bayi} notasyonu, yoksa işçi bayisi. */
  public static BayiBilgisi sinifIcin(Class<?> testSinifi, int isciSirasi) {
    Bayi not = testSinifi.getAnnotation(Bayi.class);
    return sec(not == null ? null : not.value(), isciSirasi);
  }

  /**
   * Koşu hesabı başına parola: test-runner {@code TP_RUN_DEALER_PASSWORDS} = JSON
   * {@code {"<kullanıcı>": "<parola>"}} verir (AI Probe › Test kullanıcıları; yalnız parolası girilen
   * hesaplar). Hesabın parolası yoksa seed (ortak) parolası kullanılır.
   */
  public static final String KOSU_PAROLALARI_ENV = "TP_RUN_DEALER_PASSWORDS";

  /**
   * {@code TP_RUN_DEALER_PASSWORDS} değerini çözer (boş/null = boş harita). Yalnız düz
   * {@code {"metin": "metin", …}} nesnesi kabul edilir; bozuk değer açık hatayla durur (değer
   * iletiye yazılmaz). Boş parolalar atlanır.
   */
  public static Map<String, String> kosuParolalari(String ham) {
    Map<String, String> out = new LinkedHashMap<>();
    if (ham == null || ham.isBlank()) {
      return out;
    }
    JsonOkuyucu o = new JsonOkuyucu(ham);
    try {
      o.bekle('{');
      if (!o.varsa('}')) {
        do {
          String ad = o.metin();
          o.bekle(':');
          String parola = o.metin();
          if (!parola.isEmpty()) {
            out.put(ad, parola);
          }
        } while (o.varsa(','));
        o.bekle('}');
      }
      o.son();
    } catch (IllegalStateException e) {
      throw new IllegalArgumentException(KOSU_PAROLALARI_ENV + " geçerli bir JSON nesnesi değil");
    }
    return out;
  }

  /** Bayinin bu koşudaki parolası: koşu ortamında girilmişse o, yoksa seed (ortak) parolası. */
  public static BayiBilgisi kosuParolasiyla(BayiBilgisi b, Map<String, String> parolalar) {
    String p = parolalar.get(b.kullaniciAdi());
    return p == null ? b : new BayiBilgisi(b.kullaniciAdi(), p, b.ad());
  }

  private static BayiBilgisi kosuParolasiyla(BayiBilgisi b) {
    return kosuParolasiyla(b, kosuParolalari(System.getenv(KOSU_PAROLALARI_ENV)));
  }

  /** Düz JSON nesnesi okuyucusu (yalnız metin değerler; bağımlılık eklememek için). */
  private static final class JsonOkuyucu {
    private final String s;
    private int i;

    JsonOkuyucu(String s) {
      this.s = s;
    }

    private void bosluk() {
      while (i < s.length() && Character.isWhitespace(s.charAt(i))) {
        i++;
      }
    }

    void bekle(char c) {
      if (!varsa(c)) {
        throw new IllegalStateException();
      }
    }

    boolean varsa(char c) {
      bosluk();
      if (i < s.length() && s.charAt(i) == c) {
        i++;
        return true;
      }
      return false;
    }

    void son() {
      bosluk();
      if (i != s.length()) {
        throw new IllegalStateException();
      }
    }

    String metin() {
      bekle('"');
      StringBuilder b = new StringBuilder();
      while (i < s.length()) {
        char c = s.charAt(i++);
        if (c == '"') {
          return b.toString();
        }
        if (c < 0x20) {
          throw new IllegalStateException();
        }
        if (c != '\\') {
          b.append(c);
          continue;
        }
        if (i >= s.length()) {
          throw new IllegalStateException();
        }
        char e = s.charAt(i++);
        switch (e) {
          case '"', '\\', '/' -> b.append(e);
          case 'b' -> b.append('\b');
          case 'f' -> b.append('\f');
          case 'n' -> b.append('\n');
          case 'r' -> b.append('\r');
          case 't' -> b.append('\t');
          case 'u' -> {
            if (i + 4 > s.length()) {
              throw new IllegalStateException();
            }
            try {
              b.append((char) Integer.parseInt(s.substring(i, i + 4), 16));
            } catch (NumberFormatException ex) {
              throw new IllegalStateException();
            }
            i += 4;
          }
          default -> throw new IllegalStateException();
        }
      }
      throw new IllegalStateException();
    }
  }

  private static String izinliler() {
    return E2E.stream().map(BayiBilgisi::kullaniciAdi).collect(Collectors.joining(", "));
  }
}
