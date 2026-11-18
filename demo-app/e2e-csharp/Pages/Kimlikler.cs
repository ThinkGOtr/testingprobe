namespace Antreklabs.Bayi.Pages;

/// <summary>
/// Web data-testid kimlikleri — SAF VERİ (014 §3.2; Java karşılığı e2e-java ekranlar/Kimlikler.java).
/// Değerler TypeScript <c>../e2e/pages/&lt;alan&gt;/locators.ts</c> ve <c>demo-app/kimlikler.json</c> ile
/// aynıdır; grup ve sabit adları Java Kimlikler.java ile birebirdir (<c>cart.lineQuantity</c> →
/// <c>Cart.LINE_QUANTITY_ONEK</c>). <c>_ONEK</c> ile biten sabit önektir: ürün kodu / sipariş numarası
/// eklenir. Kapsamlı kimlikler (TS <c>within</c>) kapsayıcının adını taşıyan iç gruptadır
/// (<c>Catalog.ProductCard</c>; kapsayıcı öneki <c>Catalog.PRODUCT_CARD_ONEK</c>).
///
/// Yalnız iç içe statik sınıflar ve <c>const string</c> sabitleri; başka kod yok (cs-araclar guard
/// <c>--kimlikler</c> denetler). Uygulamada data-testid değişirse onarım yalnız buradaki değeri değiştirir
/// (<c>cs-araclar locators patch</c>).
/// </summary>
public static class Kimlikler
{
    /// <summary>Ortak üst menü (tüm oturumlu sayfalarda).</summary>
    public static class Nav
    {
        /// <summary>Üst menüde ürün kataloğuna giden bağlantı.</summary>
        public const string CATALOG = "nav-catalog";
        /// <summary>Üst menüde sepete giden bağlantı (sepet sayacını içerir).</summary>
        public const string CART = "nav-cart";
        /// <summary>Sepetteki toplam ürün adedini gösteren sayaç.</summary>
        public const string CART_COUNT = "cart-count";
        /// <summary>Üst menüde sipariş geçmişine giden bağlantı.</summary>
        public const string ORDERS = "nav-orders";
        /// <summary>Oturumu kapatan buton.</summary>
        public const string LOGOUT = "nav-logout";
        /// <summary>Oturum açmış bayinin adı.</summary>
        public const string CURRENT_DEALER = "current-dealer";
    }

    /// <summary>Giriş sayfası.</summary>
    public static class Login
    {
        /// <summary>Giriş formunda kullanıcı adı alanı.</summary>
        public const string USERNAME = "login-username";
        /// <summary>Giriş formunda parola alanı.</summary>
        public const string PASSWORD = "login-password";
        /// <summary>Giriş formunu gönderen buton.</summary>
        public const string SUBMIT = "login-submit";
        /// <summary>Hatalı girişte gösterilen hata mesajı.</summary>
        public const string ERROR = "login-error";
    }

    /// <summary>Katalog sayfası.</summary>
    public static class Catalog
    {
        /// <summary>Ürün kartlarının listesi.</summary>
        public const string PRODUCT_LIST = "product-list";
        /// <summary>Tek bir ürünün kartı.</summary>
        public const string PRODUCT_CARD_ONEK = "product-card-";
        /// <summary>Ürün kartındaki birim fiyat.</summary>
        public const string PRODUCT_PRICE_ONEK = "product-price-";
        /// <summary>Sepete ekleme sonrası ürün kartındaki bilgi mesajı.</summary>
        public const string ADD_STATUS_ONEK = "product-status-";

        /// <summary>Ürün kartının (PRODUCT_CARD_ONEK + ürün kodu) içinde aranan kimlikler.</summary>
        public static class ProductCard
        {
            /// <summary>Ürün kartında eklenecek adet alanı.</summary>
            public const string QUANTITY_INPUT_ONEK = "qty-input-";
            /// <summary>Ürün kartında sepete ekleme butonu.</summary>
            public const string ADD_TO_CART = "add-to-cart";
        }
    }

    /// <summary>Sepet sayfası.</summary>
    public static class Cart
    {
        /// <summary>Sepet satırları tablosu.</summary>
        public const string TABLE = "cart-table";
        /// <summary>Sepet boşken gösterilen bilgi alanı.</summary>
        public const string EMPTY = "cart-empty";
        /// <summary>Sepette bir ürünün satırı.</summary>
        public const string LINE_ONEK = "cart-line-";
        /// <summary>Sepet satırındaki adet.</summary>
        public const string LINE_QUANTITY_ONEK = "cart-line-qty-";
        /// <summary>Sepet satırında kampanyayla bedava verilen adet.</summary>
        public const string LINE_FREE_ONEK = "cart-line-free-";
        /// <summary>Sepet satırının indirim sonrası tutarı.</summary>
        public const string LINE_TOTAL_ONEK = "cart-line-total-";
        /// <summary>Satırı sepetten kaldıran buton.</summary>
        public const string LINE_REMOVE_ONEK = "cart-line-remove-";
        /// <summary>Sepetin indirim öncesi ara toplamı.</summary>
        public const string SUBTOTAL = "cart-subtotal";
        /// <summary>Sepetteki toplam kampanya indirimi.</summary>
        public const string DISCOUNT = "cart-discount";
        /// <summary>Sepetin indirim sonrası genel toplamı.</summary>
        public const string TOTAL = "cart-total";
        /// <summary>Minimum sipariş tutarının altında gösterilen uyarı.</summary>
        public const string MIN_ORDER_WARNING = "min-order-warning";
        /// <summary>Sipariş onayı başarısız olduğunda hata mesajı.</summary>
        public const string CHECKOUT_ERROR = "checkout-error";
        /// <summary>Siparişi onaylayan buton.</summary>
        public const string CHECKOUT_SUBMIT = "checkout-submit";
    }

    /// <summary>Sipariş onayı ve sipariş geçmişi.</summary>
    public static class Order
    {
        /// <summary>Sipariş onaylandıktan sonra gösterilen onay alanı.</summary>
        public const string CONFIRMATION = "order-confirmation";
        /// <summary>Onay alanındaki sipariş numarası.</summary>
        public const string ORDER_NUMBER = "order-number";
        /// <summary>Onaylanan siparişin genel toplamı.</summary>
        public const string ORDER_TOTAL = "order-total";
        /// <summary>Sipariş geçmişi tablosu.</summary>
        public const string ORDERS_TABLE = "orders-table";
        /// <summary>Hiç sipariş yokken gösterilen bilgi alanı.</summary>
        public const string ORDERS_EMPTY = "orders-empty";
        /// <summary>Sipariş geçmişinde bir siparişin satırı.</summary>
        public const string ORDER_ROW_ONEK = "order-row-";
        /// <summary>Sipariş geçmişi satırındaki genel toplam.</summary>
        public const string ORDER_ROW_TOTAL_ONEK = "order-total-";
    }
}
