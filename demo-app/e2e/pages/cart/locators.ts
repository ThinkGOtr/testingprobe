// Sepet sayfası locator'ları — saf veri. Sonu `-` ile biten testId'ler önektir: ürün kodu eklenir (product-card-P-001).
export const cart = {
  table: { testId: "cart-table", role: "table", name: "Sepetteki ürünler", intent: "Sepet satırları tablosu" },
  empty: { testId: "cart-empty", role: "generic", name: "", intent: "Sepet boşken gösterilen bilgi alanı" },
  line: { testId: "cart-line-", role: "row", name: "", intent: "Sepette bir ürünün satırı" },
  lineQuantity: { testId: "cart-line-qty-", role: "generic", name: "", intent: "Sepet satırındaki adet" },
  lineFree: { testId: "cart-line-free-", role: "generic", name: "", intent: "Sepet satırında kampanyayla bedava verilen adet" },
  lineTotal: { testId: "cart-line-total-", role: "cell", name: "", intent: "Sepet satırının indirim sonrası tutarı" },
  lineRemove: { testId: "cart-line-remove-", role: "button", name: "", intent: "Satırı sepetten kaldıran buton" },
  subtotal: { testId: "cart-subtotal", role: "definition", name: "", intent: "Sepetin indirim öncesi ara toplamı" },
  discount: { testId: "cart-discount", role: "generic", name: "", intent: "Sepetteki toplam kampanya indirimi" },
  total: { testId: "cart-total", role: "definition", name: "", intent: "Sepetin indirim sonrası genel toplamı" },
  minOrderWarning: { testId: "min-order-warning", role: "alert", name: "", intent: "Minimum sipariş tutarının altında gösterilen uyarı" },
  checkoutError: { testId: "checkout-error", role: "alert", name: "", intent: "Sipariş onayı başarısız olduğunda hata mesajı" },
  checkoutSubmit: { testId: "checkout-submit", role: "button", name: "Siparişi onayla", intent: "Siparişi onaylayan buton" },
} as const;
