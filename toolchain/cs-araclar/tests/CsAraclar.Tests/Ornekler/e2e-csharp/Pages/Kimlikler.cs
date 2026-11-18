namespace Antreklabs.Bayi.Pages;

/// <summary>data-testid sabitleri.</summary>
public static class Kimlikler
{
    public static class Nav
    {
        /// <summary>Sepet sayacı. Üst menüde.</summary>
        public const string CART_COUNT = "nav-cart-count";
    }

    public static class Login
    {
        /// <summary>Kullanıcı adı alanı.</summary>
        public const string USERNAME = "login-username";

        /// <summary>Parola alanı.</summary>
        public const string PASSWORD = "login-password";

        public const string SUBMIT = "login-submit";
    }

    public static class Catalog
    {
        /// <summary>Ürün kartı öneki.</summary>
        public const string PRODUCT_CARD_ONEK = "product-card-";

        public static class ProductCard
        {
            /// <summary>Sepete ekle butonu.</summary>
            public const string ADD_TO_CART = "add-to-cart";
        }
    }

    public static class Cart
    {
        public const string LINE_QUANTITY_ONEK = "cart-line-qty-";
        public const string TOTAL = "cart-total";
    }
}
