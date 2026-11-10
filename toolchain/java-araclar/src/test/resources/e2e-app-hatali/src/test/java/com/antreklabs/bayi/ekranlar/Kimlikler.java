package com.antreklabs.bayi.ekranlar;

import java.util.Locale;

/** Saf veri DEĞİL: her saflık ihlali bir hata üretir. */
public final class Kimlikler {
  private Kimlikler() {}

  static {
    System.out.println("kod");
  }

  /** Giriş ekranı. */
  public static final class Giris {
    /** Geçerli sabit. */
    public static final String KULLANICI_ADI = "login-username";
    /** Birleştirme yasak. */
    public static final String PAROLA = "login-" + "password";
    /** Metot çağrısı yasak. */
    public static final String GONDER = "LOGIN-SUBMIT".toLowerCase(Locale.ROOT);
    /** Final değil. */
    public static String HATA = "login-error";
    /** Tür String değil. */
    public static final int SAYI = 3;
    /** İki sabit tek bildirimde. */
    public static final String A = "a", B = "b";
    /** Geçersiz kimlik. */
    public static final String BOSLUKLU = "login error";
    /** Metin bloğu yasak. */
    public static final String BLOK = """
        login-block""";

    public static String yardimci() {
      return KULLANICI_ADI;
    }
  }

  /** Statik olmayan grup. */
  public final class Katalog {
    public static final String SEPETE_EKLE = "add-to-cart";
  }

  /** Geçerli grup. */
  public static final class Sepet {
    /** Sepet toplamı. */
    public static final String TOPLAM = "cart-total";
    /** Yinelenen anahtar. */
    public static final String TOPLAM = "cart-total-2";
  }
}

class Ek {}
