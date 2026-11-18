# Erişilebilirlik kimlikleri — SAF VERİ (Java: ekranlar/Kimlikler.java ile birebir; değerler web
# data-testid'lerinin aynısı). Yalnız üst düzey `AD = {...}` sözlük literalleri; içe aktarma, işlev
# ya da ifade YOK (py-guard denetler). `_ONEK` ile biten anahtar önektir: ürün kodu / sipariş no
# eklenir (`kimlik.ekli`). `intent` Javadoc'un ilk cümlesidir. Uygulamada kimlik değişirse onarım
# yalnız buradaki "testId" değerini değiştirir.

MENU = {
    "KATALOG": {"testId": "nav-catalog", "intent": "Üst menüde ürün kataloğuna giden bağlantı."},
    "SEPET": {"testId": "nav-cart", "intent": "Üst menüde sepete giden bağlantı (sepet sayacını içerir)."},
    "SEPET_SAYACI": {"testId": "cart-count", "intent": "Sepetteki toplam ürün adedini gösteren sayaç."},
    "SIPARISLER": {"testId": "nav-orders", "intent": "Üst menüde sipariş geçmişine giden bağlantı."},
    "CIKIS": {"testId": "nav-logout", "intent": "Oturumu kapatan buton."},
    "BAYI_ADI": {"testId": "current-dealer", "intent": "Oturum açmış bayinin adı."},
}

GIRIS = {
    "KULLANICI_ADI": {"testId": "login-username", "intent": "Giriş formunda kullanıcı adı alanı."},
    "PAROLA": {"testId": "login-password", "intent": "Giriş formunda parola alanı."},
    "GIRIS_YAP": {"testId": "login-submit", "intent": "Giriş formunu gönderen buton."},
    "HATA": {"testId": "login-error", "intent": "Hatalı girişte gösterilen hata mesajı."},
}

KATALOG = {
    "URUN_LISTESI": {"testId": "product-list", "intent": "Ürün kartlarının listesi."},
    "URUN_KARTI_ONEK": {"testId": "product-card-", "intent": "Tek bir ürünün kartı."},
    "URUN_FIYATI_ONEK": {"testId": "product-price-", "intent": "Ürün kartındaki birim fiyat."},
    "ADET_ONEK": {"testId": "qty-input-", "intent": "Ürün kartında eklenecek adet alanı."},
    "SEPETE_EKLE": {"testId": "add-to-cart", "intent": "Ürün kartında sepete ekleme butonu (her kartta aynı kimlik; ürün kartının içinde aranır)."},
    "EKLEME_DURUMU_ONEK": {"testId": "product-status-", "intent": "Sepete ekleme sonrası ürün kartındaki bilgi mesajı."},
}

SEPET = {
    "TABLO": {"testId": "cart-table", "intent": "Sepet satırları tablosu."},
    "BOS": {"testId": "cart-empty", "intent": "Sepet boşken gösterilen bilgi alanı."},
    "SATIR_ONEK": {"testId": "cart-line-", "intent": "Sepette bir ürünün satırı."},
    "SATIR_ADEDI_ONEK": {"testId": "cart-line-qty-", "intent": "Sepet satırındaki adet."},
    "BEDAVA_ADET_ONEK": {"testId": "cart-line-free-", "intent": "Sepet satırında kampanyayla bedava verilen adet."},
    "SATIR_TOPLAMI_ONEK": {"testId": "cart-line-total-", "intent": "Sepet satırının indirim sonrası tutarı."},
    "SATIRI_KALDIR_ONEK": {"testId": "cart-line-remove-", "intent": "Satırı sepetten kaldıran buton."},
    "ARA_TOPLAM": {"testId": "cart-subtotal", "intent": "Sepetin indirim öncesi ara toplamı."},
    "INDIRIM": {"testId": "cart-discount", "intent": "Sepetteki toplam kampanya indirimi."},
    "TOPLAM": {"testId": "cart-total", "intent": "Sepetin indirim sonrası genel toplamı."},
    "MIN_SIPARIS_UYARISI": {"testId": "min-order-warning", "intent": "Minimum sipariş tutarının altında gösterilen uyarı."},
    "ONAY_HATASI": {"testId": "checkout-error", "intent": "Sipariş onayı başarısız olduğunda hata mesajı."},
    "SIPARISI_ONAYLA": {"testId": "checkout-submit", "intent": "Siparişi onaylayan buton."},
}

ONAY = {
    "ONAY_ALANI": {"testId": "order-confirmation", "intent": "Sipariş onaylandıktan sonra gösterilen onay alanı."},
    "SIPARIS_NUMARASI": {"testId": "order-number", "intent": "Onay alanındaki sipariş numarası."},
    "INDIRIM": {"testId": "order-discount", "intent": "Onaylanan siparişin kampanya indirimi."},
    "TOPLAM": {"testId": "order-total", "intent": "Onaylanan siparişin genel toplamı."},
    "SIPARISLERIME_GIT": {"testId": "go-orders", "intent": "Onay ekranından sipariş geçmişine giden buton."},
    "ALISVERISE_DEVAM": {"testId": "go-catalog", "intent": "Onay ekranından kataloğa dönen buton."},
}

SIPARIS = {
    "TABLO": {"testId": "orders-table", "intent": "Sipariş geçmişi tablosu."},
    "BOS": {"testId": "orders-empty", "intent": "Hiç sipariş yokken gösterilen bilgi alanı."},
    "SATIR_ONEK": {"testId": "order-row-", "intent": "Sipariş geçmişinde bir siparişin satırı."},
    "SATIR_TOPLAMI_ONEK": {"testId": "order-total-", "intent": "Sipariş geçmişi satırındaki genel toplam."},
}
