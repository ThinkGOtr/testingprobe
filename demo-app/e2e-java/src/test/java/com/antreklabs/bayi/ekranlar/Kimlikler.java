package com.antreklabs.bayi.ekranlar;

/**
 * Web data-testid kimlikleri — SAF VERİ (009 plan §2.8, 011 plan §2.5). Değerler TypeScript
 * {@code ../e2e/pages/<alan>/locators.ts} ve {@code demo-app/kimlikler.json} ile aynıdır.
 *
 * <p>Yalnızca iç içe sınıflar ve dize sabitleri; başka kod yok. Javadoc ilk cümlesi = niyet
 * (intent). Adlar TypeScript anahtarlarının karşılığıdır: {@code cart.lineQuantity} →
 * {@code Cart.LINE_QUANTITY_ONEK}. {@code _ONEK} ile biten sabit önektir: ürün kodu / sipariş
 * numarası eklenir ({@code PRODUCT_CARD_ONEK + "P-001" = "product-card-P-001"}).
 *
 * <p>Kapsamlı kimlikler (TypeScript {@code within}): rol + ad sayfada tekrarlanan eleman, kapsayıcısının
 * adını taşıyan iç grupta durur ({@code Catalog.ProductCard}); kapsayıcının öneki üst gruptaki aynı
 * adlı sabittir ({@code Catalog.PRODUCT_CARD_ONEK}). Eşleşme {@code PRODUCT_CARD_ONEK + ürün kodu}
 * kapsayıcısının içinde aranır ({@link Ekran#kapsam}).
 *
 * <p>Uygulamada data-testid değişirse onarım yalnızca buradaki değeri değiştirir.
 */
public final class Kimlikler {
  private Kimlikler() {}

  /** Ortak üst menü (tüm oturumlu sayfalarda). */
  public static final class Nav {
    /** Üst menüde ürün kataloğuna giden bağlantı. */
    public static final String CATALOG = "nav-catalog";
    /** Üst menüde sepete giden bağlantı (sepet sayacını içerir). */
    public static final String CART = "nav-cart";
    /** Sepetteki toplam ürün adedini gösteren sayaç. */
    public static final String CART_COUNT = "cart-count";
    /** Üst menüde sipariş geçmişine giden bağlantı. */
    public static final String ORDERS = "nav-orders";
    /** Oturumu kapatan buton. */
    public static final String LOGOUT = "nav-logout";
    /** Oturum açmış bayinin adı. */
    public static final String CURRENT_DEALER = "current-dealer";
  }

  /** Giriş sayfası. */
  public static final class Login {
    /** Giriş formunda kullanıcı adı alanı. */
    public static final String USERNAME = "login-username";
    /** Giriş formunda parola alanı. */
    public static final String PASSWORD = "login-password";
    /** Giriş formunu gönderen buton. */
    public static final String SUBMIT = "login-submit";
    /** Hatalı girişte gösterilen hata mesajı. */
    public static final String ERROR = "login-error";
  }

  /** Katalog sayfası. */
  public static final class Catalog {
    /** Ürün kartlarının listesi. */
    public static final String PRODUCT_LIST = "product-list";
    /** Tek bir ürünün kartı. */
    public static final String PRODUCT_CARD_ONEK = "product-card-";
    /** Ürün kartındaki birim fiyat. */
    public static final String PRODUCT_PRICE_ONEK = "product-price-";
    /** Sepete ekleme sonrası ürün kartındaki bilgi mesajı. */
    public static final String ADD_STATUS_ONEK = "product-status-";

    /** Ürün kartının (PRODUCT_CARD_ONEK + ürün kodu) içinde aranan kimlikler. */
    public static final class ProductCard {
      /** Ürün kartında eklenecek adet alanı. */
      public static final String QUANTITY_INPUT_ONEK = "qty-input-";
      /** Ürün kartında sepete ekleme butonu. */
      public static final String ADD_TO_CART = "add-to-cart";
    }
  }

  /** Sepet sayfası. */
  public static final class Cart {
    /** Sepet satırları tablosu. */
    public static final String TABLE = "cart-table";
    /** Sepet boşken gösterilen bilgi alanı. */
    public static final String EMPTY = "cart-empty";
    /** Sepette bir ürünün satırı. */
    public static final String LINE_ONEK = "cart-line-";
    /** Sepet satırındaki adet. */
    public static final String LINE_QUANTITY_ONEK = "cart-line-qty-";
    /** Sepet satırında kampanyayla bedava verilen adet. */
    public static final String LINE_FREE_ONEK = "cart-line-free-";
    /** Sepet satırının indirim sonrası tutarı. */
    public static final String LINE_TOTAL_ONEK = "cart-line-total-";
    /** Satırı sepetten kaldıran buton. */
    public static final String LINE_REMOVE_ONEK = "cart-line-remove-";
    /** Sepetin indirim öncesi ara toplamı. */
    public static final String SUBTOTAL = "cart-subtotal";
    /** Sepetteki toplam kampanya indirimi. */
    public static final String DISCOUNT = "cart-discount";
    /** Sepetin indirim sonrası genel toplamı. */
    public static final String TOTAL = "cart-total";
    /** Minimum sipariş tutarının altında gösterilen uyarı. */
    public static final String MIN_ORDER_WARNING = "min-order-warning";
    /** Sipariş onayı başarısız olduğunda hata mesajı. */
    public static final String CHECKOUT_ERROR = "checkout-error";
    /** Siparişi onaylayan buton. */
    public static final String CHECKOUT_SUBMIT = "checkout-submit";
  }

  /** Sipariş onayı ve sipariş geçmişi. */
  public static final class Order {
    /** Sipariş onaylandıktan sonra gösterilen onay alanı. */
    public static final String CONFIRMATION = "order-confirmation";
    /** Onay alanındaki sipariş numarası. */
    public static final String ORDER_NUMBER = "order-number";
    /** Onaylanan siparişin genel toplamı. */
    public static final String ORDER_TOTAL = "order-total";
    /** Sipariş geçmişi tablosu. */
    public static final String ORDERS_TABLE = "orders-table";
    /** Hiç sipariş yokken gösterilen bilgi alanı. */
    public static final String ORDERS_EMPTY = "orders-empty";
    /** Sipariş geçmişinde bir siparişin satırı. */
    public static final String ORDER_ROW_ONEK = "order-row-";
    /** Sipariş geçmişi satırındaki genel toplam. */
    public static final String ORDER_ROW_TOTAL_ONEK = "order-total-";
  }
}
