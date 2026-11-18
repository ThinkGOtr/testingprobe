namespace Antreklabs.Bayi.Ekranlar;

/// <summary>
/// Erişilebilirlik kimlikleri — SAF VERİ (plan §2.8). Değerler web'deki data-testid'lerin aynısıdır;
/// adlar Java <c>ekranlar/Kimlikler.java</c> ile birebir aynıdır (onarım anahtarı <c>Grup.SABIT</c>).
/// Yalnızca iç içe statik sınıflar ve <c>public const string</c> sabitleri; başka kod yok. Belge
/// yorumunun ilk cümlesi = niyet (intent). <c>_ONEK</c> ile biten sabit önektir: ürün kodu / sipariş
/// numarası eklenir. Uygulamada kimlik değişirse onarım yalnızca buradaki değeri değiştirir
/// (<c>cs-araclar locators patch</c>).
/// </summary>
public static class Kimlikler
{
    /// <summary>Üst menü (tüm oturumlu ekranlarda ortak).</summary>
    public static class Menu
    {
        /// <summary>Üst menüde ürün kataloğuna giden bağlantı.</summary>
        public const string KATALOG = "nav-catalog";
        /// <summary>Üst menüde sepete giden bağlantı (sepet sayacını içerir).</summary>
        public const string SEPET = "nav-cart";
        /// <summary>Sepetteki toplam ürün adedini gösteren sayaç.</summary>
        public const string SEPET_SAYACI = "cart-count";
        /// <summary>Üst menüde sipariş geçmişine giden bağlantı.</summary>
        public const string SIPARISLER = "nav-orders";
        /// <summary>Oturumu kapatan buton.</summary>
        public const string CIKIS = "nav-logout";
        /// <summary>Oturum açmış bayinin adı.</summary>
        public const string BAYI_ADI = "current-dealer";
    }

    /// <summary>Giriş ekranı.</summary>
    public static class Giris
    {
        /// <summary>Giriş formunda kullanıcı adı alanı.</summary>
        public const string KULLANICI_ADI = "login-username";
        /// <summary>Giriş formunda parola alanı.</summary>
        public const string PAROLA = "login-password";
        /// <summary>Giriş formunu gönderen buton.</summary>
        public const string GIRIS_YAP = "login-submit";
        /// <summary>Hatalı girişte gösterilen hata mesajı.</summary>
        public const string HATA = "login-error";
    }

    /// <summary>Ürün kataloğu ekranı.</summary>
    public static class Katalog
    {
        /// <summary>Ürün kartlarının listesi.</summary>
        public const string URUN_LISTESI = "product-list";
        /// <summary>Tek bir ürünün kartı.</summary>
        public const string URUN_KARTI_ONEK = "product-card-";
        /// <summary>Ürün kartındaki birim fiyat.</summary>
        public const string URUN_FIYATI_ONEK = "product-price-";
        /// <summary>Ürün kartında eklenecek adet alanı.</summary>
        public const string ADET_ONEK = "qty-input-";
        /// <summary>Ürün kartında sepete ekleme butonu (her kartta aynı kimlik; ürün kartının içinde aranır).</summary>
        public const string SEPETE_EKLE = "add-to-cart";
        /// <summary>Sepete ekleme sonrası ürün kartındaki bilgi mesajı.</summary>
        public const string EKLEME_DURUMU_ONEK = "product-status-";
    }

    /// <summary>Sepet ekranı.</summary>
    public static class Sepet
    {
        /// <summary>Sepet satırları tablosu.</summary>
        public const string TABLO = "cart-table";
        /// <summary>Sepet boşken gösterilen bilgi alanı.</summary>
        public const string BOS = "cart-empty";
        /// <summary>Sepette bir ürünün satırı.</summary>
        public const string SATIR_ONEK = "cart-line-";
        /// <summary>Sepet satırındaki adet.</summary>
        public const string SATIR_ADEDI_ONEK = "cart-line-qty-";
        /// <summary>Sepet satırında kampanyayla bedava verilen adet.</summary>
        public const string BEDAVA_ADET_ONEK = "cart-line-free-";
        /// <summary>Sepet satırının indirim sonrası tutarı.</summary>
        public const string SATIR_TOPLAMI_ONEK = "cart-line-total-";
        /// <summary>Satırı sepetten kaldıran buton.</summary>
        public const string SATIRI_KALDIR_ONEK = "cart-line-remove-";
        /// <summary>Sepetin indirim öncesi ara toplamı.</summary>
        public const string ARA_TOPLAM = "cart-subtotal";
        /// <summary>Sepetteki toplam kampanya indirimi.</summary>
        public const string INDIRIM = "cart-discount";
        /// <summary>Sepetin indirim sonrası genel toplamı.</summary>
        public const string TOPLAM = "cart-total";
        /// <summary>Minimum sipariş tutarının altında gösterilen uyarı.</summary>
        public const string MIN_SIPARIS_UYARISI = "min-order-warning";
        /// <summary>Sipariş onayı başarısız olduğunda hata mesajı.</summary>
        public const string ONAY_HATASI = "checkout-error";
        /// <summary>Siparişi onaylayan buton.</summary>
        public const string SIPARISI_ONAYLA = "checkout-submit";
    }

    /// <summary>Sipariş onayı ekranı.</summary>
    public static class Onay
    {
        /// <summary>Sipariş onaylandıktan sonra gösterilen onay alanı.</summary>
        public const string ONAY_ALANI = "order-confirmation";
        /// <summary>Onay alanındaki sipariş numarası.</summary>
        public const string SIPARIS_NUMARASI = "order-number";
        /// <summary>Onaylanan siparişin kampanya indirimi.</summary>
        public const string INDIRIM = "order-discount";
        /// <summary>Onaylanan siparişin genel toplamı.</summary>
        public const string TOPLAM = "order-total";
        /// <summary>Onay ekranından sipariş geçmişine giden buton.</summary>
        public const string SIPARISLERIME_GIT = "go-orders";
        /// <summary>Onay ekranından kataloğa dönen buton.</summary>
        public const string ALISVERISE_DEVAM = "go-catalog";
    }

    /// <summary>Sipariş geçmişi (Siparişlerim) ekranı.</summary>
    public static class Siparis
    {
        /// <summary>Sipariş geçmişi tablosu.</summary>
        public const string TABLO = "orders-table";
        /// <summary>Hiç sipariş yokken gösterilen bilgi alanı.</summary>
        public const string BOS = "orders-empty";
        /// <summary>Sipariş geçmişinde bir siparişin satırı.</summary>
        public const string SATIR_ONEK = "order-row-";
        /// <summary>Sipariş geçmişi satırındaki genel toplam.</summary>
        public const string SATIR_TOPLAMI_ONEK = "order-total-";
    }
}
