// 013 review turu 1 portal düzeltmeleri (specs/013-sprint-otomasyonu §9): K13 "görüldü" sayacı
// (IntersectionObserver sahtesi + sahte zamanlayıcı), toplu onay sonucu/odak/teyit anlık görüntüsü,
// parçalı gönderimde kısmi sonuç, otomatik akış rozeti, Test verisi düzeltmeleri.
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { yapilandir } from "../api/http";
import { mockGoruntulemeEkle, mockIstek, mockVerisi } from "../api/mock/handlers";
import type { TestCase, TopluKararYaniti } from "../api/types";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { goruntulenenleriSifirla, YENIDEN_DENEME_MS, YENIDEN_DENEME_SAYISI, yeterinceGorunur } from "../components/CaseKarti";
import { gozlemciKur } from "../test/gorunurluk";
import { oturumAc } from "../test/yardimci";
import { TOPLU_UST_SINIR, topluOnayla } from "./CaseReview";

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

/** Birinci gereksinime üç taslak case (hiçbiri görülmemiş). */
function taslaklariKur(n = 3): { rid: string; caseler: TestCase[] } {
  const v = mockVerisi();
  const rid = v.gereksinimler[0].id;
  const temel = v.caseler[0];
  const caseler = Array.from({ length: n }, (_, i) => i + 1).map((k) => ({
    ...JSON.parse(JSON.stringify(temel)),
    id: `tc-d4-${k}`,
    requirement_id: rid,
    sira_no: k,
    durum: "draft",
    karar: null,
    karar_veren: null,
    karar_zamani: null,
    onaylanan_hash: null,
    jira_test_key: null,
    goruntulenme: null,
    icerik: { ...JSON.parse(JSON.stringify(temel.icerik)), title: `Taslak ${k}` },
  })) as TestCase[];
  v.caseler = [...v.caseler.filter((c) => c.requirement_id !== rid), ...caseler];
  v.scriptler = v.scriptler.filter((s) => !s.case_ids.some((id) => id.startsWith("tc-d4-")));
  return { rid, caseler };
}

const kart = async (baslik: string) => (await screen.findByRole("heading", { name: baslik })).closest("article") as HTMLElement;
/** Kart gözlenmeye başlayınca görünür yapar (efekt yeniden kurulmuş olabilir). */
async function gosterBekle(g: ReturnType<typeof gozlemciKur>, el: HTMLElement, s?: Parameters<ReturnType<typeof gozlemciKur>["goster"]>[1]) {
  await waitFor(() => expect(g.gozlenenler()).toContain(el));
  g.goster(el, s);
}
const ilerlet = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));

beforeEach(() => goruntulenenleriSifirla());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("K13 görünürlük eşiği", () => {
  const k = (gorunen: number, kart: number, ekran = 800) => ({
    isIntersecting: gorunen > 0,
    intersectionRect: { height: gorunen } as DOMRectReadOnly,
    boundingClientRect: { height: kart } as DOMRectReadOnly,
    rootBounds: { height: ekran } as DOMRectReadOnly,
  });
  it("kısa kart: yarısı görünmeli", () => {
    expect(yeterinceGorunur(k(200, 400))).toBe(true);
    expect(yeterinceGorunur(k(150, 400))).toBe(false);
  });
  it("viewport'tan uzun kart: yarım ekranı doldurması yeter (min(%50 kart, %50 viewport))", () => {
    expect(yeterinceGorunur(k(400, 3000))).toBe(true);
    expect(yeterinceGorunur(k(300, 3000))).toBe(false);
    expect(yeterinceGorunur(k(0, 3000))).toBe(false);
  });
});

describe("K13: kart en az 3 sn kesintisiz görünür kalınca bildirilir", () => {
  it("K13': kayıt görünürlüğün başında gider; 3 sn dolmadan kesilirse yerelde görülmez; dolunca toplu onaya girer", async () => {
    const { rid, caseler } = taslaklariKur();
    const g = gozlemciKur();
    await oturumAc("analist");
    const casus = vi.spyOn(api, "caseGoruntulendi");
    vi.useFakeTimers({ shouldAdvanceTime: true });
    uygulama(`/gereksinimler/${rid}/caseler`);
    const k1 = await kart("Taslak 1");
    await screen.findByRole("button", { name: "Tümünü onayla (0)" });

    await gosterBekle(g, k1);
    // POST görünürlüğün başında (review süresi bu andan ölçülür).
    await waitFor(() => expect(casus).toHaveBeenCalledTimes(1));
    expect(casus).toHaveBeenCalledWith(caseler[0].id);
    await ilerlet(2900);
    expect(screen.getByRole("button", { name: "Tümünü onayla (0)" })).toBeInTheDocument();
    g.gizle(k1);
    await ilerlet(3000);
    expect(screen.getByRole("button", { name: "Tümünü onayla (0)" })).toBeInTheDocument();

    // Yeni görünürlük döneminde sayaç baştan; kayıt zaten yapıldığı için ikinci POST yok.
    await gosterBekle(g, k1);
    await ilerlet(2900);
    expect(screen.getByRole("button", { name: "Tümünü onayla (0)" })).toBeInTheDocument();
    await ilerlet(200);
    expect(await screen.findByRole("button", { name: "Tümünü onayla (1)" })).toBeInTheDocument();
    expect(casus).toHaveBeenCalledTimes(1);
    // Görülen kart artık gözlenmez; yeniden görünse de istek gitmez.
    expect(g.gozlenenler()).not.toContain(k1);
    g.gizle(k1);
    g.goster(k1);
    await ilerlet(5000);
    expect(casus).toHaveBeenCalledTimes(1);
  });

  it("uzun kart yarım ekranı doldurunca sayılır; çeyreği görünen kısa kart sayılmaz", async () => {
    const { rid, caseler } = taslaklariKur();
    const g = gozlemciKur();
    await oturumAc("analist");
    const casus = vi.spyOn(api, "caseGoruntulendi");
    vi.useFakeTimers({ shouldAdvanceTime: true });
    uygulama(`/gereksinimler/${rid}/caseler`);
    const k2 = await kart("Taslak 2");
    const k3 = await kart("Taslak 3");
    await gosterBekle(g, k2, { kart: 3000, ekran: 800, gorunen: 400 });
    await gosterBekle(g, k3, { kart: 400, ekran: 800, gorunen: 100 });
    await ilerlet(3100);
    expect(casus.mock.calls.map((c) => c[0])).toEqual([caseler[1].id]);
  });

  it("POST hata verirse kart görünür kaldıkça zamanlayıcıyla yeniden denenir; 3 sn başarılı kayıttan sayılır", async () => {
    const { rid } = taslaklariKur();
    const g = gozlemciKur();
    await oturumAc("analist");
    const casus = vi.spyOn(api, "caseGoruntulendi").mockRejectedValueOnce(new Error("ağ yok"));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    uygulama(`/gereksinimler/${rid}/caseler`);
    const k1 = await kart("Taslak 1");
    await gosterBekle(g, k1);
    await waitFor(() => expect(casus).toHaveBeenCalledTimes(1));
    // Kart hareket etmeden yeniden denenir.
    await ilerlet(YENIDEN_DENEME_MS);
    await waitFor(() => expect(casus).toHaveBeenCalledTimes(2));
    // Görünürlüğün 3. saniyesi: kayıt 2. saniyede yapıldı, sunucu penceresi henüz dolmadı.
    await ilerlet(1000);
    expect(screen.getByRole("button", { name: "Tümünü onayla (0)" })).toBeInTheDocument();
    await ilerlet(2100);
    expect(await screen.findByRole("button", { name: "Tümünü onayla (1)" })).toBeInTheDocument();
  });

  it("yeniden deneme sınırlı; kart görünmüyorsa denenmez", async () => {
    const { rid } = taslaklariKur();
    const g = gozlemciKur();
    await oturumAc("analist");
    const casus = vi.spyOn(api, "caseGoruntulendi").mockRejectedValue(new Error("ağ yok"));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    uygulama(`/gereksinimler/${rid}/caseler`);
    const k1 = await kart("Taslak 1");
    await gosterBekle(g, k1);
    await ilerlet(YENIDEN_DENEME_MS * (YENIDEN_DENEME_SAYISI + 3));
    expect(casus).toHaveBeenCalledTimes(1 + YENIDEN_DENEME_SAYISI);
    g.gizle(k1);
    await ilerlet(YENIDEN_DENEME_MS * 3);
    expect(casus).toHaveBeenCalledTimes(1 + YENIDEN_DENEME_SAYISI);
    // Yeni görünürlük döneminde yeniden denenir.
    g.goster(k1);
    await waitFor(() => expect(casus).toHaveBeenCalledTimes(2 + YENIDEN_DENEME_SAYISI));
    expect(screen.getByRole("button", { name: "Tümünü onayla (0)" })).toBeInTheDocument();
  });

  it("sekme gizlenince sayaç durur ve sıfırlanır; gizli sekmede kayıt gönderilmez", async () => {
    const { rid } = taslaklariKur();
    const g = gozlemciKur();
    let gorunurluk: DocumentVisibilityState = "hidden";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => gorunurluk);
    const sekme = (d: DocumentVisibilityState) => {
      gorunurluk = d;
      act(() => void document.dispatchEvent(new Event("visibilitychange")));
    };
    await oturumAc("analist");
    const casus = vi.spyOn(api, "caseGoruntulendi");
    vi.useFakeTimers({ shouldAdvanceTime: true });
    uygulama(`/gereksinimler/${rid}/caseler`);
    const k1 = await kart("Taslak 1");
    await gosterBekle(g, k1);
    await ilerlet(4000);
    expect(casus).not.toHaveBeenCalled();

    sekme("visible");
    await waitFor(() => expect(casus).toHaveBeenCalledTimes(1));
    await ilerlet(2000);
    sekme("hidden");
    await ilerlet(3000);
    expect(screen.getByRole("button", { name: "Tümünü onayla (0)" })).toBeInTheDocument();
    sekme("visible");
    await ilerlet(2900);
    expect(screen.getByRole("button", { name: "Tümünü onayla (0)" })).toBeInTheDocument();
    await ilerlet(200);
    expect(await screen.findByRole("button", { name: "Tümünü onayla (1)" })).toBeInTheDocument();
    expect(casus).toHaveBeenCalledTimes(1);
  });

  it("karar + yeniden açma sonrası case yeniden görülmeden toplu onaya girmez; yeniden bildirilir", async () => {
    const { rid, caseler } = taslaklariKur();
    const g = gozlemciKur();
    await oturumAc("analist");
    const casus = vi.spyOn(api, "caseGoruntulendi");
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const u = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    uygulama(`/gereksinimler/${rid}/caseler`);
    let k1 = await kart("Taslak 1");
    await gosterBekle(g, k1);
    await ilerlet(3000);
    await screen.findByRole("button", { name: "Tümünü onayla (1)" });

    await u.click(within(k1).getByRole("button", { name: "Onayla" }));
    await waitFor(() => expect(mockVerisi().caseler.find((c) => c.id === caseler[0].id)!.durum).toBe("approved"));
    k1 = await kart("Taslak 1");
    await u.click(await within(k1).findByRole("button", { name: "Yeniden aç" }));
    await waitFor(() => expect(mockVerisi().caseler.find((c) => c.id === caseler[0].id)!.durum).toBe("draft"));
    expect(await screen.findByRole("button", { name: "Tümünü onayla (0)" })).toBeInTheDocument();

    k1 = await kart("Taslak 1");
    await waitFor(() => expect(g.gozlenenler()).toContain(k1));
    await gosterBekle(g, k1);
    await ilerlet(3000);
    expect(casus.mock.calls.filter((c) => c[0] === caseler[0].id)).toHaveLength(2);
    expect(await screen.findByRole("button", { name: "Tümünü onayla (1)" })).toBeInTheDocument();
  });

  it("IntersectionObserver yoksa görünürlük doğrulanamaz: bildirilmez (güvenli taraf)", async () => {
    const { rid } = taslaklariKur();
    vi.stubGlobal("IntersectionObserver", undefined);
    await oturumAc("analist");
    const casus = vi.spyOn(api, "caseGoruntulendi");
    vi.useFakeTimers({ shouldAdvanceTime: true });
    uygulama(`/gereksinimler/${rid}/caseler`);
    await kart("Taslak 1");
    await ilerlet(5000);
    expect(casus).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Tümünü onayla (0)" })).toBeInTheDocument();
  });
});

describe("Toplu onay: sonuç, odak, teyit anlık görüntüsü", () => {
  it("tüm taslaklar onaylanınca da sonuç özeti kalır ve odak başlığına gider; teyitte odak kutuya, Vazgeç'te tetikleyene", async () => {
    const { rid, caseler } = taslaklariKur(2);
    for (const c of caseler) mockGoruntulemeEkle(c.id, "analist");
    await oturumAc("analist");
    uygulama(`/gereksinimler/${rid}/caseler`);
    const u = userEvent.setup();
    const tumu = await screen.findByRole("button", { name: "Tümünü onayla (2)" });
    await u.click(tumu);
    const teyit = screen.getByRole("group", { name: "Toplu onay teyidi" });
    await waitFor(() => expect(within(teyit).getByRole("checkbox")).toHaveFocus());
    await u.click(within(teyit).getByRole("button", { name: "Vazgeç" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Tümünü onayla (2)" })).toHaveFocus());

    await u.click(screen.getByRole("button", { name: "Tümünü onayla (2)" }));
    const t2 = screen.getByRole("group", { name: "Toplu onay teyidi" });
    await u.click(within(t2).getByRole("checkbox"));
    await u.click(within(t2).getByRole("button", { name: "Onayla (2)" }));
    const sonuc = await screen.findByTestId("toplu-onay-sonucu");
    expect(sonuc).toHaveTextContent("Toplu onay: 2 onaylandı · 0 atlandı");
    // Taslak kalmadı: çubuk kalkar ama özet kalır.
    await waitFor(() => expect(screen.queryByRole("region", { name: "Toplu onay" })).toBeNull());
    expect(screen.getByTestId("toplu-onay-sonucu")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("heading", { name: /^Toplu onay: 2 onaylandı/ })).toHaveFocus());
  });

  it("teyit açıkken hedef liste değişirse teyit sıfırlanır", async () => {
    const { rid, caseler } = taslaklariKur(3);
    mockGoruntulemeEkle(caseler[0].id, "analist");
    mockGoruntulemeEkle(caseler[1].id, "analist");
    const g = gozlemciKur();
    await oturumAc("analist");
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const u = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    uygulama(`/gereksinimler/${rid}/caseler`);
    await u.click(await screen.findByRole("button", { name: "Tümünü onayla (2)" }));
    const teyit = screen.getByRole("group", { name: "Toplu onay teyidi" });
    await u.click(within(teyit).getByRole("checkbox"));
    expect(within(teyit).getByRole("button", { name: "Onayla (2)" })).toBeEnabled();
    // Üçüncü case bu arada 3 sn görülür: hedef değişti.
    await gosterBekle(g, await kart("Taslak 3"));
    await ilerlet(3000);
    await waitFor(() => expect(within(teyit).getByRole("button", { name: "Onayla (3)" })).toBeDisabled());
    expect(within(teyit).getByRole("checkbox")).not.toBeChecked();
    expect(within(teyit).getByRole("alert")).toHaveTextContent("Liste değişti");
  });

  it("200'den fazla öğe: ikinci parça hata verirse ilk parçanın sonucu korunur", async () => {
    const ogeler = Array.from({ length: TOPLU_UST_SINIR + 5 }, (_, i) => ({ id: `c${i}`, icerik_hash: `h${i}` }));
    let n = 0;
    const gonder = vi.fn(async (p: { id: string }[]): Promise<TopluKararYaniti> => {
      if (n++ > 0) throw new Error("bağlantı koptu");
      return {
        sonuclar: p.map((c) => ({ case_id: c.id, durum: "onaylandi", neden: null, otomatik_kod: null })),
        ozet: { onaylandi: p.length, atlandi: 0, hata: 0 },
        otomatik_kod: { durum: "kuyrukta", job_id: "j1", case_sayisi: p.length },
      };
    });
    const c = await topluOnayla(ogeler, gonder);
    expect(gonder).toHaveBeenCalledTimes(2);
    expect(c.yanit.ozet.onaylandi).toBe(TOPLU_UST_SINIR);
    expect(c.yanit.otomatik_kod).toEqual({ durum: "kuyrukta", job_id: "j1", case_sayisi: TOPLU_UST_SINIR });
    expect(c.hata).toBeInstanceOf(Error);
    expect(c.gonderilmeyen).toBe(5);
  });

  it("istek hata verse de sonuç (hata) gösterilir ve liste yenilenir", async () => {
    const { rid, caseler } = taslaklariKur(2);
    for (const c of caseler) mockGoruntulemeEkle(c.id, "analist");
    await oturumAc("analist");
    const caseIstekleri: string[] = [];
    yapilandir({
      mock: async (method, path, q, govde) => {
        if (path === "/cases/bulk-decision") throw new Error("sunucu yok");
        if (method === "GET" && path === "/cases") caseIstekleri.push(path);
        return mockIstek(method, path, q, govde);
      },
    });
    uygulama(`/gereksinimler/${rid}/caseler`);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Tümünü onayla (2)" }));
    const teyit = screen.getByRole("group", { name: "Toplu onay teyidi" });
    await u.click(within(teyit).getByRole("checkbox"));
    const once = caseIstekleri.length;
    await u.click(within(teyit).getByRole("button", { name: "Onayla (2)" }));
    const sonuc = await screen.findByTestId("toplu-onay-sonucu");
    expect(sonuc).toHaveTextContent("2 gönderilemedi");
    await waitFor(() => expect(caseIstekleri.length).toBeGreaterThan(once));
  });
});

describe("Gereksinim otomatik akış rozeti (K15)", () => {
  it("durdu ise neden görünür; liste ve detayda", async () => {
    const g = mockVerisi().gereksinimler[0] as unknown as { id: string; otomatik_akis?: unknown };
    g.otomatik_akis = { tetik_zamani: "2026-11-12T09:00:00+03:00", durum: "durdu", neden: "İçerik değişti, ön inceleme yeniden başlatılamadı" };
    await oturumAc("analist");
    const { unmount } = uygulama("/gereksinimler");
    const rozet = await screen.findByTestId("otomatik-akis");
    expect(rozet).toHaveAttribute("data-durum", "durdu");
    expect(rozet).toHaveTextContent("Otomatik akış durdu İçerik değişti, ön inceleme yeniden başlatılamadı; elle sürdürün.");
    unmount();
    uygulama(`/gereksinimler/${g.id}`);
    expect(await screen.findByTestId("otomatik-akis")).toHaveTextContent("Otomatik akış durdu");
  });
});

describe("Test verisi düzeltmeleri", () => {
  it("açıklama temizlenince boş metin gider; K17/K18 notları; silme teyidinde ilk odak Vazgeç; grup başlık kimliği boşluksuz", async () => {
    await oturumAc("analist");
    const cagrilar: { method: string; path: string; govde: unknown }[] = [];
    yapilandir({
      mock: async (method, path, q, govde) => {
        cagrilar.push({ method, path, govde });
        return mockIstek(method, path, q, govde);
      },
    });
    uygulama("/test-verisi");
    const u = userEvent.setup();
    const not = await screen.findByTestId("katalog-kapsam-notu");
    expect(not).toHaveTextContent("REPLAY (demo provası) kipinde kayıtlı veri kullanılır");
    expect(not).toHaveTextContent("Etiket ve ayar grupları case'e otomatik atfedilmez");
    await waitFor(() => expect(not).toHaveTextContent("Şu anki kip: REPLAY"));

    await u.click(await screen.findByRole("button", { name: "urun.p_001.fiyat düzenle" }));
    await u.clear(screen.getByLabelText("Açıklama"));
    await u.click(screen.getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(cagrilar.find((c) => c.method === "PUT")?.govde).toMatchObject({ aciklama: "" }));
    await waitFor(() => expect(document.querySelector('tr[data-anahtar="urun.p_001.fiyat"]')).toHaveTextContent("s2"));

    await u.click(screen.getByRole("button", { name: "kampanya.k6_1.ad sil" }));
    const satir = document.querySelector('tr[data-anahtar="kampanya.k6_1.ad"]') as HTMLElement;
    expect(within(satir).getByRole("button", { name: "Vazgeç" })).toHaveFocus();

    for (const s of document.querySelectorAll("section.testveri-grup")) {
      expect(s.getAttribute("aria-labelledby")).not.toMatch(/\s/);
      expect(document.getElementById(s.getAttribute("aria-labelledby")!)).not.toBeNull();
    }
    // Gizli değer hiçbir yerde yok.
    expect(document.body).not.toHaveTextContent("Demo123!");
  });

  it("Test verisi ekle: atfın alanı olan adım silinince ekleme yapılmaz", async () => {
    const { rid } = taslaklariKur(1);
    await oturumAc("analist");
    uygulama(`/gereksinimler/${rid}/caseler`);
    const k = await kart("Taslak 1");
    const u = userEvent.setup();
    await u.click(within(k).getByRole("button", { name: "Düzelt" }));
    await u.click(within(k).getByRole("button", { name: "Adım ekle" }));
    const adimSayisi = within(k).getAllByRole("button", { name: /adımını sil$/ }).length;
    const sonVeri = within(k).getByLabelText(`S${adimSayisi} veri`);
    await u.click(sonVeri);
    await u.selectOptions(await within(k).findByLabelText("Eklenecek test verisi"), "bayi.bayi1.kullanici_adi");
    expect(within(k).getByRole("button", { name: `İmlece ekle (S${adimSayisi} veri)` })).toBeEnabled();
    await u.click(within(k).getByRole("button", { name: `S${adimSayisi} adımını sil` }));
    // Son alan sıfırlandı: alan seçilmeden ekleme yok.
    expect(within(k).getByRole("button", { name: "İmlece ekle" })).toBeDisabled();
    for (const t of within(k).getAllByRole("textbox")) expect((t as HTMLInputElement).value).not.toContain("{veri:");
  });
});
