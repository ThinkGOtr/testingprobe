# Locator verisi — SAF VERİ (TS: pages/**/locators.ts ile birebir). Yalnız üst düzey
# `AD = {...}` sözlük literalleri; içe aktarma, işlev ya da ifade YOK (py-guard denetler).
# Sonu `-` ile biten testId önektir: ürün kodu / sipariş no eklenir ("product-card-" + "P-001").
# `within`: aynı rol + ad her kartta tekrarlandığı için eşleşmenin arandığı kapsayıcının öneki.
# Uygulamada data-testid değişirse onarım yalnız buradaki "testId" değerini değiştirir.

NAV = {
    "catalog": {"testId": "nav-catalog", "role": "link", "name": "Katalog", "intent": "Üst menüde ürün kataloğuna giden bağlantı"},
    "cart": {"testId": "nav-cart", "role": "link", "name": "Sepet", "intent": "Üst menüde sepete giden bağlantı (sepet sayacını içerir)"},
    "cartCount": {"testId": "cart-count", "role": "generic", "name": "", "intent": "Sepetteki toplam ürün adedini gösteren sayaç"},
    "orders": {"testId": "nav-orders", "role": "link", "name": "Siparişlerim", "intent": "Üst menüde sipariş geçmişine giden bağlantı"},
    "logout": {"testId": "nav-logout", "role": "button", "name": "Çıkış yap", "intent": "Oturumu kapatan buton"},
    "currentDealer": {"testId": "current-dealer", "role": "generic", "name": "", "intent": "Oturum açmış bayinin adı"},
}

LOGIN = {
    "username": {"testId": "login-username", "role": "textbox", "name": "Kullanıcı adı", "intent": "Giriş formunda kullanıcı adı alanı"},
    "password": {"testId": "login-password", "role": "textbox", "name": "Parola", "intent": "Giriş formunda parola alanı"},
    "submit": {"testId": "login-submit", "role": "button", "name": "Giriş yap", "intent": "Giriş formunu gönderen buton"},
    "error": {"testId": "login-error", "role": "alert", "name": "", "intent": "Hatalı girişte gösterilen hata mesajı"},
}

CATALOG = {
    "productList": {"testId": "product-list", "role": "generic", "name": "", "intent": "Ürün kartlarının listesi"},
    "productCard": {"testId": "product-card-", "role": "article", "name": "", "intent": "Tek bir ürünün kartı"},
    "productPrice": {"testId": "product-price-", "role": "paragraph", "name": "", "intent": "Ürün kartındaki birim fiyat"},
    "quantityInput": {"testId": "qty-input-", "role": "spinbutton", "name": "Adet", "within": "product-card-", "intent": "Ürün kartında eklenecek adet alanı"},
    "addToCart": {"testId": "add-to-cart", "role": "button", "name": "Sepete ekle", "within": "product-card-", "intent": "Ürün kartında sepete ekleme butonu"},
    "addStatus": {"testId": "product-status-", "role": "status", "name": "", "intent": "Sepete ekleme sonrası ürün kartındaki bilgi mesajı"},
}

CART = {
    "table": {"testId": "cart-table", "role": "table", "name": "Sepetteki ürünler", "intent": "Sepet satırları tablosu"},
    "empty": {"testId": "cart-empty", "role": "generic", "name": "", "intent": "Sepet boşken gösterilen bilgi alanı"},
    "line": {"testId": "cart-line-", "role": "row", "name": "", "intent": "Sepette bir ürünün satırı"},
    "lineQuantity": {"testId": "cart-line-qty-", "role": "generic", "name": "", "intent": "Sepet satırındaki adet"},
    "lineFree": {"testId": "cart-line-free-", "role": "generic", "name": "", "intent": "Sepet satırında kampanyayla bedava verilen adet"},
    "lineTotal": {"testId": "cart-line-total-", "role": "cell", "name": "", "intent": "Sepet satırının indirim sonrası tutarı"},
    "lineRemove": {"testId": "cart-line-remove-", "role": "button", "name": "", "intent": "Satırı sepetten kaldıran buton"},
    "subtotal": {"testId": "cart-subtotal", "role": "definition", "name": "", "intent": "Sepetin indirim öncesi ara toplamı"},
    "discount": {"testId": "cart-discount", "role": "generic", "name": "", "intent": "Sepetteki toplam kampanya indirimi"},
    "total": {"testId": "cart-total", "role": "definition", "name": "", "intent": "Sepetin indirim sonrası genel toplamı"},
    "minOrderWarning": {"testId": "min-order-warning", "role": "alert", "name": "", "intent": "Minimum sipariş tutarının altında gösterilen uyarı"},
    "checkoutError": {"testId": "checkout-error", "role": "alert", "name": "", "intent": "Sipariş onayı başarısız olduğunda hata mesajı"},
    "checkoutSubmit": {"testId": "checkout-submit", "role": "button", "name": "Siparişi onayla", "intent": "Siparişi onaylayan buton"},
}

ORDER = {
    "confirmation": {"testId": "order-confirmation", "role": "region", "name": "Siparişiniz alındı", "intent": "Sipariş onaylandıktan sonra gösterilen onay alanı"},
    "orderNumber": {"testId": "order-number", "role": "strong", "name": "", "intent": "Onay alanındaki sipariş numarası"},
    "orderTotal": {"testId": "order-total", "role": "definition", "name": "", "intent": "Onaylanan siparişin genel toplamı"},
    "ordersTable": {"testId": "orders-table", "role": "table", "name": "Sipariş geçmişi", "intent": "Sipariş geçmişi tablosu"},
    "ordersEmpty": {"testId": "orders-empty", "role": "generic", "name": "", "intent": "Hiç sipariş yokken gösterilen bilgi alanı"},
    "orderRow": {"testId": "order-row-", "role": "row", "name": "", "intent": "Sipariş geçmişinde bir siparişin satırı"},
    "orderRowTotal": {"testId": "order-total-", "role": "cell", "name": "", "intent": "Sipariş geçmişi satırındaki genel toplam"},
}
