// Test ortamları: tetik seçicisi, koşu rozeti ve süzgeci, koşu detayı, Kontrol Kulesi süzgeci, canlı ortam
// koruması (kırarak doğrulama ve demo düğmeleri pasif; sunucu 409 detayı gösterilir), uyum katmanı ve i18n.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ayar, mockTestOrtamlari, mockVerisi } from "../api/mock/handlers";
import type { Ortam } from "../api/types";
import { ortamlarUyarla, testOrtamiUyarla } from "../api/uyumOrtam";
import { kontrolKulesiUyarla, kosuUyarla } from "../api/uyumDemoB";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { canliOrtamEngeli, ortamMetni, ortamTuruEtiketi } from "../lib/ortam";
import { ApiError } from "../api/http";
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

const STAGING: Ortam = { eid: "a1b2c3d4e5f6", ad: "Staging", tur: "staging", varsayilan: true, canli: false };
const CANLI: Ortam = { eid: "f6e5d4c3b2a1", ad: "Üretim", tur: "prod", varsayilan: false, canli: true };

function ortamlariKur(varsayilan: Ortam = STAGING) {
  mockTestOrtamlari.ortamlar = [STAGING, CANLI].map((o) => ({ ...o, varsayilan: o.eid === varsayilan.eid }));
  mockTestOrtamlari.varsayilan_eid = varsayilan.eid;
}

beforeEach(() => {
  ayar.isAdimiMs = 0;
});
afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.lang = "";
});

describe("uyum katmanı", () => {
  it("test_ortami yoksa null; prod her zaman canlı; bilinmeyen tür test", () => {
    expect(testOrtamiUyarla(undefined)).toBeNull();
    expect(testOrtamiUyarla({ ad: "x" })).toBeNull();
    expect(testOrtamiUyarla({ eid: "e1", ad: "P", tur: "prod" })).toEqual({ eid: "e1", ad: "P", tur: "prod", canli: true });
    expect(testOrtamiUyarla({ eid: "e2", tur: "garip" })).toEqual({ eid: "e2", ad: "e2", tur: "test", canli: false });
    expect(kosuUyarla({ id: "r1" }).test_ortami).toBeNull();
    expect(kosuUyarla({ id: "r1", test_ortami: { eid: "e1", ad: "S", tur: "staging", canli: false } }).test_ortami).toMatchObject({ ad: "S" });
    // Ham `ortam` JSON alanı test ortamı sayılmaz.
    expect(kosuUyarla({ id: "r1", ortam: { eid: "x", ad: "y" } }).test_ortami).toBeNull();
    expect(kontrolKulesiUyarla({ ortam_suzgeci: "e1" }).ortam_suzgeci).toBe("e1");
    expect(kontrolKulesiUyarla({}).ortam_suzgeci).toBeNull();
  });

  it("ortam listesi: varsayılan işareti ve eksik gövde", () => {
    expect(ortamlarUyarla(null)).toEqual({ ortamlar: [], varsayilan_eid: null });
    const o = ortamlarUyarla({ ortamlar: [{ eid: "a", ad: "A", tur: "dev" }, { eid: "b", ad: "B", tur: "test", varsayilan: true }] });
    expect(o.varsayilan_eid).toBe("b");
    expect(o.ortamlar.map((x) => x.varsayilan)).toEqual([false, true]);
  });

  it("i18n: <html lang> İngilizceyse EN metin ve tür etiketi", () => {
    expect(ortamTuruEtiketi("prod")).toBe("Canlı");
    expect(ortamMetni("canliUyari")).toBe("Canlı ortam: koşu yalnız okuma amaçlıdır; veriyi değiştiren işlemler kapalıdır.");
    document.documentElement.lang = "en";
    expect(ortamTuruEtiketi("prod")).toBe("Production");
    expect(ortamMetni("geceNotu")).toBe("The nightly run uses the default environment.");
  });

  it("canlı ortam engeli 409 gövdesinden tanınır", () => {
    expect(canliOrtamEngeli(new ApiError(409, "x", { govde: { engel: "canli_ortam" } }))).toBe(true);
    expect(canliOrtamEngeli(new ApiError(409, "x"))).toBe(false);
  });
});

describe("istemci gövdesi ve sorgusu", () => {
  it("ortam verilmezse gövdede yok; verilirse var; koşu ve kule süzgeci sorguda", async () => {
    const { yapilandir } = await import("../api/http");
    yapilandir({ mockZorunlu: false, mockOtomatik: false });
    const f = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify({ job_id: "j", durum: "queued" }), { status: 200, headers: { "Content-Type": "application/json" } })),
    );
    vi.stubGlobal("fetch", f);
    const govde = () => JSON.parse((f.mock.calls[0][1] as RequestInit).body as string);
    await api.ciTetikle("manual");
    expect(govde()).toEqual({ tetik: "manual" });
    f.mockClear();
    await api.ciTetikle("deploy", "a1b2c3d4e5f6");
    expect(govde()).toEqual({ tetik: "deploy", ortam: "a1b2c3d4e5f6" });
    f.mockClear();
    await api.kosular("-").catch(() => undefined);
    expect(f.mock.calls[0][0]).toBe("/api/runs?ortam=-");
    f.mockClear();
    await api.kontrolKulesi("a1b2c3d4e5f6").catch(() => undefined);
    expect(f.mock.calls[0][0]).toBe("/api/control-tower?ortam=a1b2c3d4e5f6");
    f.mockClear();
    await api.ortamlar().catch(() => undefined);
    expect(f.mock.calls[0][0]).toBe("/api/environments");
    vi.unstubAllGlobals();
  });
});

describe("Koşular: tetik ortamı", () => {
  it("projede ortam yoksa seçici ve süzgeç yok, istek ortamsız", async () => {
    await oturumAc("muhendis");
    const tetik = vi.spyOn(api, "ciTetikle");
    const u = userEvent.setup();
    uygulama("/kosular");
    await screen.findByRole("group", { name: "Koşu süzgeci" });
    expect(screen.queryByTestId("ortam-secici")).toBeNull();
    expect(screen.queryByTestId("ortam-suzgeci")).toBeNull();
    await u.click(screen.getByRole("button", { name: "Manuel koşu başlat" }));
    await waitFor(() => expect(tetik).toHaveBeenCalled());
    expect(tetik.mock.calls[0]).toEqual(["manual"]);
  });

  it("varsayılan ortam seçili gelir, seçilen ortam gövdede gider, canlıda uyarı, gece notu", async () => {
    ortamlariKur();
    await oturumAc("muhendis");
    const tetik = vi.spyOn(api, "ciTetikle");
    const u = userEvent.setup();
    uygulama("/kosular");
    const secici = await screen.findByTestId("ortam-secici");
    const select = within(secici).getByRole("combobox", { name: "Koşunun ortamı" });
    expect(select).toHaveValue(STAGING.eid);
    expect(within(secici).getByRole("option", { name: "Üretim (Canlı)" })).toBeInTheDocument();
    expect(secici).toHaveTextContent("Gece koşusu varsayılan ortamda çalışır.");
    expect(screen.queryByTestId("canli-ortam-uyarisi")).toBeNull();

    await u.click(screen.getByRole("button", { name: "Deploy sonrası testleri koş" }));
    await waitFor(() => expect(tetik).toHaveBeenCalledWith("deploy", STAGING.eid));

    await u.selectOptions(select, CANLI.eid);
    expect(screen.getByTestId("canli-ortam-uyarisi")).toHaveTextContent("Canlı ortam: koşu yalnız okuma amaçlıdır; veriyi değiştiren işlemler kapalıdır.");
    await u.click(screen.getByRole("button", { name: "Manuel koşu başlat" }));
    await waitFor(() => expect(tetik).toHaveBeenCalledWith("manual", CANLI.eid));
    // Gece koşusu varsayılan ortamda: ortam gönderilmez.
    await u.click(screen.getByRole("button", { name: "Gece koşusunu şimdi başlat" }));
    await waitFor(() => expect(tetik).toHaveBeenCalledWith("nightly"));
    // Mock core koşuya ortamı yazar; tabloda rozet olarak görünür (canlı uyarı tonunda).
    await waitFor(() => expect(screen.getAllByTestId("ortam-rozeti").some((r) => r.dataset.canli === "true")).toBe(true));
    expect(mockVerisi().kosular.some((k) => k.test_ortami?.eid === CANLI.eid)).toBe(true);
  });
});

describe("Koşular: rozet ve süzgeç", () => {
  it("ortam süzgeci `?ortam=` ile sunucuya gider; Ortamsız seçeneği", async () => {
    ortamlariKur();
    const v = mockVerisi();
    v.kosular[0].test_ortami = { eid: STAGING.eid, ad: STAGING.ad, tur: STAGING.tur, canli: false };
    await oturumAc("muhendis");
    const liste = vi.spyOn(api, "kosular");
    const u = userEvent.setup();
    uygulama("/kosular");
    const suzgec = await screen.findByTestId("ortam-suzgeci");
    expect(within(suzgec).getByRole("option", { name: "Ortamsız" })).toBeInTheDocument();
    expect(await screen.findAllByTestId("ortam-rozeti")).toHaveLength(1);
    await u.selectOptions(suzgec, STAGING.eid);
    await waitFor(() => expect(liste).toHaveBeenLastCalledWith(STAGING.eid));
    expect(await screen.findByText("1/1 koşu")).toBeInTheDocument();
    await u.selectOptions(screen.getByTestId("ortam-suzgeci"), "-");
    await waitFor(() => expect(liste).toHaveBeenLastCalledWith("-"));
    await waitFor(() => expect(screen.queryAllByTestId("ortam-rozeti")).toHaveLength(0));
  });

  it("koşu detayı başlığında ortam rozeti", async () => {
    const v = mockVerisi();
    const k = v.kosular[0];
    k.test_ortami = { eid: CANLI.eid, ad: CANLI.ad, tur: "prod", canli: true };
    await oturumAc("muhendis");
    uygulama(`/kosular/${k.id}`);
    const r = await screen.findByTestId("ortam-rozeti");
    expect(r).toHaveTextContent("Üretim");
    expect(r.closest(".cip")).toHaveClass("cip-uyari");
  });
});

describe("Kontrol Kulesi: ortam süzgeci", () => {
  it("seçim `?ortam=` ile istenir ve ipucu görünür; ortam yoksa süzgeç yok", async () => {
    await oturumAc("muhendis");
    const kule = vi.spyOn(api, "kontrolKulesi");
    const ilk = uygulama("/kontrol-kulesi");
    await screen.findByTestId("kule-platform");
    expect(screen.queryByTestId("kule-ortam")).toBeNull();
    ilk.unmount();

    ortamlariKur();
    const u = userEvent.setup();
    uygulama("/kontrol-kulesi");
    const s = await screen.findByTestId("ortam-suzgeci");
    expect(within(s).queryByRole("option", { name: "Ortamsız" })).toBeNull();
    await u.selectOptions(s, STAGING.eid);
    await waitFor(() => expect(kule).toHaveBeenLastCalledWith(STAGING.eid));
    expect(await screen.findByText(ortamMetni("kuleIpucu"))).toBeInTheDocument();
  });
});

describe("canlı ortam koruması", () => {
  it("varsayılan ortam canlıysa kırarak doğrulama pasif ve nedeni yazılı", async () => {
    ortamlariKur(CANLI);
    await oturumAc("muhendis");
    uygulama("/kod/scr-2");
    expect(await screen.findByTestId("kirma-canli-ortam")).toHaveTextContent(ortamMetni("canliKapali"));
    const kart = document.getElementById("kirarak-dogrula")!;
    const dugme = within(kart).getByRole("button", { name: /doğrula$/ });
    expect(dugme).toBeDisabled();
    expect(dugme).toHaveAttribute("title", ortamMetni("canliKapali"));
  });

  it("canlı olmayan varsayılanda düğme açık; sunucu 409 canlı engeli detayı gösterilir", async () => {
    ortamlariKur(STAGING);
    await oturumAc("muhendis");
    vi.spyOn(api, "kirarakDogrula").mockRejectedValue(
      new ApiError(409, "Canlı ortamda kırarak doğrulama kapalı", { kod: "cakisma", govde: { engel: "canli_ortam" } }),
    );
    const u = userEvent.setup();
    uygulama("/kod/scr-2");
    await screen.findByRole("heading", { level: 1 });
    const kart = await waitFor(() => document.getElementById("kirarak-dogrula")!);
    expect(screen.queryByTestId("kirma-canli-ortam")).toBeNull();
    const dugme = within(kart).getByRole("button", { name: /doğrula$/ });
    expect(dugme).toBeEnabled();
    await u.click(dugme);
    expect((await screen.findAllByText(/Canlı ortamda kırarak doğrulama kapalı/)).length).toBeGreaterThan(0);
  });

  it("demo kırma ve sıfırlama düğmeleri canlıda pasif; mock core 409 döner", async () => {
    ortamlariKur(CANLI);
    await oturumAc("sunucu");
    uygulama("/demo");
    expect(await screen.findByTestId("demo-canli-ortam")).toHaveTextContent(ortamMetni("canliKapali"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Demo'yu sıfırla" })).toBeDisabled());
    expect(screen.getByRole("button", { name: ortamMetni("canliKapaliBaslik") })).toBeDisabled();
    await expect(api.demoKir()).rejects.toMatchObject({ status: 409, detail: "Canlı ortamda demo kırma kapalı" });
    await expect(api.demoSifirla()).rejects.toMatchObject({ status: 409 });
    await oturumAc("muhendis");
    await expect(api.kirarakDogrula("scr-2")).rejects.toSatisfy((e: unknown) => canliOrtamEngeli(e));
  });
});
