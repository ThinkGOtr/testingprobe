// Mock ajan adımları için hafif "ekran görüntüsü": Bayi Sipariş Portalı'nın şematik SVG'si,
// hedef eleman vurgulanmış. Yalnızca örnek veri; gerçek görüntüler core-worker'dan gelir.

type Sayfa = "login" | "catalog" | "cart" | "confirmation";

function kacis(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const URUNLER = [
  ["P-001", "Portakal Gazozu 1L", "25,00 TL"],
  ["P-002", "Limonata 330ml", "15,00 TL"],
  ["P-003", "Maden Suyu 200ml", "8,00 TL"],
  ["P-004", "Şeftalili Soğuk Çay 1L", "30,00 TL"],
] as const;

export function ekranGoruntusu(sayfa: Sayfa, vurgu: string, sepet = 0): string {
  const parcalar: string[] = [];
  const kutu = (x: number, y: number, w: number, h: number, id: string, metin: string, dolgu = "#ffffff") => {
    const vurgulu = id === vurgu;
    parcalar.push(
      `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="6" fill="${dolgu}" stroke="${vurgulu ? "#d9480f" : "#c9ced8"}" stroke-width="${vurgulu ? 3 : 1}"/>`,
      `<text x="${x + 10}" y="${y + h / 2 + 5}" font-size="13" fill="#1c2230">${kacis(metin)}</text>`,
    );
    if (vurgulu) {
      parcalar.push(
        `<text x="${x}" y="${y + h + 13}" font-size="11" fill="#d9480f" font-family="monospace">${kacis(`data-testid="${id}"`)}</text>`,
      );
    }
  };

  parcalar.push(`<rect width="640" height="400" fill="#f4f5f7"/>`);
  parcalar.push(`<rect width="640" height="44" fill="#14365d"/>`);
  parcalar.push(`<text x="16" y="28" font-size="15" fill="#fff" font-weight="600">Bayi Sipariş Portalı</text>`);

  if (sayfa !== "login") {
    parcalar.push(`<text x="380" y="28" font-size="13" fill="#dbe4f0">Katalog   Sepet (${sepet})   Siparişler</text>`);
  }

  if (sayfa === "login") {
    parcalar.push(`<text x="220" y="100" font-size="18" fill="#1c2230" font-weight="600">Bayi girişi</text>`);
    kutu(220, 120, 200, 36, "login-username", "bayi1");
    kutu(220, 170, 200, 36, "login-password", "••••••••");
    kutu(220, 222, 200, 36, "login-submit", "Giriş yap", "#e7eefb");
  } else if (sayfa === "catalog") {
    URUNLER.forEach(([kod, ad, fiyat], i) => {
      const x = 20 + (i % 2) * 310;
      const y = 64 + Math.floor(i / 2) * 160;
      parcalar.push(`<rect x="${x}" y="${y}" width="290" height="140" rx="8" fill="#fff" stroke="#dde1e8"/>`);
      parcalar.push(`<text x="${x + 14}" y="${y + 28}" font-size="14" fill="#1c2230" font-weight="600">${kacis(ad)}</text>`);
      parcalar.push(`<text x="${x + 14}" y="${y + 50}" font-size="12" fill="#5d6677">${kod} · ${fiyat}${kod === "P-001" ? " · 6 al 1 bedava" : ""}</text>`);
      kutu(x + 14, y + 64, 80, 30, `qty-input-${kod}`, kod === "P-001" && sepet > 0 ? String(sepet) : "1");
      kutu(x + 110, y + 64, 160, 30, kod === "P-001" ? "add-to-cart" : `add-to-cart-${kod}`, "Sepete ekle", "#e7eefb");
    });
  } else if (sayfa === "cart") {
    parcalar.push(`<text x="20" y="80" font-size="18" fill="#1c2230" font-weight="600">Sepet</text>`);
    // demo-app kampanya kodu: bedava = adet // 6 (campaign.py), P-001 birim fiyatı 25,00 TL.
    const adet = Math.max(1, sepet);
    const bedava = Math.floor(adet / 6);
    const tl = (n: number) => `${n.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} TL`;
    kutu(20, 96, 600, 36, "cart-line-P-001", `Portakal Gazozu 1L   × ${adet}${bedava ? `   (${bedava} bedava)` : ""}`);
    kutu(330, 150, 290, 30, "cart-subtotal", `Ara toplam: ${tl(25 * adet)}`);
    kutu(330, 188, 290, 30, "cart-discount", `İndirim: ${tl(25 * bedava)}`);
    kutu(330, 226, 290, 30, "cart-total", `Toplam: ${tl(25 * (adet - bedava))}`);
    kutu(330, 280, 290, 36, "checkout-submit", "Siparişi onayla", "#e7eefb");
  } else {
    kutu(120, 120, 400, 60, "order-confirmation", "Siparişiniz alındı");
    kutu(120, 200, 400, 36, "order-number", "Sipariş no: SP-2026-0042");
  }

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="400" viewBox="0 0 640 400" font-family="system-ui, sans-serif">${parcalar.join("")}</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

/**
 * 009: uygulama ekranı (app-mcp `app_screenshot`) — Bayi Sipariş uygulamasının şematik SVG'si.
 * Android/iOS dikey telefon (360×740), Windows yatay masaüstü penceresi (800×500). Hedef eleman
 * kimliğiyle (AutomationId / resource-id / accessibilityIdentifier) vurgulanır. Yalnızca örnek veri.
 */
export function uygulamaEkranGoruntusu(platform: "android" | "ios" | "windows", sayfa: Sayfa, vurgu: string, sepet = 0): string {
  const masaustu = platform === "windows";
  const G = masaustu ? 800 : 360;
  const Y = masaustu ? 500 : 740;
  const p: string[] = [];
  const kutu = (x: number, y: number, w: number, h: number, id: string, metin: string, dolgu = "#ffffff") => {
    const vurgulu = id === vurgu;
    p.push(
      `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${masaustu ? 4 : 10}" fill="${dolgu}" stroke="${vurgulu ? "#d9480f" : "#c9ced8"}" stroke-width="${vurgulu ? 3 : 1}"/>`,
      `<text x="${x + 12}" y="${y + h / 2 + 5}" font-size="14" fill="#1c2230">${kacis(metin)}</text>`,
    );
    if (vurgulu) p.push(`<text x="${x}" y="${y + h + 14}" font-size="11" fill="#d9480f" font-family="monospace">${kacis(`id="${id}"`)}</text>`);
  };
  p.push(`<rect width="${G}" height="${Y}" fill="#f4f5f7"/>`);
  if (masaustu) {
    p.push(`<rect width="${G}" height="32" fill="#e9ecf2"/>`, `<text x="12" y="21" font-size="13" fill="#1c2230">Bayi Sipariş — Windows</text>`);
    p.push(`<rect y="32" width="${G}" height="40" fill="#14365d"/>`, `<text x="16" y="58" font-size="15" fill="#fff" font-weight="600">Bayi Sipariş</text>`);
  } else {
    // Durum çubuğu + uygulama başlığı.
    p.push(`<rect width="${G}" height="28" fill="#0f2a4a"/>`, `<text x="16" y="19" font-size="12" fill="#dbe4f0">09:41</text>`);
    p.push(`<rect y="28" width="${G}" height="52" fill="#14365d"/>`, `<text x="16" y="61" font-size="17" fill="#fff" font-weight="600">Bayi Sipariş</text>`);
    if (sayfa !== "login") p.push(`<text x="${G - 96}" y="61" font-size="13" fill="#dbe4f0">Sepet (${sepet})</text>`);
  }
  const ust = masaustu ? 96 : 104;
  const genis = masaustu ? 360 : G - 40;
  const sol = masaustu ? 220 : 20;
  if (sayfa === "login") {
    p.push(`<text x="${sol}" y="${ust + 20}" font-size="18" fill="#1c2230" font-weight="600">Bayi girişi</text>`);
    kutu(sol, ust + 40, genis, 44, "login-username", "bayi1");
    kutu(sol, ust + 100, genis, 44, "login-password", "••••••••");
    kutu(sol, ust + 164, genis, 48, "login-submit", "Giriş yap", "#e7eefb");
  } else if (sayfa === "catalog") {
    URUNLER.slice(0, masaustu ? 4 : 3).forEach(([kod, ad, fiyat], i) => {
      const x = masaustu ? 20 + (i % 2) * 390 : 20;
      const y = masaustu ? ust + Math.floor(i / 2) * 170 : ust + i * 196;
      const w = masaustu ? 370 : G - 40;
      p.push(`<rect x="${x}" y="${y}" width="${w}" height="${masaustu ? 150 : 180}" rx="10" fill="#fff" stroke="#dde1e8"/>`);
      p.push(`<text x="${x + 14}" y="${y + 28}" font-size="15" fill="#1c2230" font-weight="600">${kacis(ad)}</text>`);
      p.push(`<text x="${x + 14}" y="${y + 50}" font-size="12" fill="#5d6677">${kod} · ${fiyat}${kod === "P-001" ? " · 6 al 1 bedava" : ""}</text>`);
      kutu(x + 14, y + 68, 90, 40, `qty-input-${kod}`, kod === "P-001" && sepet > 0 ? String(sepet) : "1");
      kutu(x + 120, y + 68, w - 134, 40, kod === "P-001" ? "add-to-cart-P-001" : `add-to-cart-${kod}`, "Sepete ekle", "#e7eefb");
    });
  } else if (sayfa === "cart") {
    const adet = Math.max(1, sepet);
    const bedava = Math.floor(adet / 6);
    const tl = (n: number) => `${n.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} TL`;
    p.push(`<text x="20" y="${ust + 20}" font-size="18" fill="#1c2230" font-weight="600">Sepet</text>`);
    const w = masaustu ? 760 : G - 40;
    kutu(20, ust + 36, w, 48, "cart-line-P-001", `Portakal Gazozu × ${adet}${bedava ? ` (${bedava} bedava)` : ""}`);
    kutu(20, ust + 100, w, 40, "cart-subtotal", `Ara toplam: ${tl(25 * adet)}`);
    kutu(20, ust + 152, w, 40, "cart-discount", `İndirim: ${tl(25 * bedava)}`);
    kutu(20, ust + 204, w, 40, "cart-total", `Toplam: ${tl(25 * (adet - bedava))}`);
    kutu(20, ust + 268, w, 48, "checkout-submit", "Siparişi onayla", "#e7eefb");
  } else {
    kutu(20, ust + 40, masaustu ? 760 : G - 40, 60, "order-confirmation", "Siparişiniz alındı");
  }
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${G}" height="${Y}" viewBox="0 0 ${G} ${Y}" font-family="system-ui, sans-serif">${p.join("")}</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
