// Erişilebilirlik kimlikleri — SAF VERİ (TASARIM §3.4; Java karşılığı: e2e-app ekranlar/Kimlikler.java).
//
// Değerler web'deki data-testid'lerin aynısıdır; iOS'ta `accessibilityIdentifier` olarak okunur
// (demo-app/kimlikler.json sözleşmesi). Yalnızca iç içe `enum`'lar ve `static let` dize sabitleri;
// başka kod yok (worker/diller/swift.py koruması bunu denetler). `///` belge yorumunun ilk cümlesi =
// niyet (intent). `Onek` ile biten sabit önektir: ürün kodu / sipariş numarası eklenir
// (`Katalog.urunKartiOnek + "P-001" = "product-card-P-001"`). Uygulamada kimlik değişirse onarım
// yalnızca buradaki değeri değiştirir.

enum Kimlikler {
    /// Üst menü (tüm oturumlu ekranlarda ortak).
    enum Menu {
        /// Üst menüde ürün kataloğuna giden bağlantı.
        static let katalog = "nav-catalog"
        /// Üst menüde sepete giden bağlantı (sepet sayacını içerir).
        static let sepet = "nav-cart"
        /// Sepetteki toplam ürün adedini gösteren sayaç.
        static let sepetSayaci = "cart-count"
        /// Üst menüde sipariş geçmişine giden bağlantı.
        static let siparisler = "nav-orders"
        /// Oturumu kapatan buton.
        static let cikis = "nav-logout"
        /// Oturum açmış bayinin adı.
        static let bayiAdi = "current-dealer"
    }

    /// Giriş ekranı.
    enum Giris {
        /// Giriş formunda kullanıcı adı alanı.
        static let kullaniciAdi = "login-username"
        /// Giriş formunda parola alanı.
        static let parola = "login-password"
        /// Giriş formunu gönderen buton.
        static let girisYap = "login-submit"
        /// Hatalı girişte gösterilen hata mesajı.
        static let hata = "login-error"
    }

    /// Ürün kataloğu ekranı.
    enum Katalog {
        /// Ürün kartlarının listesi.
        static let urunListesi = "product-list"
        /// Tek bir ürünün kartı.
        static let urunKartiOnek = "product-card-"
        /// Ürün kartındaki birim fiyat.
        static let urunFiyatiOnek = "product-price-"
        /// Ürün kartında eklenecek adet alanı.
        static let adetOnek = "qty-input-"
        /// Ürün kartında sepete ekleme butonu (her kartta aynı kimlik; ürün kartının içinde aranır).
        static let sepeteEkle = "add-to-cart"
        /// Sepete ekleme sonrası ürün kartındaki bilgi mesajı.
        static let eklemeDurumuOnek = "product-status-"
    }

    /// Sepet ekranı.
    enum Sepet {
        /// Sepet satırları tablosu.
        static let tablo = "cart-table"
        /// Sepet boşken gösterilen bilgi alanı.
        static let bos = "cart-empty"
        /// Sepette bir ürünün satırı.
        static let satirOnek = "cart-line-"
        /// Sepet satırındaki adet.
        static let satirAdediOnek = "cart-line-qty-"
        /// Sepet satırında kampanyayla bedava verilen adet.
        static let bedavaAdetOnek = "cart-line-free-"
        /// Sepet satırının indirim sonrası tutarı.
        static let satirToplamiOnek = "cart-line-total-"
        /// Satırı sepetten kaldıran buton.
        static let satiriKaldirOnek = "cart-line-remove-"
        /// Sepetin indirim öncesi ara toplamı.
        static let araToplam = "cart-subtotal"
        /// Sepetteki toplam kampanya indirimi.
        static let indirim = "cart-discount"
        /// Sepetin indirim sonrası genel toplamı.
        static let toplam = "cart-total"
        /// Minimum sipariş tutarının altında gösterilen uyarı.
        static let minSiparisUyarisi = "min-order-warning"
        /// Sipariş onayı başarısız olduğunda hata mesajı.
        static let onayHatasi = "checkout-error"
        /// Siparişi onaylayan buton.
        static let siparisiOnayla = "checkout-submit"
    }

    /// Sipariş onayı ekranı.
    enum Onay {
        /// Sipariş onaylandıktan sonra gösterilen onay alanı.
        static let onayAlani = "order-confirmation"
        /// Onay alanındaki sipariş numarası.
        static let siparisNumarasi = "order-number"
        /// Onaylanan siparişin kampanya indirimi.
        static let indirim = "order-discount"
        /// Onaylanan siparişin genel toplamı.
        static let toplam = "order-total"
        /// Onay ekranından sipariş geçmişine giden buton.
        static let siparislerimeGit = "go-orders"
        /// Onay ekranından kataloğa dönen buton.
        static let alisveriseDevam = "go-catalog"
    }

    /// Sipariş geçmişi (Siparişlerim) ekranı.
    enum Siparis {
        /// Sipariş geçmişi tablosu.
        static let tablo = "orders-table"
        /// Hiç sipariş yokken gösterilen bilgi alanı.
        static let bos = "orders-empty"
        /// Sipariş geçmişinde bir siparişin satırı.
        static let satirOnek = "order-row-"
        /// Sipariş geçmişi satırındaki genel toplam.
        static let satirToplamiOnek = "order-total-"
    }
}
