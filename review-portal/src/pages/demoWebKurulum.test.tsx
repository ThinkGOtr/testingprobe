// Kırma sonrası demo uygulamasının yeniden kurulumu (~3 dk): normal süre içinde (izleyici kalp
// atışı taze ya da bilinmiyor) nötr "yeniden kuruluyor"; uyarı yalnız gerçek sorunda (toplam
// bekleme > 10 dk ya da izleyici kalp atışı yok).
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ayar } from "../api/mock/handlers";
import type { DemoDurumu } from "../api/types";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { oturumAc } from "../test/yardimci";

function uygulama(yol: string) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          <Rotalar />
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

const UYARI = "Demo uygulaması hâlâ yeniden kurulmadı";

function kirik(onceMs: number, izleyici?: DemoDurumu["web_izleyici"]): DemoDurumu {
  return {
    forge: { main: "21b36dec00001111", testid: "cart-add", baseline: "aaaa", main_baseline_mi: false },
    locator_durumu: "kirik",
    uygulama: { sha: "94683fc000001111", main_ile_eslesiyor: false },
    web_yenileme_istegi: { istek_id: "i1", eylem: "break", sha: "21b36dec0000", zaman: new Date(Date.now() - onceMs).toISOString(), isteyen: "sunucu" },
    web_izleyici: izleyici,
  };
}

beforeEach(() => {
  ayar.isAdimiMs = 0;
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("kırma sonrası demo uygulaması yeniden kurulumu", () => {
  async function ac(d: DemoDurumu) {
    await oturumAc("sunucu");
    vi.spyOn(api, "demoDurumu").mockResolvedValue(d);
    vi.spyOn(api, "kosular").mockResolvedValue([]);
    uygulama("/demo");
    await screen.findByRole("list", { name: "Locator kırılması ilerlemesi" });
  }

  it("izleyici canlı, 1 dk: nötr 'yeniden kuruluyor', uyarı yok", async () => {
    await ac(kirik(60_000, { calisiyor: true, yas_s: 5 }));
    expect(await screen.findByTestId("web-kuruluyor")).toHaveTextContent("Demo uygulaması yeniden kuruluyor (yaklaşık 3 dk)");
    expect(screen.queryByText(UYARI)).toBeNull();
  });

  it("izleyici bilgisi yok (core bildirmiyor), 2 dk: yine nötr", async () => {
    await ac(kirik(120_000));
    expect(await screen.findByTestId("web-kuruluyor")).toBeInTheDocument();
    expect(screen.queryByText(UYARI)).toBeNull();
  });

  it("toplam bekleme 10 dk'yı aştı: mevcut uyarı (host komutu)", async () => {
    await ac(kirik(11 * 60_000, { calisiyor: true, yas_s: 5 }));
    expect(await screen.findByText(UYARI)).toBeInTheDocument();
    expect(screen.queryByTestId("web-kuruluyor")).toBeNull();
  });

  it("izleyici kalp atışı yok, 30 sn: uyarı", async () => {
    await ac(kirik(30_000, { calisiyor: false, yas_s: null }));
    expect(await screen.findByText(UYARI)).toBeInTheDocument();
    expect(screen.queryByTestId("web-kuruluyor")).toBeNull();
  });
});

// "Demo durumu" kartı da aynı kuralı uygular: normal yeniden kurulumda teknik yönerge yerine nötr metin.
describe("Demo durumu kartı: çalışan uygulama main'den geride", () => {
  const YONERGE = "Demo uygulaması forge main'den yeniden derlenmeli: host'ta `scripts/demo-web-sync.sh` çalıştırın.";
  function durumlu(onceMs: number | null, izleyici?: DemoDurumu["web_izleyici"]): DemoDurumu {
    const d = kirik(onceMs ?? 0, izleyici);
    d.uygulama = { sha: "94683fc000001111", main_ile_eslesiyor: false, neden: "uygulama kodu farklı (web)", yonerge: YONERGE };
    if (onceMs === null) d.web_yenileme_istegi = null;
    return d;
  }
  async function ac(d: DemoDurumu) {
    await oturumAc("sunucu");
    vi.spyOn(api, "demoDurumu").mockResolvedValue(d);
    vi.spyOn(api, "kosular").mockResolvedValue([]);
    uygulama("/demo");
    await screen.findByText("Çalışan uygulama");
  }

  it("izleyici canlı, 1 dk: nötr metin; neden ve yönerge yok; çip rengi aynı", async () => {
    await ac(durumlu(60_000, { calisiyor: true, yas_s: 5 }));
    expect(await screen.findByTestId("durum-web-kuruluyor")).toHaveTextContent("Demo uygulaması yeniden kuruluyor (yaklaşık 3 dk)");
    expect(screen.queryAllByText(/demo-web-sync\.sh/)).toHaveLength(0);
    expect(screen.queryByText("uygulama kodu farklı (web)")).toBeNull();
    expect(screen.getByText("main ile eşleşmiyor")).toBeInTheDocument();
  });

  it("10 dk aşıldı: yönerge", async () => {
    await ac(durumlu(11 * 60_000, { calisiyor: true, yas_s: 5 }));
    expect((await screen.findAllByText(/demo-web-sync\.sh/)).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("durum-web-kuruluyor")).toBeNull();
  });

  it("kalp atışı yok: süre içinde olsa da yönerge", async () => {
    await ac(durumlu(30_000, { calisiyor: false, yas_s: null }));
    expect((await screen.findAllByText(/demo-web-sync\.sh/)).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("durum-web-kuruluyor")).toBeNull();
  });

  it("yenileme isteği yok: yönerge (beklenen yeniden kurulum yok)", async () => {
    await ac(durumlu(null, { calisiyor: true, yas_s: 5 }));
    expect((await screen.findAllByText(/demo-web-sync\.sh/)).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("durum-web-kuruluyor")).toBeNull();
  });
});
