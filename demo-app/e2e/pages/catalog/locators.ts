// Katalog sayfası locator'ları — saf veri. Sonu `-` ile biten testId'ler önektir: ürün kodu eklenir (product-card-P-001).
// `within`: locator'ın arandığı kapsayıcının testId öneki; aynı rol + ada sahip eleman her üründe
// tekrarlandığı için eşleşme ürün kodu eklenmiş kapsayıcının (product-card-P-001) içinde aranır.
export const catalog = {
  productList: { testId: "product-list", role: "generic", name: "", intent: "Ürün kartlarının listesi" },
  productCard: { testId: "product-card-", role: "article", name: "", intent: "Tek bir ürünün kartı" },
  productPrice: { testId: "product-price-", role: "paragraph", name: "", intent: "Ürün kartındaki birim fiyat" },
  quantityInput: { testId: "qty-input-", role: "spinbutton", name: "Adet", within: "product-card-", intent: "Ürün kartında eklenecek adet alanı" },
  addToCart: { testId: "add-to-cart", role: "button", name: "Sepete ekle", within: "product-card-", intent: "Ürün kartında sepete ekleme butonu" },
  addStatus: { testId: "product-status-", role: "status", name: "", intent: "Sepete ekleme sonrası ürün kartındaki bilgi mesajı" },
} as const;
