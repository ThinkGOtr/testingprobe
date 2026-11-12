// 013 review turu 2 portal düzeltmeleri (specs/013-sprint-otomasyonu §10: K13', K21, K10 case yarısı):
// pencere içi toplu onay nedeni, onaydan sonra değişen test verisi uyarısı, otomatik kod sayısı/atlananlar
// ve iş sonucu, teyitte taze ayar, K21 metinleri, tetik ipucu, grup temizleme, ScriptDetay kuralı, odak.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { yapilandir } from "../api/http";
import { mockGoruntulemeEkle, mockIstek, mockVerisi, YENI_GORUNTULEME_NEDENI } from "../api/mock/handlers";
import type { Gereksinim, TestCase } from "../api/types";
import { caseOtomasyonAlanlari, kodUretimIsiUyarla, otomasyonAyarlariUyarla, jiraTetikDurumuUyarla, topluKararUyarla } from "../api/uyumOtomasyon";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { goruntulenenleriSifirla } from "../components/CaseKarti";
import { ENGEL_TURU } from "../lib/kapi";
import { oturumAc, yereldeGorulmus } from "../test/yardimci";
import { tetikIpucu } from "./DemoKontrolleri";
import { AKIS_METNI_ELLE, AKIS_METNI_OTOMATIK } from "./Otomasyon";
import { GRUP_IPUCU } from "./TestVerisi";

/** K13' (tur 3): sunucu görüntülemesi + yerel 3 sn kaydı (toplu onay yalnız yereldekine bakar). */
let yerelGorulen: string[] = [];
function gor(id: string) {
  mockGoruntulemeEkle(id, "analist");
  yerelGorulen.push(id);
}
async function analistOturumu() {
  await oturumAc("analist");
  await yereldeGorulmus(yerelGorulen);
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

/** Birinci gereksinime n taslak case; `gorulen` kadarı analist tarafından en az 3 sn önce görülmüş. */
function taslaklariKur(n = 2, gorulen = n): { rid: string; caseler: TestCase[] } {
  const v = mockVerisi();
  const rid = v.gereksinimler[0].id;
  const temel = v.caseler[0];
  const caseler = Array.from({ length: n }, (_, i) => i + 1).map((k) => ({
    ...JSON.parse(JSON.stringify(temel)),
    id: `tc-e4-${k}`,
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
  v.scriptler = v.scriptler.filter((s) => !s.case_ids.some((id) => id.startsWith("tc-e4-")));
  for (const c of caseler.slice(0, gorulen)) gor(c.id);
  return { rid, caseler };
}

async function topluOnayVer(u: ReturnType<typeof userEvent.setup>, n: number) {
  await u.click(await screen.findByRole("button", { name: `Tümünü onayla (${n})` }));
  const teyit = screen.getByRole("group", { name: "Toplu onay teyidi" });
  await u.click(within(teyit).getByRole("checkbox"));
  await u.click(within(teyit).getByRole("button", { name: `Onayla (${n})` }));
  return screen.findByTestId("toplu-onay-sonucu");
}

beforeEach(() => {
  yerelGorulen = [];
  goruntulenenleriSifirla();
  // Önceki testin `izle` sarmalayıcısı modül düzeyinde kalır: her test düz mock'la başlar.
  yapilandir({ mock: mockIstek });
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("K13' sunucu penceresi (mock core ile aynı)", () => {
  it("görüntüleme kaydından hemen sonra toplu onay ayrı nedenle atlanır; 3 sn sonra geçer", async () => {
    const { caseler } = taslaklariKur(1, 0);
    await analistOturumu();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await api.caseGoruntulendi(caseler[0].id);
    const y1 = await api.topluOnay([caseler[0]]);
    expect(y1.sonuclar[0]).toMatchObject({ durum: "atlandi", neden: YENI_GORUNTULEME_NEDENI });
    vi.advanceTimersByTime(3000);
    const y2 = await api.topluOnay([caseler[0]]);
    expect(y2.sonuclar[0]).toMatchObject({ durum: "onaylandi" });
    // Hiç görülmeyen case eski nedenle atlanır.
    const { caseler: c2 } = taslaklariKur(1, 0);
    expect((await api.topluOnay([c2[0]])).sonuclar[0].neden).toBe("Case en az 3 saniye ekranda kalmadı");
  });

  it("taslak olmayan case'te görüntüleme kaydı açılmaz", async () => {
    const c = mockVerisi().caseler.find((x) => x.durum !== "draft")!;
    await analistOturumu();
    expect(await api.caseGoruntulendi(c.id)).toMatchObject({ ilk_goruntuleme: null, yeni: false });
  });

  it("pencere içinde tıklama: sunucu nedeni ve yeniden deneme notu gösterilir", async () => {
    const { rid, caseler } = taslaklariKur(2);
    await analistOturumu();
    izle((c) =>
      c.path === "/cases/bulk-decision"
        ? {
            sonuclar: [
              { case_id: caseler[0].id, durum: "onaylandi", neden: null, otomatik_kod: null },
              { case_id: caseler[1].id, durum: "atlandi", neden: YENI_GORUNTULEME_NEDENI, otomatik_kod: null },
            ],
            ozet: { onaylandi: 1, atlandi: 1, hata: 0 },
            otomatik_kod: { durum: "kuyrukta", job_id: null, case_sayisi: 1, atlanan: [] },
          }
        : undefined,
    );
    uygulama(`/gereksinimler/${rid}/caseler`);
    const sonuc = await topluOnayVer(userEvent.setup(), 2);
    expect(within(sonuc).getByRole("list", { name: "Onaylanmayan case'ler" })).toHaveTextContent(`#2 Taslak 2 — ${YENI_GORUNTULEME_NEDENI}`);
    expect(within(sonuc).getByTestId("toplu-yeni-goruntuleme")).toHaveTextContent("1 case az önce ekranınıza geldiği için atlandı");
    // job_id yoksa iş sonucu bağlantısı gösterilmez.
    expect(within(sonuc).queryByRole("button", { name: /Kod üretimi sonucunu/ })).toBeNull();
  });
});

describe("Toplu onay: otomatik kod sayısı, atlananlar ve iş sonucu", () => {
  it("mock core gibi: açık PR'lı case sayıya girmez, atlanan listesinde; iş sonucu çekmecesi", async () => {
    const { rid, caseler } = taslaklariKur(2);
    const v = mockVerisi();
    const sablon = v.scriptler.find((s) => s.durum === "pr_open")!;
    v.scriptler.push({ ...JSON.parse(JSON.stringify(sablon)), id: "scr-e4-acik", case_ids: [caseler[1].id], durum: "pr_open" });
    await analistOturumu();
    uygulama(`/gereksinimler/${rid}/caseler`);
    const sonuc = await topluOnayVer(userEvent.setup(), 2);
    expect(within(sonuc).getByTestId("toplu-otokod")).toHaveTextContent(
      "Otomatik kod üretimi: 1 case için web kodu üretimi kuyruğa alındı (tek arka plan işi). 1 case kod üretimine alınmadı",
    );
    expect(within(sonuc).getByRole("list", { name: "Kod üretimine alınmayan case'ler" })).toHaveTextContent("#2 Taslak 2 — Açık PR var");
    const dugme = within(sonuc).getByRole("button", { name: "Kod üretimi sonucunu göster" });
    expect(dugme).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(dugme);
    const is_ = await within(sonuc).findByTestId("kod-uretim-isi");
    await waitFor(() => expect(is_).toHaveTextContent("Kod üretimi işi bitti · 1 case · 1 üretim başladı"));
    expect(within(is_).getByRole("list", { name: "Case başına kod üretimi sonucu" })).toHaveTextContent("#1 Taslak 1");
  });

  it("hepsi atlanırsa 'başlatılmadı' ve nedenler; kapalıysa kapalı", async () => {
    const y = topluKararUyarla({
      sonuclar: [{ case_id: "a", durum: "onaylandi" }],
      ozet: { onaylandi: 1, atlandi: 0, hata: 0 },
      otomatik_kod: { durum: "yok", job_id: null, case_sayisi: 0, atlanan: [{ case_id: "a", neden: "Açık PR var" }, { neden: "kimliksiz" }] },
    });
    expect(y.otomatik_kod?.atlanan).toEqual([{ case_id: "a", neden: "Açık PR var" }]);
    const { topluOtokodMetni } = await import("./CaseReview");
    expect(topluOtokodMetni(y)).toBe("Otomatik kod üretimi başlatılmadı: onaylanan 1 case'in hiçbiri kod üretimine alınmadı (aşağıda nedeni).");
    expect(topluOtokodMetni({ ...y, otomatik_kod: { durum: "yok", job_id: null, case_sayisi: 0 } })).toBe(
      "Otomatik kod üretimi başlatılmadı: üretilecek case yok.",
    );
  });

  it("teyit açılırken otomatik kod ayarı taze okunur; okunamazsa temkinli metin", async () => {
    const { rid } = taslaklariKur(2);
    await analistOturumu();
    let ayarHatasi = false;
    izle((c) => {
      if (c.path === "/automation-settings" && c.method === "GET" && ayarHatasi) throw new Error("okunamadı");
      return undefined;
    });
    uygulama(`/gereksinimler/${rid}/caseler`);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Tümünü onayla (2)" }));
    let teyit = screen.getByRole("group", { name: "Toplu onay teyidi" });
    await waitFor(() => expect(teyit).toHaveTextContent("Onaylanan 2 case için web kodu üretilecek"));
    await u.click(within(teyit).getByRole("button", { name: "Vazgeç" }));

    // Başka bir kullanıcı ayarı kapattı: teyit yeniden açılınca kod üretiminden söz edilmez.
    await api.otomasyonAyariKaydet("otomatik_kod_uretimi", { acik: false });
    await u.click(screen.getByRole("button", { name: "Tümünü onayla (2)" }));
    teyit = screen.getByRole("group", { name: "Toplu onay teyidi" });
    await waitFor(() => expect(teyit).not.toHaveTextContent("web kodu"));
    await u.click(within(teyit).getByRole("button", { name: "Vazgeç" }));

    ayarHatasi = true;
    await u.click(screen.getByRole("button", { name: "Tümünü onayla (2)" }));
    teyit = screen.getByRole("group", { name: "Toplu onay teyidi" });
    await waitFor(() => expect(teyit).toHaveTextContent("Otomatik kod üretimi ayarı okunamadı; açıksa onaylananların web kodu üretilir."));
  });

  it("Özeti kapat sonrası odak body'ye düşmez", async () => {
    const { rid } = taslaklariKur(3, 2);
    await analistOturumu();
    uygulama(`/gereksinimler/${rid}/caseler`);
    const u = userEvent.setup();
    const sonuc = await topluOnayVer(u, 2);
    await u.click(within(sonuc).getByRole("button", { name: "Özeti kapat" }));
    // Taslak kaldı ama görülmedi: "Tümünü onayla (0)" pasif, odak aktif filtre sekmesine.
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    expect(document.activeElement).toHaveClass("sekme");
  });
});

describe("K10: onaydan sonra değişen test verisi", () => {
  it("onaylı case'te anahtarlar uyarıda; değer/özet yok", async () => {
    const { rid, caseler } = taslaklariKur(1);
    const tc = mockVerisi().caseler.find((c) => c.id === caseler[0].id)!;
    tc.icerik.steps[0].data = "{veri:urun.p_001.fiyat}";
    await analistOturumu();
    await api.caseKarari(tc.id, { karar: "approve", icerik_hash: tc.icerik_hash });
    const kayit = (await api.testVerileri()).find((k) => k.anahtar === "urun.p_001.fiyat")!;
    await api.testVerisiGuncelle(kayit.id, { deger: "999,00 TL", beklenen_surum: kayit.surum });
    uygulama(`/gereksinimler/${rid}/caseler`);
    const uyari = await screen.findByTestId("case-veri-degisti");
    expect(uyari).toHaveTextContent("Test verisi onaydan sonra değişti: urun.p_001.fiyat.");
  });

  it("uyarlayıcı: boş dizi alan eklemez; dolu dizi geçer", () => {
    expect(caseOtomasyonAlanlari({ veri_onaydan_sonra_degisen: [] })).not.toHaveProperty("veri_onaydan_sonra_degisen");
    expect(caseOtomasyonAlanlari({ veri_onaydan_sonra_degisen: ["a.b", 3, ""] }).veri_onaydan_sonra_degisen).toEqual(["a.b"]);
  });
});

describe("Uyarlayıcılar: K14 ve kod üretimi işi", () => {
  it("eksik acik/otomatik_case açık sayılmaz", () => {
    const a = otomasyonAyarlariUyarla({});
    expect(a.otomatik_kod_uretimi.acik).toBe(false);
    expect(a.jira_tetik.acik).toBe(false);
    expect(a.jira_tetik.otomatik_case).toBe(false);
    expect(jiraTetikDurumuUyarla({}).acik).toBe(false);
  });

  it("iş yanıtı: core job biçimi (durum + sonuc) ve düz biçim", () => {
    const ic = kodUretimIsiUyarla({
      id: 5,
      durum: "running",
      sonuc: { case_sayisi: 2, sonuclar: [{ case_id: "a", durum: "kuyrukta", script_id: "s1" }, { case_id: "b", durum: "atlandi", neden: "Açık PR var" }] },
    });
    expect(ic).toMatchObject({ job_id: "5", durum: "calisiyor", case_sayisi: 2, ozet: { kuyrukta: 1, atlandi: 1 } });
    expect(ic.sonuclar[0]).toEqual({ case_id: "a", durum: "kuyrukta", neden: null, script_id: "s1" });
    expect(kodUretimIsiUyarla({ durum: "failed", son_hata: "x" }, "j").durum).toBe("hata");
  });
});

describe("K21 metinleri ve etiketler", () => {
  it("test_verisi engel etiketi", () => {
    expect(ENGEL_TURU.test_verisi).toBe("Test verisi çözülemedi (sır tanımsız ya da kayıt yok)");
  });

  it("Otomasyon: akış notu otomatik case ayarına göre", async () => {
    await analistOturumu();
    uygulama("/otomasyon");
    const not = await screen.findByTestId("akis-notu");
    expect(not).toHaveTextContent(AKIS_METNI_OTOMATIK);
    await userEvent.click(screen.getByRole("switch", { name: "PO onayından sonra case'leri otomatik üret" }));
    expect(screen.getByTestId("akis-notu")).toHaveTextContent(AKIS_METNI_ELLE);
  });

  it("tetik ipucu giris_isle kurallarıyla hizalı", () => {
    const ayar = { acik: true, durum: "QA To Do", otomatik_case: true, tabanBekleniyor: false };
    const g = (durum: string, case_toplam = 0, case_onayli = 0, jira_durumu: string | null = null) =>
      ({ durum, sayaclar: { bulgu_acik: 0, case_toplam, case_onayli }, jira_durumu }) as Pick<Gereksinim, "durum" | "sayaclar" | "jira_durumu">;
    expect(tetikIpucu(g("pending_po"), ayar)).toMatchObject({ tetiklenir: true, metin: expect.stringContaining("PO onayından sonra case'ler otomatik üretilir") });
    expect(tetikIpucu(g("in_review"), { ...ayar, otomatik_case: false }).metin).toContain("case üretimini elle başlatın");
    expect(tetikIpucu(g("po_approved"), { ...ayar, otomatik_case: false }).tetiklenir).toBe(false);
    expect(tetikIpucu(g("po_approved"), ayar).tetiklenir).toBe(true);
    expect(tetikIpucu(g("po_approved", 3, 2), ayar).tetiklenir).toBe(false);
    // Yalnız reddedilmiş mi, taslak mı: portal bilemez.
    expect(tetikIpucu(g("po_approved", 3, 0), ayar)).toMatchObject({ tetiklenir: null, metin: expect.stringContaining("Sunucu karar verir") });
    expect(tetikIpucu(g("cases_ready"), ayar)).toMatchObject({ tetiklenir: null, metin: expect.stringContaining("Sunucu karar verir") });
    expect(tetikIpucu(undefined, { ...ayar, tabanBekleniyor: true })).toMatchObject({ tetiklenir: false, metin: expect.stringContaining("taban") });
    expect(tetikIpucu(g("new", 0, 0, "QA To Do"), ayar).tetiklenir).toBe(false);
    expect(tetikIpucu(g("new"), null).tetiklenir).toBeNull();
  });
});

describe("Test verisi: grup temizleme", () => {
  it("düzenlemede boş grup \"\" gider ve grup anahtarın ilk parçasına döner", async () => {
    await analistOturumu();
    const kayit = (await api.testVerileri()).find((k) => k.anahtar === "urun.p_001.fiyat")!;
    await api.testVerisiGuncelle(kayit.id, { grup: "fiyatlar", beklenen_surum: kayit.surum });
    const cagrilar = izle();
    uygulama("/test-verisi");
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "urun.p_001.fiyat düzenle" }));
    const grup = screen.getByLabelText("Grup");
    expect(grup).toHaveAccessibleDescription(GRUP_IPUCU);
    await u.clear(grup);
    await u.click(screen.getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(cagrilar.find((c) => c.method === "PUT")?.govde).toMatchObject({ grup: "" }));
    await waitFor(async () => expect((await api.testVerileri()).find((k) => k.id === kayit.id)?.grup).toBe("urun"));
  });
});

describe("ScriptDetay: 'Test verisi değişti' Kod listesiyle aynı kural", () => {
  it("süren üretimde ve yerine yenisi üretilmiş eski kayıtta uyarı yok; güncelde var", async () => {
    const v = mockVerisi();
    const s = v.scriptler.find((x) => x.case_ids.length > 0 && x.durum === "pr_open")!;
    Object.assign(s, { durum: "verifying", veri_degisti: true, veri_degisen: ["urun.p_001.ad"] });
    await oturumAc("muhendis");
    const { unmount } = uygulama(`/kod/${s.id}`);
    await screen.findAllByText(s.baslik);
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText("Test verisi değişti; yeniden üretin")).toBeNull();
    unmount();

    Object.assign(s, { durum: "merged", platform: "web" });
    v.scriptler.push({ ...JSON.parse(JSON.stringify(s)), id: "scr-e4-yeni", durum: "pr_open", olusturma: "2099-01-01T00:00:00Z", veri_degisti: false });
    const r2 = uygulama(`/kod/${s.id}`);
    await screen.findAllByText(s.baslik);
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText("Test verisi değişti; yeniden üretin")).toBeNull();
    r2.unmount();

    v.scriptler = v.scriptler.filter((x) => x.id !== "scr-e4-yeni");
    uygulama(`/kod/${s.id}`);
    expect(await screen.findByText("Test verisi değişti; yeniden üretin")).toBeInTheDocument();
  });
});
