// 013 review turu 3 portal düzeltmeleri (specs/013-sprint-otomasyonu §11: K13' yerel küme, K22, K23):
// toplu onay uygunluğu yalnız yerel 3 sn kümesi, son karar değişince yeniden görüntüleme, 200'ü aşan
// onayda iş başına özet, başlıkta atıf çipi + maske uyarısı/422 ipucu, REPLAY uyarısı, tetik nedeni,
// taban bilgisi ve Test verisi IDE notu.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ApiError, yapilandir } from "../api/http";
import { mockGoruntulemeEkle, mockIstek, mockVerisi } from "../api/mock/handlers";
import type { TestCase, TopluKararYaniti } from "../api/types";
import { jiraTetikDurumuUyarla, otomasyonAyarlariUyarla } from "../api/uyumOtomasyon";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { CaseKarti, COK_DENEME_IPUCU, goruntulenenleriSifirla, MASKE_HATASI_IPUCU, maskeliAlanlar } from "../components/CaseKarti";
import { AtifliMetin } from "../components/VeriAtfi";
import { gozlemciKur } from "../test/gorunurluk";
import { oturumAc } from "../test/yardimci";
import { topluOnayla, topluOtokodMetni, TopluOnaySonucu } from "./CaseReview";
import { REPLAY_OTOKOD_UYARISI } from "./Otomasyon";

function Sarmal({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter>
      <OturumProvider>
        <BildirimProvider>{children}</BildirimProvider>
      </OturumProvider>
    </MemoryRouter>
  );
}

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

type Cagri = { method: string; path: string; govde: unknown };
function izle(ozel?: (c: Cagri) => unknown) {
  const cagrilar: Cagri[] = [];
  yapilandir({
    mock: async (method, path, q, govde) => {
      const c = { method, path, govde };
      cagrilar.push(c);
      const o = ozel?.(c);
      if (o !== undefined) return o;
      return mockIstek(method, path, q, govde);
    },
  });
  return cagrilar;
}

/** Birinci gereksinime n taslak case; hepsi sunucuda analist tarafından ≥ 3 sn önce görülmüş. */

/** 012: case'i Testçi kararı bekleyen taslağa çevirir (düzeltme Testçinin işidir). */
function taslagaCevir(id: string) {
  Object.assign(mockVerisi().caseler.find((x) => x.id === id)!, { durum: "draft", karar: null, testci_karari: null, testci: null, karar_veren: null });
}

function taslaklariKur(n = 2): { rid: string; caseler: TestCase[] } {
  const v = mockVerisi();
  const rid = v.gereksinimler[0].id;
  const temel = v.caseler[0];
  const caseler = Array.from({ length: n }, (_, i) => i + 1).map((k) => ({
    ...JSON.parse(JSON.stringify(temel)),
    id: `tc-f3-${k}`,
    requirement_id: rid,
    sira_no: k,
    // 012: Testçi kabul etti (onaya hazır); Analist toplu/tekli son onayı verir.
    durum: "ready",
    karar: "accept",
    testci_karari: "accept",
    testci: "testci",
    karar_veren: "testci",
    karar_zamani: null,
    son_onay: null,
    onaylanan_hash: null,
    jira_test_key: null,
    goruntulenme: "2026-11-11T09:00:00+03:00",
    icerik: { ...JSON.parse(JSON.stringify(temel.icerik)), title: `Taslak ${k}` },
  })) as TestCase[];
  v.caseler = [...v.caseler.filter((c) => c.requirement_id !== rid), ...caseler];
  v.scriptler = v.scriptler.filter((s) => !s.case_ids.some((id) => id.startsWith("tc-f3-")));
  for (const c of caseler) mockGoruntulemeEkle(c.id, "analist");
  return { rid, caseler };
}

beforeEach(() => {
  goruntulenenleriSifirla();
  yapilandir({ mock: mockIstek });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("QA #3: toplu onay yalnız yerel 3 sn kümesine dayanır", () => {
  it("sunucu 'görüldü' dese de yerel küme boşsa (sayfa yenilendi) toplu onaya girmez; not açıklar", async () => {
    const { rid } = taslaklariKur(2);
    await oturumAc("analist");
    // jsdom'da gözlemci yok: kart görünürlüğü doğrulanamaz, yerel küme boş kalır.
    vi.stubGlobal("IntersectionObserver", undefined);
    uygulama(`/gereksinimler/${rid}/caseler`);
    expect(await screen.findByRole("button", { name: "Toplu onayla (0)" })).toBeDisabled();
    const not = screen.getByTestId("toplu-onay-notu");
    expect(not).toHaveTextContent("2 case en az 3 saniye ekranda kalmadığı için dışarıda.");
    expect(not).toHaveTextContent("sayfa yenilenince case'lerin yeniden en az 3 saniye ekranda kalması gerekir");
  });

  it("sunucu görüldü diyen kart da yeniden 3 sn görülünce uygun olur (görüntüleme yeniden gönderilir)", async () => {
    const { rid, caseler } = taslaklariKur(1);
    const g = gozlemciKur();
    await oturumAc("analist");
    const casus = vi.spyOn(api, "caseGoruntulendi");
    vi.useFakeTimers({ shouldAdvanceTime: true });
    uygulama(`/gereksinimler/${rid}/caseler`);
    const kart = (await screen.findByRole("heading", { name: "Taslak 1" })).closest("article") as HTMLElement;
    await waitFor(() => expect(g.gozlenenler()).toContain(kart));
    g.goster(kart);
    await waitFor(() => expect(casus).toHaveBeenCalledWith(caseler[0].id));
    await vi.advanceTimersByTimeAsync(3000);
    expect(await screen.findByRole("button", { name: "Toplu onayla (1)" })).toBeEnabled();
  });
});

describe("Frontend #4: son karar değişince yerel kayıt sıfırlanır", () => {
  it("başka sekmede onaylanıp yeniden açılan case için görüntüleme yeniden gönderilir", async () => {
    const { caseler } = taslaklariKur(1);
    const g = gozlemciKur();
    await oturumAc("analist");
    const casus = vi.spyOn(api, "caseGoruntulendi");
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const goruldu = vi.fn();
    const tc = { ...caseler[0] };
    const { rerender } = render(<CaseKarti tc={tc} guncellendi={() => undefined} goruntulendi={goruldu} />, { wrapper: Sarmal });
    const kart = (await screen.findByRole("heading", { name: "Taslak 1" })).closest("article") as HTMLElement;
    await waitFor(() => expect(g.gozlenenler()).toContain(kart));
    g.goster(kart);
    await vi.advanceTimersByTimeAsync(3100);
    await waitFor(() => expect(goruldu).toHaveBeenCalledTimes(1));
    expect(casus).toHaveBeenCalledTimes(1);

    // Sessiz yenileme: case başka yerde onaylanıp yeniden açılmış (son karar değişti).
    rerender(<CaseKarti tc={{ ...tc, karar: "approve", karar_zamani: "2026-11-12T10:00:00Z" }} guncellendi={() => undefined} goruntulendi={goruldu} />);
    await waitFor(() => expect(g.gozlenenler()).toContain(kart));
    g.goster(kart);
    await waitFor(() => expect(casus).toHaveBeenCalledTimes(2));
    await vi.advanceTimersByTimeAsync(3100);
    await waitFor(() => expect(goruldu).toHaveBeenCalledTimes(2));
  });
});

describe("QA #5: 200'ü aşan toplu onayda iş başına özet", () => {
  it("her parçanın işi ayrı tutulur ve ayrı çekmecede gösterilir", async () => {
    const ogeler = Array.from({ length: 250 }, (_, i) => ({ id: `c${i}`, icerik_hash: `h${i}` }));
    let n = 0;
    const gonder = vi.fn(async (p: { id: string }[]): Promise<TopluKararYaniti> => {
      n += 1;
      return {
        sonuclar: p.map((c) => ({ case_id: c.id, durum: "onaylandi", neden: null, otomatik_kod: null })),
        ozet: { onaylandi: p.length, atlandi: 0, hata: 0 },
        otomatik_kod: { durum: "kuyrukta", job_id: `j${n}`, case_sayisi: p.length },
      };
    });
    const cikti = await topluOnayla(ogeler, gonder);
    expect(cikti.kodIsleri).toEqual(["j1", "j2"]);
    expect(topluOtokodMetni(cikti.yanit, 2)).toContain("250 case için web kodu üretimi kuyruğa alındı (2 arka plan işi");

    await oturumAc("analist");
    const istenen: string[] = [];
    vi.spyOn(api, "kodUretimIsi").mockImplementation(async (id: string) => {
      istenen.push(id);
      return { job_id: id, durum: "tamam", case_sayisi: id === "j1" ? 200 : 50, ozet: { kuyrukta: 1 }, sonuclar: [], hata: null };
    });
    render(<TopluOnaySonucu sonuc={{ cikti, caseler: [] }} kapat={() => undefined} />, { wrapper: Sarmal });
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Kod üretimi sonucunu göster (iş 1/2)" }));
    await u.click(screen.getByRole("button", { name: "Kod üretimi sonucunu göster (iş 2/2)" }));
    const ozetler = await screen.findAllByTestId("kod-uretim-isi");
    expect(ozetler).toHaveLength(2);
    await waitFor(() => expect(ozetler[0]).toHaveTextContent("200 case"));
    await waitFor(() => expect(ozetler[1]).toHaveTextContent("50 case"));
    expect(istenen.sort()).toEqual(["j1", "j2"]);
  });
});

describe("K22: gizli değer atfı ve maske", () => {
  it("başlıktaki atıf çip olarak görünür; düzelt formu atfı korur", async () => {
    const { rid, caseler } = taslaklariKur(1);
    // 012: düzeltme Testçinin taslaktaki kararıdır.
    for (const c of caseler) taslagaCevir(c.id);
    const c = mockVerisi().caseler.find((x) => x.id === caseler[0].id)!;
    c.icerik.title = "{veri:ortak.demo_parola} ile giriş";
    await oturumAc("testci");
    const cagrilar = izle();
    uygulama(`/gereksinimler/${rid}/caseler`);
    const baslik = await screen.findByRole("heading", { name: /ile giriş/ });
    await waitFor(() => expect(baslik.querySelector('.veri-atif[data-anahtar="ortak.demo_parola"]')).not.toBeNull());
    expect(baslik).toHaveTextContent("••• (gizli)");
    expect(baslik).not.toHaveTextContent("Demo123!");
    const kart = baslik.closest("article") as HTMLElement;
    const u = userEvent.setup();
    await u.click(within(kart).getByRole("button", { name: "Düzelterek kabul" }));
    expect(within(kart).getByLabelText("Başlık")).toHaveValue("{veri:ortak.demo_parola} ile giriş");
    expect(within(kart).queryByTestId("maske-uyarisi")).toBeNull();
    await u.click(within(kart).getByRole("button", { name: "Düzelterek kabul et" }));
    await waitFor(() => expect(cagrilar.some((x) => x.path === `/cases/${caseler[0].id}/decision`)).toBe(true));
    const govde = cagrilar.find((x) => x.path === `/cases/${caseler[0].id}/decision`)!.govde as { icerik: { title: string } };
    expect(govde.icerik.title).toBe("{veri:ortak.demo_parola} ile giriş");
  });

  it("formda ••• görünürse uyarır ve kaydetmeden durur", async () => {
    const { rid, caseler } = taslaklariKur(1);
    // 012: düzeltme Testçinin taslaktaki kararıdır.
    for (const c of caseler) taslagaCevir(c.id);
    const c = mockVerisi().caseler.find((x) => x.id === caseler[0].id)!;
    c.icerik.steps[0] = { ...c.icerik.steps[0], data: "•••" };
    await oturumAc("testci");
    const cagrilar = izle();
    uygulama(`/gereksinimler/${rid}/caseler`);
    const kart = (await screen.findByRole("heading", { name: "Taslak 1" })).closest("article") as HTMLElement;
    const u = userEvent.setup();
    await u.click(within(kart).getByRole("button", { name: "Düzelterek kabul" }));
    expect(within(kart).getByTestId("maske-uyarisi")).toHaveTextContent("maskeli gizli değer (•••)");
    expect(within(kart).getByTestId("maske-uyarisi")).toHaveTextContent("(S1)");
    await u.click(within(kart).getByRole("button", { name: "Düzelterek kabul et" }));
    expect(await within(kart).findByRole("alert")).toHaveTextContent("{veri:anahtar}");
    expect(cagrilar.some((x) => x.path.endsWith("/decision"))).toBe(false);
  });

  it("sunucunun maske 422'si anlaşılır ipucuyla gösterilir", async () => {
    const { rid, caseler } = taslaklariKur(1);
    // 012: düzeltme Testçinin taslaktaki kararıdır.
    for (const c of caseler) taslagaCevir(c.id);
    await oturumAc("testci");
    izle((x) => {
      if (x.path.endsWith("/decision")) throw new ApiError(422, "Gizli değer maskeli görünüyor; {veri:…} atfını kullanın");
      return undefined;
    });
    uygulama(`/gereksinimler/${rid}/caseler`);
    const kart = (await screen.findByRole("heading", { name: "Taslak 1" })).closest("article") as HTMLElement;
    const u = userEvent.setup();
    await u.click(within(kart).getByRole("button", { name: "Düzelterek kabul" }));
    await u.click(within(kart).getByRole("button", { name: "Düzelterek kabul et" }));
    expect(await within(kart).findByTestId("maske-hatasi-ipucu")).toHaveTextContent(MASKE_HATASI_IPUCU);
    expect(kart).toHaveTextContent("Gizli değer maskeli görünüyor");
  });

  it("maskeliAlanlar alanları adlandırır", () => {
    expect(
      maskeliAlanlar({
        title: "a ••• b",
        type: "positive",
        risk: "low",
        preconditions: ["x"],
        acceptance_criteria_refs: ["AC1"],
        tags: [],
        steps: [{ id: "S1", action: "a", data: null, expected: "e" }, { id: "S2", action: "a", data: "•••", expected: "e" }],
        expected_result: "ok",
      }),
    ).toEqual(["Başlık", "S2"]);
  });
});

describe("Review tur 4: başlık atfı, etiket maskesi, düzeltme 429", () => {
  it("veri geldi ama anahtar yoksa çip nötr; yalnız var:false kırmızı", () => {
    const { container } = render(
      <AtifliMetin
        metin="{veri:ortak.demo_parola} ve {veri:bayi.silinen.ad}"
        veri={{ "bayi.silinen.ad": { deger: null, gizli: false, surum: null, var: false } }}
      />,
    );
    expect(container.querySelector('[data-anahtar="ortak.demo_parola"]')).toHaveAttribute("data-durum", "bilinmiyor");
    expect(container.querySelector('[data-anahtar="bayi.silinen.ad"]')).toHaveAttribute("data-durum", "yok");
    expect(container.querySelector('[data-anahtar="ortak.demo_parola"]')).not.toHaveTextContent("katalogda yok");
  });

  it("maskeliAlanlar etiketleri de kapsar", () => {
    expect(
      maskeliAlanlar({
        title: "t",
        type: "positive",
        risk: "low",
        preconditions: [],
        acceptance_criteria_refs: ["AC1"],
        tags: ["giris", "x•••"],
        steps: [{ id: "S1", action: "a", data: null, expected: "e" }],
        expected_result: "ok",
      }),
    ).toEqual(["Etiketler"]);
  });

  it("düzeltme 429'u anlaşılır ipucuyla gösterilir", async () => {
    const { rid, caseler } = taslaklariKur(1);
    // 012: düzeltme Testçinin taslaktaki kararıdır.
    for (const c of caseler) taslagaCevir(c.id);
    await oturumAc("testci");
    izle((x) => {
      if (x.path.endsWith("/decision")) {
        throw new ApiError(429, "Çok sayıda test verisi değeri reddedildi; bir süre sonra yeniden deneyin (parola ve benzeri değerleri gizli kayıt olarak tanımlayın)");
      }
      return undefined;
    });
    uygulama(`/gereksinimler/${rid}/caseler`);
    const kart = (await screen.findByRole("heading", { name: "Taslak 1" })).closest("article") as HTMLElement;
    const u = userEvent.setup();
    await u.click(within(kart).getByRole("button", { name: "Düzelterek kabul" }));
    await u.click(within(kart).getByRole("button", { name: "Düzelterek kabul et" }));
    expect(await within(kart).findByTestId("cok-deneme-ipucu")).toHaveTextContent(COK_DENEME_IPUCU);
    expect(within(kart).queryByTestId("maske-hatasi-ipucu")).toBeNull();
  });
});

describe("K23 ve tetik: Otomasyon sayfası", () => {
  it("ayar ucu REPLAY bildirirse uyarı gösterilir", async () => {
    await oturumAc("analist");
    izle((x) => {
      if (x.method === "GET" && x.path === "/automation-settings") {
        return mockIstek("GET", "/automation-settings", new URLSearchParams(), undefined).then((g) => ({ ...(g as object), model_kipi: "replay" }));
      }
      return undefined;
    });
    uygulama("/otomasyon");
    expect(await screen.findByTestId("replay-otokod-uyarisi")).toHaveTextContent(REPLAY_OTOKOD_UYARISI);
  });

  it("ayar ucu bildirmezse /demo/status model.mod'a düşer; live'da uyarı yok", async () => {
    await oturumAc("analist");
    let mod = "replay";
    izle((x) => {
      if (x.method === "GET" && x.path === "/demo/status") {
        return mockIstek("GET", "/demo/status", new URLSearchParams(), undefined).then((d) => ({ ...(d as object), model: { mod } }));
      }
      return undefined;
    });
    const r = uygulama("/otomasyon");
    expect(await screen.findByTestId("replay-otokod-uyarisi")).toBeInTheDocument();
    r.unmount();
    mod = "live";
    uygulama("/otomasyon");
    await screen.findByRole("heading", { name: "Onay sonrası otomatik kod üretimi" });
    await new Promise((x) => setTimeout(x, 50));
    expect(screen.queryByTestId("replay-otokod-uyarisi")).toBeNull();
  });

  it("story başına son tetik sonucu kalıcı nedeniyle görünür", async () => {
    await oturumAc("analist");
    izle((x) =>
      x.method === "GET" && x.path === "/automation/jira-trigger"
        ? {
            acik: true,
            durum: "QA To Do",
            aralik_s: 60,
            son_tur: null,
            son_tetiklenenler: [{ jira_key: "TPD-9", zaman: "2026-11-12T09:00:00Z", sonuc: "dokunulmadi", neden: "Gereksinim hata durumunda (failed)" }],
          }
        : undefined,
    );
    uygulama("/otomasyon");
    const liste = await screen.findByTestId("son-tetik-sonuclari");
    expect(screen.getByRole("heading", { name: "Story başına son tetik sonucu" })).toBeInTheDocument();
    expect(liste).toHaveTextContent("TPD-9");
    expect(liste).toHaveTextContent("Dokunulmadı");
    expect(liste).toHaveTextContent("Gereksinim hata durumunda (failed)");
  });

  it("uyarlayıcılar: replay/model_kipi, neden, taban_bekleniyor/taban_kurulu", () => {
    expect(otomasyonAyarlariUyarla({ replay: true }).replay).toBe(true);
    expect(otomasyonAyarlariUyarla({ model_kipi: "live" }).replay).toBe(false);
    expect(otomasyonAyarlariUyarla({}).replay).toBeUndefined();
    expect(jiraTetikDurumuUyarla({ son_tetiklenenler: [{ jira_key: "A-1", neden: "x" }] }).son_tetiklenenler[0].neden).toBe("x");
    expect(jiraTetikDurumuUyarla({ acik: true, taban_kurulu: false }).taban_bekleniyor).toBe(true);
    expect(jiraTetikDurumuUyarla({ acik: true, taban_kurulu: true }).taban_bekleniyor).toBe(false);
    expect(jiraTetikDurumuUyarla({ taban_bekleniyor: true }).taban_bekleniyor).toBe(true);
    expect(jiraTetikDurumuUyarla({ acik: true }).taban_bekleniyor).toBeUndefined();
  });
});

describe("PO #6: Test verisi K17 notu", () => {
  it("IDE/MCP kanalının her zaman katalogu kullandığını söyler", async () => {
    await oturumAc("analist");
    uygulama("/test-verisi");
    expect(await screen.findByTestId("katalog-ide-notu")).toHaveTextContent("IDE/MCP kanalı (Claude Code, Copilot) her zaman bu kataloğu kullanır");
  });
});
