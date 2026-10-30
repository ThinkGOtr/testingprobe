// Sipariş onayı ve sipariş geçmişi locator'ları — saf veri. Sonu `-` ile biten testId'ler önektir: sipariş numarası eklenir (order-row-SP-000001).
export const order = {
  confirmation: { testId: "order-confirmation", role: "region", name: "Siparişiniz alındı", intent: "Sipariş onaylandıktan sonra gösterilen onay alanı" },
  orderNumber: { testId: "order-number", role: "strong", name: "", intent: "Onay alanındaki sipariş numarası" },
  orderTotal: { testId: "order-total", role: "definition", name: "", intent: "Onaylanan siparişin genel toplamı" },
  ordersTable: { testId: "orders-table", role: "table", name: "Sipariş geçmişi", intent: "Sipariş geçmişi tablosu" },
  ordersEmpty: { testId: "orders-empty", role: "generic", name: "", intent: "Hiç sipariş yokken gösterilen bilgi alanı" },
  orderRow: { testId: "order-row-", role: "row", name: "", intent: "Sipariş geçmişinde bir siparişin satırı" },
  orderRowTotal: { testId: "order-total-", role: "cell", name: "", intent: "Sipariş geçmişi satırındaki genel toplam" },
} as const;
