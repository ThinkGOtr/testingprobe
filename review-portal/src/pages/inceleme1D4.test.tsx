// 011 inceleme turu 1, D4 portal düzeltmeleri:
// QA-Y2 Koşular tek dil rozeti · MİM-L6 "Yeniden üret" dil kaynağı · EKR-E4 üretilen testler yığın kipi ·
// QA-O5 Test case'leri → case kartı çapası + Otomasyon sütunu · MİM-Y2 Kontrol Kulesi doğrulanmamış sayacı ·
// K-T8 `/code/languages` 403 → dil seçici sessizce gizli.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ApiError, yapilandir } from "../api/http";
import { capaAyar } from "../lib/capa";
import type { Kosu, Script } from "../api/types";
import { kontrolKulesiUyarla } from "../api/uyumDemoB";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { oturumAc } from "../test/yardimci";
import { KosuTablosu } from "./Kosular";
import { caseScriptleri } from "./TestCaseleri";

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

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("QA-Y2: Koşular tablosunda dil rozeti tek", () => {
  it("platform + dil taşıyan koşu satırında bir dil rozeti ('Java' iki kez yazılmaz)", () => {
    const kosu = {
      id: "run-1",
      tetik: "push",
      kaynak: "local",
      commit: "abc1234",
      pr_no: null,
      durum: "passed",
      baslangic: "2026-11-03T10:00:00Z",
      sure_ms: 1000,
      toplam: 1,
      gecen: 1,
      basarisiz: 0,
      flaky: 0,
      atlanan: 0,
      allure_url: null,
      rapor_url: null,
      sauce_url: null,
      ci_url: null,
      break_campaign: false,
      script_id: null,
      platform: "web",
      dil: "java",
    } as unknown as Kosu;
    render(
      <MemoryRouter>
        <KosuTablosu kosular={[kosu]} />
      </MemoryRouter>,
    );
    const satir = screen.getAllByRole("row")[1];
    expect(within(satir).getAllByTestId("dil-rozeti")).toHaveLength(1);
    expect(within(satir).getByTestId("dil-rozeti")).toHaveTextContent("Java");
  });
});

const OPENAPI = {
  paths: Object.fromEntries(
    ["/auth/me", "/auth/login", "/cases", "/scripts", "/scripts/{script_id}", "/runs", "/events", "/code/generate", "/code/languages"].map((p) => [
      p,
      { get: {}, post: {} },
    ]),
  ),
};

const DILLER = {
  platform: "web",
  algilanan: "ts",
  kaynak: "algilandi",
  sayilar: { ts: 9, java: 4 },
  secenekler: [
    { dil: "ts", etiket: "TypeScript", cati: "Playwright Test", hat: "tam", kullanilabilir: true, neden: null },
    { dil: "java", etiket: "Java", cati: "Playwright for Java + TestNG", hat: "tam", kullanilabilir: true, neden: null },
  ],
};

function bloklu(id: string, baslik: string, caseId: string, dil: string, dil_kaynagi: string) {
  return { id, case_ids: [caseId], baslik, durum: "blocked", platform: "web", dil, dil_kaynagi, pr: null, dosya_yolu: `e2e/${caseId}.spec.ts`, mode: "replay" };
}

type Cagri = { url: string; method: string; govde: unknown };

function sahteCore(ek: Record<string, { status?: number; govde: unknown }>, cagrilar: Cagri[]) {
  return vi.fn().mockImplementation((url: string, init?: RequestInit) => {
    const j = (status: number, govde: unknown) => Promise.resolve(new Response(JSON.stringify(govde), { status, headers: { "Content-Type": "application/json" } }));
    const method = (init?.method ?? "GET").toUpperCase();
    if (url === "/api/openapi.json") return j(200, OPENAPI);
    if (url === "/api/auth/me") return j(200, { id: "u1", kullanici_adi: "engineer", rol: "engineer" });
    const yol = url.replace(/^\/api/, "").split("?")[0];
    if (method !== "GET") {
      cagrilar.push({ url: yol, method, govde: init?.body ? JSON.parse(String(init.body)) : null });
      return j(202, { job_id: "j1", durum: "queued", mesaj: "Kuyruğa alındı." });
    }
    if (yol in ek) return j(ek[yol].status ?? 200, ek[yol].govde);
    return j(404, { detail: "Not Found" });
  });
}

describe("MİM-L6: Yeniden üret dil kaynağını korur", () => {
  it("elle seçilmiş dil (secildi) gönderilir; algılanan dilde `dil` gönderilmez", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const cagrilar: Cagri[] = [];
    const scriptler = [bloklu("s-elle", "Elle Java", "c-1", "java", "secildi"), bloklu("s-algi", "Algılanan TS", "c-2", "ts", "algilandi")];
    vi.stubGlobal("fetch", sahteCore({ "/scripts": { govde: scriptler }, "/cases": { govde: [] }, "/code/languages": { govde: DILLER } }, cagrilar));
    const u = userEvent.setup();
    uygulama("/kod");
    const tablo = await screen.findByRole("region", { name: "Üretilen testler tablosu" });
    await screen.findByRole("radiogroup", { name: "Dil" }).catch(() => screen.findByText(/repodan algılandı/));
    const satir = (ad: string) => within(tablo).getByRole("link", { name: ad }).closest("tr")!;
    await u.click(within(satir("Elle Java")).getByRole("button", { name: "Yeniden üret" }));
    await waitFor(() => expect(cagrilar).toHaveLength(1));
    expect(cagrilar[0].govde).toEqual({ case_ids: ["c-1"], platform: "web", dil: "java" });
    await u.click(within(satir("Algılanan TS")).getByRole("button", { name: "Yeniden üret" }));
    await waitFor(() => expect(cagrilar).toHaveLength(2));
    expect(cagrilar[1].govde).toEqual({ case_ids: ["c-2"], platform: "web" });
  });
});

describe("K-T8: /code/languages 403", () => {
  it("api.kodDilleri 403'te null döner (uç yok gibi); başka hata fırlatılır", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    vi.stubGlobal("fetch", sahteCore({ "/code/languages": { status: 403, govde: { detail: "Bu işlem için yetkiniz yok." } } }, []));
    await expect(api.kodDilleri("web")).resolves.toBeNull();
    vi.stubGlobal("fetch", sahteCore({ "/code/languages": { status: 500, govde: { detail: "patladı" } } }, []));
    await expect(api.kodDilleri("web")).rejects.toBeInstanceOf(ApiError);
  });

  it("Kod üretiminde 403: dil seçici ve hata kutusu yok; üretim düğmesi durur", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    vi.stubGlobal(
      "fetch",
      sahteCore({ "/scripts": { govde: [] }, "/cases": { govde: [] }, "/code/languages": { status: 403, govde: { detail: "Bu işlem için yetkiniz yok." } } }, []),
    );
    uygulama("/kod");
    expect(await screen.findByText("Henüz üretilen test yok.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Dil seçenekleri yükleniyor…")).toBeNull());
    expect(screen.queryByRole("radiogroup", { name: "Dil" })).toBeNull();
    expect(screen.queryByText("Dil seçenekleri yüklenemedi")).toBeNull();
    expect(screen.getByRole("button", { name: /Seçilenler için kod üret/ })).toBeInTheDocument();
  });
});

describe("EKR-E4: üretilen testler dar ekranda kart", () => {
  it("tablo `tablo-yigin`; her hücrede `data-etiket`, Test hücresi kart başlığı; boş eylem hücresi gizlenir", async () => {
    await oturumAc("muhendis");
    uygulama("/kod");
    const bolge = await screen.findByRole("region", { name: "Üretilen testler tablosu" });
    const tablo = within(bolge).getByRole("table");
    expect(tablo).toHaveClass("tablo-yigin");
    const satirlar = within(tablo).getAllByRole("row").slice(1);
    for (const tr of satirlar) {
      const hucreler = [...tr.querySelectorAll("td")];
      expect(hucreler.map((td) => td.getAttribute("data-etiket"))).toEqual(["Test", "Durum", "PR", "Kırarak doğrula", "Oluşturma", "Eylem"]);
      expect(hucreler[0]).toHaveClass("yigin-baslik");
      const eylemVar = within(hucreler[5]).queryByRole("button") !== null;
      expect(hucreler[5].classList.contains("bos-hucre")).toBe(!eylemVar);
    }
  });
});

describe("QA-O5: Test case'leri → case kartı ve otomasyon durumu", () => {
  it("caseScriptleri: kapatılanlar sayılmaz; liste yoksa null (uydurulmaz)", () => {
    const s = (id: string, case_ids: string[], durum: Script["durum"]) => ({ id, case_ids, durum }) as Script;
    const m = caseScriptleri([s("a", ["c1"], "merged"), s("b", ["c1", "c2"], "unverified"), s("c", ["c3"], "closed")])!;
    expect(m.get("c1")!.map((x) => x.id)).toEqual(["a", "b"]);
    expect(m.get("c2")!.map((x) => x.id)).toEqual(["b"]);
    expect(m.has("c3")).toBe(false);
    expect(caseScriptleri(null)).toBeNull();
  });

  it("satır bağlantısı `#case-<id>` çapasıyla; Otomasyon sütunu platform + dil + durum + PR, script yoksa 'Kod yok'", async () => {
    await oturumAc("analist");
    uygulama("/caseler");
    const tablo = await screen.findByRole("table");
    expect(within(tablo).getByRole("columnheader", { name: "Otomasyon" })).toBeInTheDocument();
    const satirOf = (baslik: string) => within(tablo).getAllByRole("link", { name: baslik })[0].closest("tr")!;
    const c9 = (await api.caseler()).find((c) => c.id === "case-1-9")!;
    expect(within(tablo).getAllByRole("link", { name: c9.icerik.title })[0]).toHaveAttribute("href", `/gereksinimler/${c9.requirement_id}/caseler#case-case-1-9`);
    // C9: web + Java PR açık (örnek veri scr-java).
    const hucre = await waitFor(() => {
      const h = satirOf(c9.icerik.title).querySelector('td[data-etiket="Otomasyon"]') as HTMLElement;
      expect(within(h).getAllByTestId("otomasyon-script").length).toBeGreaterThan(0);
      return h;
    });
    const java = within(hucre)
      .getAllByTestId("otomasyon-script")
      .find((li) => within(li).queryByTestId("dil-rozeti")?.textContent?.includes("Java"))!;
    expect(within(java).getByTestId("platform-rozeti")).toHaveTextContent("Web");
    expect(java).toHaveTextContent("PR açık");
    expect(java).toHaveTextContent("PR #24");
    // C8: doğrulanmamış Python — PR yok.
    const c8 = (await api.caseler()).find((c) => c.id === "case-1-8")!;
    const py = satirOf(c8.icerik.title).querySelector('td[data-etiket="Otomasyon"]') as HTMLElement;
    expect(py).toHaveTextContent("Python");
    expect(py).toHaveTextContent("Doğrulanmamış");
    // Script'i olmayan case: "Kod yok".
    const scriptli = new Set((await api.scriptler()).filter((s) => s.durum !== "closed").flatMap((s) => s.case_ids));
    const kodsuz = (await api.caseler()).find((c) => c.durum !== "superseded" && !scriptli.has(c.id))!;
    expect(satirOf(kodsuz.icerik.title).querySelector('td[data-etiket="Otomasyon"]')).toHaveTextContent("Kod yok");
  });

  it("çapalı case inceleme adresi o case'in kartına kaydırır ve odaklar", async () => {
    capaAyar.aralikMs = 10;
    await oturumAc("analist");
    const c = (await api.caseler()).find((x) => x.id === "case-1-9")!;
    const kaydir = vi.fn();
    Element.prototype.scrollIntoView = kaydir;
    uygulama(`/gereksinimler/${c.requirement_id}/caseler#case-case-1-9`);
    const kart = await screen.findByRole("article", { name: c.icerik.title });
    expect(kart).toHaveAttribute("id", "case-case-1-9");
    await waitFor(() => expect(document.activeElement).toBe(kart));
    expect(kaydir).toHaveBeenCalled();
    capaAyar.aralikMs = 100;
  });
});

describe("D-2 (tur 3): /kod/:id#pr PR kartına kaydırır", () => {
  it("veri kabuğun çapa aramasından geç gelse de PR kartı çizilince kaydırılır ve odaklanır", async () => {
    const eski = { ...capaAyar };
    capaAyar.aralikMs = 5;
    capaAyar.deneme = 2;
    try {
      await oturumAc("muhendis");
      const sc = (await api.scriptler()).find((x) => x.pr);
      expect(sc).toBeDefined();
      const detay = await api.script(sc!.id);
      // Kabuğun araması (2 × 5 ms) bitmeden veri gelmez.
      vi.spyOn(api, "script").mockImplementation(() => new Promise((r) => setTimeout(() => r(detay), 80)));
      const kaydir = vi.fn();
      Element.prototype.scrollIntoView = kaydir;
      const { container } = uygulama(`/kod/${encodeURIComponent(sc!.id)}#pr`);
      await waitFor(() => expect(container.querySelector("#pr")).not.toBeNull());
      await waitFor(() => expect(document.activeElement).toBe(container.querySelector("#pr")));
      expect(kaydir).toHaveBeenCalled();
    } finally {
      Object.assign(capaAyar, eski);
    }
  });
});

describe("MİM-Y2: Kontrol Kulesi doğrulanmamış script sayacı", () => {
  it("uyum: core `ai_katkisi.script_dogrulanmamis`; yoksa null", () => {
    expect(kontrolKulesiUyarla({ ai_katkisi: { script_dogrulanmamis: 2 } }).ai_katkisi.script_dogrulanmamis).toBe(2);
    expect(kontrolKulesiUyarla({ ai_katkisi: {} }).ai_katkisi.script_dogrulanmamis).toBeNull();
  });

  it("örnek veride bir doğrulanmamış script (C8 Python) satırı görünür", async () => {
    await oturumAc("muhendis");
    uygulama("/kontrol-kulesi");
    expect(await screen.findByTestId("script-dogrulanmamis")).toHaveTextContent("1 doğrulanmamış script");
  });
});
