// Ortak üst menü locator'ları — saf veri. Uygulamada data-testid değişirse yalnızca testId değişir.
export const nav = {
  catalog: { testId: "nav-catalog", role: "link", name: "Katalog", intent: "Üst menüde ürün kataloğuna giden bağlantı" },
  cart: { testId: "nav-cart", role: "link", name: "Sepet", intent: "Üst menüde sepete giden bağlantı (sepet sayacını içerir)" },
  cartCount: { testId: "cart-count", role: "generic", name: "", intent: "Sepetteki toplam ürün adedini gösteren sayaç" },
  orders: { testId: "nav-orders", role: "link", name: "Siparişlerim", intent: "Üst menüde sipariş geçmişine giden bağlantı" },
  logout: { testId: "nav-logout", role: "button", name: "Çıkış yap", intent: "Oturumu kapatan buton" },
  currentDealer: { testId: "current-dealer", role: "generic", name: "", intent: "Oturum açmış bayinin adı" },
} as const;
