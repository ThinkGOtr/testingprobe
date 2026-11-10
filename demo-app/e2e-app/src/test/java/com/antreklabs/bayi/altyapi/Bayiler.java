package com.antreklabs.bayi.altyapi;

import java.util.List;
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

  /** Doğrulama ajanının (app-mcp / playwright-mcp) bayisi; e2e testleri kullanamaz ve sıfırlamaz. */
  public static final String AJAN_BAYISI = "bayi3";

  private Bayiler() {}

  /**
   * Testin bayisi: {@code sabit} verilmişse o, yoksa işçi sırasının bayisi.
   *
   * @param sabit {@code @Bayi} değeri (yoksa null)
   * @param isciSirasi paralel işçi sırası (tek cihazda 0)
   */
  public static BayiBilgisi sec(String sabit, int isciSirasi) {
    if (sabit != null) {
      for (BayiBilgisi b : E2E) {
        if (b.kullaniciAdi().equals(sabit)) {
          return b;
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
    return E2E.get(isciSirasi);
  }

  /** Test sınıfının bayisi: sınıftaki (ya da üst sınıftaki) {@link Bayi} notasyonu, yoksa işçi bayisi. */
  public static BayiBilgisi sinifIcin(Class<?> testSinifi, int isciSirasi) {
    Bayi not = testSinifi.getAnnotation(Bayi.class);
    return sec(not == null ? null : not.value(), isciSirasi);
  }

  private static String izinliler() {
    return E2E.stream().map(BayiBilgisi::kullaniciAdi).collect(Collectors.joining(", "));
  }
}
