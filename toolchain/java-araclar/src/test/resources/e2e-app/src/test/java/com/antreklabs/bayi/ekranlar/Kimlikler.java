package com.antreklabs.bayi.ekranlar;

/** Erişilebilirlik kimlikleri: SAF VERİ (009 §2.8). */
public final class Kimlikler {
  private Kimlikler() {}

  /** Giriş ekranı. */
  public static final class Giris {
    /** Kullanıcı adı alanı. Giriş formunun ilk alanı. */
    public static final String KULLANICI_ADI = "login-username";
    /** Parola alanı. */
    public static final String PAROLA = "login-password";
    /** Giriş yap butonu. */
    public static final String GONDER = "login-submit";
    /** Hata mesajı. */
    public static final String HATA = "login-error";
  }

  /** Katalog ekranı. */
  public static final class Katalog {
    /** Ürün kartı (ürün kodu eklenir). */
    public static final String URUN_KARTI_ONEK = "product-card-";
    /** Sepete ekle butonu. */
    public static final String SEPETE_EKLE = "add-to-cart";
  }

  /** Sepet ekranı. */
  public static final class Sepet {
    /** Sepet toplamı. */
    public static final String TOPLAM = "cart-total";

    /** Sepet satırları. */
    public static final class Satir {
      /** Satır adedi. */
      public static final String ADET = "cart-line-qty";
    }
  }
}
