// Proje özellikleri (merkezi yapılandırma, `/auth/me` → `ozellikler`, `organizasyon`, `proje`): kapalı
// platform seçicilerde sunulmaz, `ai_agent` kapalıysa Agent Probe bölümleri gizlenir, üst çubukta
// "Organizasyon · Proje" görünür. Alan yoksa (varsayılan kip) davranış bugünküyle aynıdır.
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { OZELLIK_KAPALI, yapilandir } from "../api/http";
import type { Kullanici } from "../api/types";
import { acikPlatformlar, OturumProvider, ozellikAcik } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { oturumAc } from "../test/yardimci";
import { ACIK_PLATFORM_YOK } from "./Kod";

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

const T = { timeout: 20000 };
const HEPSI = { web: true, android: true, ios: true, windows: true, ai_agent: true };

/** Mock oturumu açar ve `/auth/me` yanıtına proje alanlarını ekler. */
async function oturum(kullanici: string, ek: Partial<Kullanici> = {}) {
  await oturumAc(kullanici);
  const k = await api.me();
  vi.spyOn(api, "me").mockResolvedValue({ ...k, ...ek });
}

const radyolar = (grup: HTMLElement) => within(grup).getAllByRole("radio").map((r) => r.getAttribute("value"));

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("özellik kuralları", () => {
  it("alan yoksa hepsi açık; varsa eksik anahtar kapalı (fail-closed)", () => {
    expect(ozellikAcik({}, "android")).toBe(true);
    expect(ozellikAcik({ ozellikler: null }, "ai_agent")).toBe(true);
    expect(acikPlatformlar({})).toEqual(["web", "android", "ios", "windows"]);
    expect(ozellikAcik({ ozellikler: { web: true } }, "android")).toBe(false);
    expect(ozellikAcik({ ozellikler: { web: true } }, "ai_agent")).toBe(false);
    expect(acikPlatformlar({ ozellikler: { ios: true, web: true } })).toEqual(["web", "ios"]);
  });

  it("core 409 `ozellik_kapali` dostu Türkçe metne çevrilir", async () => {
    yapilandir({ mockZorunlu: false });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() =>
        Promise.resolve(new Response(JSON.stringify({ detail: "platform android disabled", kod: "ozellik_kapali" }), { status: 409, headers: { "Content-Type": "application/json" } })),
      ),
    );
    await expect(api.kodUret(["c1"], "android")).rejects.toMatchObject({ status: 409, kod: "ozellik_kapali", detail: OZELLIK_KAPALI });
  });
});

describe("Kod üretimi: proje platformları", { timeout: 60000 }, () => {
  it("ozellikler yoksa dört platform sunulur", async () => {
    await oturum("muhendis");
    uygulama("/kod");
    const grup = await screen.findByRole("group", { name: "Hedef platform" }, T);
    expect(radyolar(grup)).toEqual(["web", "android", "ios", "windows"]);
  });

  it("android=false: Android sunulmaz; web kapalıysa ilk açık platform seçili", async () => {
    await oturum("muhendis", { ozellikler: { ...HEPSI, android: false } });
    const { unmount } = uygulama("/kod");
    const grup = await screen.findByRole("group", { name: "Hedef platform" }, T);
    expect(radyolar(grup)).toEqual(["web", "ios", "windows"]);
    unmount();
    vi.restoreAllMocks();

    await oturum("muhendis", { ozellikler: { ios: true, windows: true } });
    uygulama("/kod");
    const grup2 = await screen.findByRole("group", { name: "Hedef platform" }, T);
    expect(radyolar(grup2)).toEqual(["ios", "windows"]);
    expect(within(grup2).getByRole("radio", { name: /^iOS/ })).toBeChecked();
  });

  it("hiç açık platform yoksa form yerine bilgi, üretim düğmesi pasif", async () => {
    await oturum("muhendis", { ozellikler: { ai_agent: true } });
    uygulama("/kod");
    expect(await screen.findByTestId("acik-platform-yok", undefined, T)).toHaveTextContent(ACIK_PLATFORM_YOK);
    expect(screen.queryByRole("group", { name: "Hedef platform" })).toBeNull();
    expect(screen.getByRole("button", { name: /^Seçilenler için kod üret/ })).toBeDisabled();
  });
});

describe("Kontrol Kulesi: platform süzgeci", { timeout: 60000 }, () => {
  it("yalnız açık platformlar (Tümü kalır); ekilmiş hata koşusu formu da", async () => {
    await oturum("sunucu", { ozellikler: { ...HEPSI, windows: false, android: false } });
    uygulama("/kontrol-kulesi");
    const grup = await screen.findByRole("group", { name: "Platform" }, T);
    expect(radyolar(grup)).toEqual(["tumu", "web", "ios"]);
    await waitFor(() => expect(screen.getByTestId("hk-platform-web")).toBeInTheDocument(), T);
    expect(screen.queryByTestId("hk-platform-android")).toBeNull();
    expect(screen.queryByTestId("hk-platform-windows")).toBeNull();
    expect(screen.getByTestId("hk-platform-ios")).toBeInTheDocument();
  });
});

describe("ai_agent: Agent Probe bölümleri", { timeout: 60000 }, () => {
  it("varsayılan kipte menüde Ajan ürünleri ve gereksinim detayında panel var", async () => {
    await oturum("analist");
    uygulama("/gereksinimler/req-ft-1");
    const menu = await screen.findByRole("navigation", { name: "Ana menü" }, T);
    expect(within(menu).getByRole("link", { name: /Ajan ürünleri/ })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Ürün AI ajanı" }, T)).toBeInTheDocument();
  });

  it("ai_agent=false: menü öğesi yok, sayfa 'erişim yok', gereksinim detayında panel ve gezgin girdisi yok", async () => {
    await oturum("analist", { ozellikler: { ...HEPSI, ai_agent: false } });
    const casus = vi.spyOn(api, "ajanTesti");
    const { unmount } = uygulama("/ajan-urunleri");
    expect(await screen.findByText("Bu ekran bu projede kapalı.", undefined, T)).toBeInTheDocument();
    const menu = screen.getByRole("navigation", { name: "Ana menü" });
    expect(within(menu).queryByRole("link", { name: /Ajan ürünleri/ })).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    unmount();

    uygulama("/gereksinimler/req-ft-1");
    await screen.findByRole("heading", { name: "Doküman" }, T);
    expect(screen.queryByRole("heading", { name: "Ürün AI ajanı" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Ürün AI ajanı" })).toBeNull();
    expect(casus).not.toHaveBeenCalled();
  });
});

describe("üst çubuk: organizasyon · proje", { timeout: 60000 }, () => {
  it("alanlar varsa 'Örnek Org · Örnek Proje' gösterilir", async () => {
    await oturum("muhendis", { organizasyon: { id: "o1", ad: "Örnek Org" }, proje: { id: "p1", ad: "Örnek Proje", kod: "OP" } });
    uygulama("/kosular");
    const b = await screen.findByRole("group", { name: "Organizasyon ve proje" }, T);
    expect(b).toHaveTextContent(/^Örnek Org · Örnek Proje$/);
  });

  it("alanlar yoksa hiçbir şey çizilmez", async () => {
    await oturum("muhendis");
    uygulama("/kosular");
    await screen.findByRole("navigation", { name: "Ana menü" }, T);
    expect(screen.queryByTestId("proje-baglami")).toBeNull();
    expect(screen.queryByRole("group", { name: "Organizasyon ve proje" })).toBeNull();
  });
});
