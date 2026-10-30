import { useState } from "react";

type ApiStatus = "bilinmiyor" | "kontrol ediliyor" | "çalışıyor" | "erişilemiyor";

// F0 iskeleti: yalnızca yer tutucu sayfa. Giriş, katalog, sepet ve sipariş akışları F1'de gelir.
// Kural: her etkileşimli elemanda data-testid bulunur (locator'lar e2e/pages/**/locators.ts içinde).
export function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("bilinmiyor");

  async function checkApi() {
    setApiStatus("kontrol ediliyor");
    try {
      const resp = await fetch("/api/health");
      setApiStatus(resp.ok ? "çalışıyor" : "erişilemiyor");
    } catch {
      setApiStatus("erişilemiyor");
    }
  }

  return (
    <main className="page" data-testid="home-page">
      <h1 data-testid="home-title">Bayi Sipariş Portalı</h1>
      <p data-testid="home-subtitle">
        Örnek uygulama iskeleti. Giriş, katalog, sepet ve sipariş ekranları yakında eklenecek.
      </p>
      <section aria-labelledby="api-status-heading">
        <h2 id="api-status-heading">Sistem durumu</h2>
        <button type="button" data-testid="home-check-api" onClick={checkApi}>
          API durumunu kontrol et
        </button>
        <p role="status" aria-live="polite" data-testid="home-api-status">
          API: {apiStatus}
        </p>
      </section>
    </main>
  );
}
