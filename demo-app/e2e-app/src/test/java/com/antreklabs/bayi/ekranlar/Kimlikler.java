package com.antreklabs.bayi.ekranlar;

/**
 * Erişilebilirlik kimlikleri — SAF VERİ (plan §2.8). Değerler web'deki data-testid'lerin aynısıdır.
 *
 * <p>Yalnızca iç içe sınıflar ve dize sabitleri; başka kod yok. Javadoc ilk cümlesi = niyet
 * (intent). {@code _ONEK} ile biten sabit önektir: ürün kodu / sipariş numarası eklenir
 * ({@code URUN_KARTI_ONEK + "P-001" = "product-card-P-001"}). Uygulamada kimlik değişirse onarım
 * yalnızca buradaki değeri değiştirir.
 */
public final class Kimlikler {
  private Kimlikler() {}

  /** Üst menü (tüm oturumlu ekranlarda ortak). */
  public static final class Menu {
    /** Üst menüde ürün kataloğuna giden bağlantı. */
    public static final String KATALOG = "nav-catalog";
    /** Üst menüde sepete giden bağlantı (sepet sayacını içerir). */
    public static final String SEPET = "nav-cart";
    /** Sepetteki toplam ürün adedini gösteren sayaç. */
    public static final String SEPET_SAYACI = "cart-count";
    /** Üst menüde sipariş geçmişine giden bağlantı. */
    public static final String SIPARISLER = "nav-orders";
    /** Oturumu kapatan buton. */
    public static final String CIKIS = "nav-logout";
    /** Oturum açmış bayinin adı. */
    public static final String BAYI_ADI = "current-dealer";
  }

  /** Giriş ekranı. */
  public static final class Giris {
    /** Giriş formunda kullanıcı adı alanı. */
    public static final String KULLANICI_ADI = "login-username";
    /** Giriş formunda parola alanı. */
    public static final String PAROLA = "login-password";
    /** Giriş formunu gönderen buton. */
    public static final String GIRIS_YAP = "login-submit";
    /** Hatalı girişte gösterilen hata mesajı. */
    public static final String HATA = "login-error";
  }

  /** Ürün kataloğu ekranı. */
  public static final class Katalog {
    /** Ürün kartlarının listesi. */
    public static final String URUN_LISTESI = "product-list";
    /** Tek bir ürünün kartı. */
    public static final String URUN_KARTI_ONEK = "product-card-";
    /** Ürün kartındaki birim fiyat. */
    public static final String URUN_FIYATI_ONEK = "product-price-";
    /** Ürün kartında eklenecek adet alanı. */
    public static final String ADET_ONEK = "qty-input-";
    /** Ürün kartında sepete ekleme butonu (her kartta aynı kimlik; ürün kartının içinde aranır). */
    public static final String SEPETE_EKLE = "add-to-cart";
    /** Sepete ekleme sonrası ürün kartındaki bilgi mesajı. */
    public static final String EKLEME_DURUMU_ONEK = "product-status-";
  }

  /** Sepet ekranı. */
  public static final class Sepet {
    /** Sepet satırları tablosu. */
    public static final String TABLO = "cart-table";
    /** Sepet boşken gösterilen bilgi alanı. */
    public static final String BOS = "cart-empty";
    /** Sepette bir ürünün satırı. */
    public static final String SATIR_ONEK = "cart-line-";
    /** Sepet satırındaki adet. */
    public static final String SATIR_ADEDI_ONEK = "cart-line-qty-";
    /** Sepet satırında kampanyayla bedava verilen adet. */
    public static final String BEDAVA_ADET_ONEK = "cart-line-free-";
    /** Sepet satırının indirim sonrası tutarı. */
    public static final String SATIR_TOPLAMI_ONEK = "cart-line-total-";
    /** Satırı sepetten kaldıran buton. */
    public static final String SATIRI_KALDIR_ONEK = "cart-line-remove-";
    /** Sepetin indirim öncesi ara toplamı. */
    public static final String ARA_TOPLAM = "cart-subtotal";
    /** Sepetteki toplam kampanya indirimi. */
    public static final String INDIRIM = "cart-discount";
    /** Sepetin indirim sonrası genel toplamı. */
    public static final String TOPLAM = "cart-total";
    /** Minimum sipariş tutarının altında gösterilen uyarı. */
    public static final String MIN_SIPARIS_UYARISI = "min-order-warning";
    /** Sipariş onayı başarısız olduğunda hata mesajı. */
    public static final String ONAY_HATASI = "checkout-error";
    /** Siparişi onaylayan buton. */
    public static final String SIPARISI_ONAYLA = "checkout-submit";
  }

  /** Sipariş onayı ekranı. */
  public static final class Onay {
    /** Sipariş onaylandıktan sonra gösterilen onay alanı. */
    public static final String ONAY_ALANI = "order-confirmation";
    /** Onay alanındaki sipariş numarası. */
    public static final String SIPARIS_NUMARASI = "order-number";
    /** Onaylanan siparişin kampanya indirimi. */
    public static final String INDIRIM = "order-discount";
    /** Onaylanan siparişin genel toplamı. */
    public static final String TOPLAM = "order-total";
    /** Onay ekranından sipariş geçmişine giden buton. */
    public static final String SIPARISLERIME_GIT = "go-orders";
    /** Onay ekranından kataloğa dönen buton. */
    public static final String ALISVERISE_DEVAM = "go-catalog";
  }

  /** Sipariş geçmişi (Siparişlerim) ekranı. */
  public static final class Siparis {
    /** Sipariş geçmişi tablosu. */
    public static final String TABLO = "orders-table";
    /** Hiç sipariş yokken gösterilen bilgi alanı. */
    public static final String BOS = "orders-empty";
    /** Sipariş geçmişinde bir siparişin satırı. */
    public static final String SATIR_ONEK = "order-row-";
    /** Sipariş geçmişi satırındaki genel toplam. */
    public static final String SATIR_TOPLAMI_ONEK = "order-total-";
  }
}
