// Faz 5: story başına manuel baz değer (gereksinim detayı + Kontrol Kulesi kazancı), demo yol
// haritası (14 adım + locator yolu, REPLAY/strict/değerlendirme), triage kanıt bağlantıları ve demo
// durum ipuçları.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ApiError, yapilandir } from "../api/http";
import { mockVerisi } from "../api/mock/handlers";
import type { BugTaslagi, GereksinimDetay, HataAnalizi, Kosu, Script, TestCase } from "../api/types";
import { bazYanitiUyarla, demoDurumuUyarla, gereksinimBazi, hazirlikUyarla, kazancOzeti, manuelBazUyarla } from "../api/uyumFaz5";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { bazFormuDogrula } from "../components/BazDegerKarti";
import { demoAdimlari, degerlendirmeOzeti, ilerleme, locatorAdimlari, modOzeti, type YolGirdisi } from "../lib/yolHaritasi";
import { oturumAc } from "../test/yardimci";
import { caseKazanci, KAZANC_REPLAY_NEDENI } from "./CaseReview";
import { denemeEtiketi, kanitGruplari } from "./HataDetay";

function Konum() {
  const k = useLocation();
  return <div data-testid="konum">{k.pathname + k.search}</div>;
}

function uygulama(yol: string) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          <Rotalar />
          <Routes>
            <Route path="*" element={<Konum />} />
          </Routes>
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

// ------------------------------------------------------------------ uyarlayıcılar

describe("manuel baz değer uyarlayıcısı", () => {
  it("ölçüm, varsayılan ve ölçülmedi; değeri olmayan 'ölçüm' ölçüm sayılmaz; alan yoksa undefined", () => {
    expect(manuelBazUyarla({ deger_s: 1800, kaynak: "olcum", giren: "analist", zaman: "2026-11-01T10:00:00Z", not: "F0 kronometre" })).toEqual({
      deger_s: 1800,
      kaynak: "olcum",
      giren: "analist",
      zaman: "2026-11-01T10:00:00Z",
      not: "F0 kronometre",
    });
    expect(manuelBazUyarla({ deger_ms: 900_000, kaynak: "default" })).toMatchObject({ deger_s: 900, kaynak: "varsayilan" });
    expect(manuelBazUyarla({ deger_s: null, kaynak: "olcum" })).toMatchObject({ deger_s: null, kaynak: "olculmedi" });
    expect(manuelBazUyarla({ deger_s: 0, kaynak: "measured" })).toMatchObject({ kaynak: "olculmedi" });
    expect(manuelBazUyarla(null)).toMatchObject({ deger_s: null, kaynak: "olculmedi" });
    expect(manuelBazUyarla(undefined)).toBeUndefined();
    expect(gereksinimBazi({ id: "x" })).toBeUndefined();
    expect(gereksinimBazi({ baseline: { saniye: 60, source: "manual", by: "po" } })).toMatchObject({ deger_s: 60, kaynak: "olcum", giren: "po" });
    // PUT yanıtı baz değer ya da gereksinim detayı olabilir.
    expect(bazYanitiUyarla({ deger_s: 120, kaynak: "olcum" })).toMatchObject({ deger_s: 120 });
    expect(bazYanitiUyarla({ id: "r", manuel_baz: { deger_s: 120, kaynak: "olcum" } })).toMatchObject({ deger_s: 120 });
    expect(bazYanitiUyarla({ durum: "ok" })).toBeUndefined();
  });

  it("core şekli (Faz 5 core şeridi): detay `baseline` (kaynak null = ölçülmedi), PUT yanıtı `{baseline, degisti, gecmis}`", () => {
    expect(gereksinimBazi({ baseline: { deger_s: null, deger_ms: null, kaynak: null, etiket: "ölçülmedi", giren: null, zaman: null, not: null } })).toMatchObject({
      deger_s: null,
      kaynak: "olculmedi",
    });
    expect(gereksinimBazi({ baseline: { deger_s: 1200, kaynak: "varsayilan", not: "TP_MANUAL_BASELINE_S (varsayılan…)" } })).toMatchObject({ deger_s: 1200, kaynak: "varsayilan" });
    expect(
      bazYanitiUyarla({ requirement_id: "r", jira_key: "TPD-1", baseline: { deger_s: 2700, kaynak: "olcum", giren: "analist", zaman: "z", not: "F0" }, degisti: true, gecmis: [] }),
    ).toMatchObject({ deger_s: 2700, kaynak: "olcum", giren: "analist" });
    const [h] = hazirlikUyarla([{ requirement_id: "r", story_key: "TPD-1", toplam_ms: 1000, manuel_baz_ms: null, manuel_baz_kaynagi: null }]);
    expect(h).toMatchObject({ baz_kaynagi: "olculmedi", manuel_baz_ms: null });
    const [v] = hazirlikUyarla([{ requirement_id: "r", toplam_ms: 1000, manuel_baz_ms: 2000, manuel_baz_kaynagi: "varsayilan", kazanc_orani: 0.5 }]);
    expect(kazancOzeti([v]).oran).toBeNull();
  });

  it("hazırlık satırları: kaynak bildirmeyen eski core'da baz değer varsayılandır (kazanca girmez)", () => {
    const [eski] = hazirlikUyarla([{ requirement_id: "r1", story_key: "TPD-1", toplam_ms: 600_000, manuel_baz_ms: 1_800_000, kazanc_orani: 0.66 }]);
    expect(eski).toMatchObject({ baz_kaynagi: "varsayilan", manuel_baz_ms: 1_800_000 });
    const oz = kazancOzeti([eski]);
    expect(oz.oran).toBeNull();
    expect(oz.kapsam).toMatch(/Kazanç hesaplanmaz/);
    expect(oz.kapsam).toMatch(/1 story varsayılan baz değerli/);
  });

  it("kazanç yalnızca ölçülmüş story'lerden; REPLAY'de süre yalnız review; kapsam metni sayıları söyler", () => {
    const satirlar = hazirlikUyarla([
      { requirement_id: "r1", story_key: "TPD-1", ai_sure_ms: null, ai_olculmedi: true, review_sure_ms: 600_000, toplam_ms: null, manuel_baz_ms: 1_800_000, baz_kaynagi: "olcum" },
      { requirement_id: "r2", story_key: "TPD-4", ai_sure_ms: 5000, review_sure_ms: 300_000, toplam_ms: 305_000, manuel_baz_ms: 1_200_000, baz_kaynagi: "varsayilan", kazanc_orani: 0.75 },
      { requirement_id: "r3", story_key: "TPD-3", toplam_ms: 100_000, manuel_baz_ms: null },
    ]);
    const oz = kazancOzeti(satirlar);
    // REPLAY'de yalnız review süresi bilinen story başlık kazancına girmez (core kazanca_girer).
    expect(oz.hesaplanan).toBe(0);
    expect(oz.replay_haric).toBe(1);
    expect(oz.oran).toBeNull();
    expect(oz.storyler[0]).toMatchObject({ yalniz_review: true, sure_ms: 600_000 });
    expect(oz.storyler[0].kazanc).toBeCloseTo(1 - 600_000 / 1_800_000);
    // Varsayılan baz değerli satırda core kazanç verse de portal kullanmaz.
    expect(oz.storyler[1].kazanc).toBeNull();
    expect(oz.kapsam).toMatch(/^Kazanç hesaplanmaz \(REPLAY\)/);
    expect(oz.kapsam).toMatch(/1 story varsayılan baz değerli \(story için ölçülmedi\); 1 story'de baz değer yok; 1 story REPLAY'de yalnız review/);
  });

  it("ölçülmüş + AI + review story varsa başlık yalnızca ondan; kapsam REPLAY hariç tutulanı söyler", () => {
    const satirlar = hazirlikUyarla([
      { requirement_id: "r1", story_key: "TPD-1", ai_sure_ms: null, ai_olculmedi: true, review_sure_ms: 600_000, toplam_ms: null, manuel_baz_ms: 1_800_000, baz_kaynagi: "olcum" },
      { requirement_id: "r2", story_key: "TPD-2", ai_sure_ms: 5000, review_sure_ms: 295_000, toplam_ms: 300_000, manuel_baz_ms: 1_200_000, manuel_baz_kaynagi: "olcum", kazanca_girer: true },
    ]);
    const oz = kazancOzeti(satirlar);
    expect(oz.hesaplanan).toBe(1);
    expect(oz.oran).toBeCloseTo(0.75);
    expect(oz.kapsam).toBe(
      "Kazanç yalnızca ölçülmüş baz değerli 1/2 story'den (TPD-2); hesaba katılmayan: 1 story REPLAY'de yalnız review süresiyle (AI süresi ölçülmedi; yüzde verimlilik iddiası değildir).",
    );
  });

  it("toplam kazanç core ile aynı formül: 1 − Σ süre / Σ ölçülmüş baz (ortalama oran değil)", () => {
    const satirlar = hazirlikUyarla([
      { requirement_id: "r1", story_key: "TPD-1", toplam_ms: 600_000, toplam_yontemi: "yalniz_review", ai_olculmedi: true, manuel_baz_ms: 3_600_000, manuel_baz_kaynagi: "olcum" },
      { requirement_id: "r2", story_key: "TPD-2", toplam_ms: 1_200_000, manuel_baz_ms: 2_400_000, manuel_baz_kaynagi: "olcum" },
      { requirement_id: "r3", story_key: "TPD-3", toplam_ms: 0, manuel_baz_ms: 1_000_000, manuel_baz_kaynagi: "olcum" },
    ]);
    const oz = kazancOzeti(satirlar);
    // 0 ms hazırlık ölçüm değildir; REPLAY yalnız-review satırı başlığa girmez.
    expect(oz.hesaplanan).toBe(1);
    expect(oz.replay_haric).toBe(1);
    expect(oz.oran).toBeCloseTo(1 - 1_200_000 / 2_400_000);
    expect(oz.storyler[0].yalniz_review).toBe(true);
  });

  it("form doğrulaması: süre, saniye aralığı, üst sınır, not ve 'gerçek ölçüm' onayı", () => {
    expect(bazFormuDogrula("", "", "not", true)).toEqual({ hata: "Ölçülen süre girilmedi." });
    expect(bazFormuDogrula("-1", "", "not", true)).toMatchObject({ hata: expect.stringMatching(/tam sayı/) });
    expect(bazFormuDogrula("2,5", "", "not", true)).toMatchObject({ hata: expect.stringMatching(/tam sayı/) });
    expect(bazFormuDogrula("1", "60", "not", true)).toMatchObject({ hata: "Saniye 0–59 arasında olmalı." });
    expect(bazFormuDogrula("2401", "", "not", true)).toMatchObject({ hata: expect.stringMatching(/en fazla 40 saat/) });
    expect(bazFormuDogrula("30", "", "  ", true)).toMatchObject({ hata: expect.stringMatching(/Ölçüm notu gerekli/) });
    // Core ile aynı: boşluk dışı en az 3 karakter.
    expect(bazFormuDogrula("30", "", "a b", true)).toMatchObject({ hata: expect.stringMatching(/Ölçüm notu gerekli/) });
    expect(bazFormuDogrula("30", "", "x".repeat(501), true)).toMatchObject({ hata: expect.stringMatching(/en fazla 500/) });
    expect(bazFormuDogrula("30", "15", "İsmail, F0", false)).toMatchObject({ hata: expect.stringMatching(/tahmin girilmez/) });
    expect(bazFormuDogrula("30", "15", " İsmail, F0 ", true)).toEqual({ deger_s: 1815, not: "İsmail, F0" });
  });

  it("/demo/status: model kipi, strict, değerlendirme ve ön koşul normalize edilir", () => {
    const d = demoDurumuUyarla({
      forge: { main: "abc" },
      uygulama: {},
      model: { mod: "replay", replay_strict: "1" },
      degerlendirme: [{ bundle_id: "triage", version: 2, status: "pending", label: "canlı değerlendirme bekliyor" }],
      onarim_on_kosulu: { hazir: false, son_yesil_kosu: null, yonerge: "make demo-reset" },
      locator_demo: { destekleniyor: false, neden: "GitHub kipi" },
    });
    expect(d.model).toMatchObject({ mod: "replay", replay_strict: true });
    expect(d.degerlendirme).toEqual([{ paket: "triage", surum: 2, durum: "pending", etiket: "canlı değerlendirme bekliyor" }]);
    expect(d.onarim_on_kosulu).toMatchObject({ hazir: false, yonerge: "make demo-reset" });
    expect(d.locator_demo).toEqual({ destekleniyor: false, neden: "GitHub kipi", kip: null });
    expect(demoDurumuUyarla({ forge: {}, uygulama: {}, locator_demo: { destekleniyor: true, neden: null, kip: "github" } }).locator_demo?.kip).toBe("github");
    expect(demoDurumuUyarla({}).model).toBeNull();
  });
});

// ------------------------------------------------------------------ gereksinim detayı: baz değer kartı

describe("Gereksinim detayı: manuel baz değer", () => {
  it("analist ölçüm girer (doğrulamayla), kaynak 'Ölçüm' + giren/not görünür, sonra siler", async () => {
    const u = userEvent.setup();
    await oturumAc("analist");
    uygulama("/gereksinimler/req-tpd-1");
    const kart = await screen.findByRole("region", { name: "Manuel baz değer" });
    expect(within(kart).getByTestId("baz-deger")).toHaveTextContent("ölçülmedi");
    expect(within(kart).getByText("Ölçülmedi")).toBeInTheDocument();
    await u.click(within(kart).getByRole("button", { name: "Ölçüm gir" }));
    const form = within(kart).getByRole("form", { name: "Manuel baz değer ölçümü" });
    await u.type(within(form).getByLabelText("Dakika"), "45");
    await u.click(within(form).getByRole("button", { name: "Kaydet" }));
    expect(within(form).getByRole("alert")).toHaveTextContent(/Ölçüm notu gerekli/);
    await u.type(within(form).getByLabelText("Ölçüm notu (kim, nasıl ölçtü)"), "İsmail, F0 haftası kronometre");
    await u.click(within(form).getByRole("button", { name: "Kaydet" }));
    expect(within(form).getByRole("alert")).toHaveTextContent(/tahmin girilmez/);
    await u.click(within(form).getByRole("checkbox"));
    await u.click(within(form).getByRole("button", { name: "Kaydet" }));
    await waitFor(() => expect(within(kart).getByTestId("baz-deger-sure")).toHaveTextContent("45 dk 00 sn"));
    expect(within(kart).getByText("Ölçüm")).toBeInTheDocument();
    // Giren kullanıcı görünen adıyla gösterilir (yalnızca gösterim; kayıtta kullanıcı adı).
    expect(kart).toHaveTextContent("Cengizhan Gunaydin · Analist");
    expect(kart).toHaveTextContent("İsmail, F0 haftası kronometre");
    expect(mockVerisi().manuelBazlar?.["req-tpd-1"]).toMatchObject({ deger_s: 2700, kaynak: "olcum", giren: "analist" });
    expect(mockVerisi().denetim.at(-1)).toMatchObject({ eylem: "requirement.baseline_set", nesne: "TPD-1" });

    await u.click(within(kart).getByRole("button", { name: "Ölçümü sil" }));
    await u.click(within(kart).getByRole("button", { name: "Evet, sil" }));
    await waitFor(() => expect(within(kart).getByText("Ölçülmedi")).toBeInTheDocument());
    expect(mockVerisi().manuelBazlar?.["req-tpd-1"]).toBeUndefined();
  });

  it("PO da girebilir; testçi için düğme pasif ve sunucu (mock) rolü reddeder", async () => {
    await oturumAc("testci");
    uygulama("/gereksinimler/req-tpd-1");
    const kart = await screen.findByRole("region", { name: "Manuel baz değer" });
    expect(within(kart).getByRole("button", { name: "Ölçüm gir" })).toBeDisabled();
    await expect(api.bazDegerKaydet("req-tpd-1", { deger_s: 60, not: "deneme" })).rejects.toMatchObject({ status: 403 });
    await oturumAc("po");
    await expect(api.bazDegerKaydet("req-tpd-1", { deger_s: 60, not: "PO ölçümü" })).resolves.toMatchObject({ kaynak: "olcum", giren: "po" });
    // Sunucu tarafı doğrulama (core gibi): tam saniye, 1..144000 (40 saat), not 3..500.
    await expect(api.bazDegerKaydet("req-tpd-1", { deger_s: 0, not: "x yz" })).rejects.toBeInstanceOf(ApiError);
    await expect(api.bazDegerKaydet("req-tpd-1", { deger_s: 150_000, not: "x yz" })).rejects.toMatchObject({ status: 422 });
    await expect(api.bazDegerKaydet("req-tpd-1", { deger_s: 60, not: "x" })).rejects.toMatchObject({ status: 422 });
  });

  it("çekirdek baz değer alanını sunmuyorsa 'bilinmiyor' der, form yoktur (değer uydurulmaz)", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const j = (status: number, govde: unknown) => Promise.resolve(new Response(JSON.stringify(govde), { status, headers: { "Content-Type": "application/json" } }));
    const detay = { ...mockVerisi().gereksinimler[0] } as Partial<GereksinimDetay>;
    delete detay.manuel_baz;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url === "/api/openapi.json") return j(200, { paths: { "/auth/me": { get: {} }, "/requirements": { get: {} }, "/requirements/{id}": { get: {} }, "/requirements/{id}/findings": { get: {} } } });
        if (url === "/api/auth/me") return j(200, { id: "u1", kullanici_adi: "analist", rol: "analyst" });
        if (url.startsWith("/api/requirements/req-tpd-1/findings")) return j(200, []);
        if (url.startsWith("/api/requirements/req-tpd-1")) return j(200, detay);
        return j(404, { detail: "Not Found" });
      }),
    );
    try {
      uygulama("/gereksinimler/req-tpd-1");
      const kart = await screen.findByRole("region", { name: "Manuel baz değer" });
      expect(within(kart).getByTestId("baz-deger-yok")).toHaveTextContent("bilinmiyor");
      expect(within(kart).queryByRole("button", { name: "Ölçüm gir" })).toBeNull();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

// ------------------------------------------------------------------ Kontrol Kulesi kazancı

describe("Kontrol Kulesi: kazanç yalnızca ölçülmüş story'lerde", () => {
  it("ölçüm yokken 'ölçülmüş baz yok'; TPD-1'e ölçüm girilince kazanç + kapsam metni + story tablosu", async () => {
    await oturumAc("sunucu");
    const ilk = uygulama("/kontrol-kulesi");
    expect(await screen.findByTestId("hazirlik-kazanci")).toHaveTextContent("ölçülmüş baz yok");
    expect(screen.getByTestId("kazanc-kapsam")).toHaveTextContent(/Kazanç hesaplanmaz/);
    ilk.unmount();

    await oturumAc("analist");
    await api.bazDegerKaydet("req-tpd-1", { deger_s: 3600, not: "F0 ölçümü (analist)" });
    await oturumAc("sunucu");
    uygulama("/kontrol-kulesi");
    // Örnek veri REPLAY: ölçüm girilse de başlık yüzdesi gösterilmez (verimlilik iddiası değil);
    // story oranı tabloda "(REPLAY: yalnız review)" etiketiyle kalır.
    const kazanc = await screen.findByTestId("hazirlik-kazanci");
    expect(kazanc).toHaveTextContent("REPLAY: hesaplanmaz");
    expect(screen.getByTestId("kazanc-kapsam")).toHaveTextContent(/Kazanç hesaplanmaz \(REPLAY\)/);
    const satir = screen.getByTestId("hazirlik-TPD-1");
    expect(satir).toHaveTextContent("1 sa 00 dk");
    expect(satir).toHaveTextContent("Ölçüm");
    expect(satir).toHaveTextContent("REPLAY: yalnız review");
    // Diğer story'lerde kazanç yok.
    const satirlar = screen.getAllByTestId(/^hazirlik-TPD-/).filter((x) => x.tagName === "TR" && x !== satir);
    for (const s of satirlar) expect(s.querySelector("td:last-child")).toHaveTextContent("—");
  });
});

// ------------------------------------------------------------------ demo yol haritası

const BOS: YolGirdisi = { gereksinim: null, caseler: [], scriptler: [], kosular: [], hatalar: [], bugTaslaklari: [], kule: null, demo: null };

describe("demo yol haritası: türetme", () => {
  it("boş durumda hiçbir adım tamam değildir; kip ve değerlendirme 'bilinmiyor' (live uydurulmaz)", () => {
    const a = demoAdimlari(BOS);
    expect(a).toHaveLength(14);
    expect(a.every((x) => x.hal === "bekliyor")).toBe(true);
    expect(a[0].ipucu).toMatch(/Jira'dan çek/);
    expect(ilerleme(a)).toMatchObject({ tamam: 0, toplam: 14 });
    expect(modOzeti(BOS)).toMatchObject({ mod: null, kaynak: "yok" });
    expect(degerlendirmeOzeti(BOS)).toMatchObject({ kaynak: "yok" });
    expect(locatorAdimlari(BOS).every((x) => x.hal === "bekliyor")).toBe(true);
  });

  it("örnek veri (ana demo yolu): adımlar gerçek nesnelerden; Sauce yerine yerel yedek açıkça", async () => {
    await oturumAc("sunucu");
    const v = mockVerisi();
    const g = await api.gereksinim("req-tpd-1");
    const girdi: YolGirdisi = {
      gereksinim: g,
      caseler: await api.caseler(g.id),
      scriptler: await api.scriptler(),
      kosular: await api.kosular(),
      hatalar: await api.hatalar(),
      bugTaslaklari: await api.bugTaslaklari(),
      kule: await api.kontrolKulesi(),
      demo: await api.demoDurumu(),
    };
    // Örnek veride story PR'ları açık (merge yok): CI koşuları story'ye sayılmaz.
    expect(demoAdimlari(girdi).slice(7, 11).map((x) => x.hal)).toEqual(["bekliyor", "bekliyor", "bekliyor", "bekliyor"]);
    // PR'lar merge edilmiş olsa da koşular (28–29 Ekim) merge'den (30 Kasım) önceyse sayılmaz.
    girdi.scriptler = girdi.scriptler.map((s) =>
      s.pr ? { ...s, durum: "merged" as const, pr: { ...s.pr, durum: "merged" as const, merge_zamani: "2026-11-30T12:00:00Z" } } : s,
    );
    expect(demoAdimlari(girdi)[8].hal).toBe("bekliyor");
    // Story merge'ünden sonra koşmuş gibi (adım 8–11 yalnız story koşularını sayar).
    girdi.kosular = girdi.kosular.map((k) => ({ ...k, baslangic: "2026-12-01T00:00:00Z" }));
    const a = demoAdimlari(girdi);
    expect(a[0]).toMatchObject({ hal: "tamam", baglanti: { yol: "/gereksinimler/req-tpd-1" } });
    // 9. adım yalnızca gerçek bir Sauce koşusu varsa "tamam"; yoksa yerel yedek açıkça yazılır.
    const sauce = girdi.kosular.some((k) => k.kaynak === "sauce");
    if (sauce) expect(a[8]).toMatchObject({ hal: "tamam", kanit: expect.stringMatching(/Sauce Labs'ta da koştu/) });
    const yerelGirdi = { ...girdi, kosular: girdi.kosular.filter((k) => k.kaynak !== "sauce") };
    expect(demoAdimlari(yerelGirdi)[8]).toMatchObject({ hal: "yedek", kanit: expect.stringMatching(/Sauce Labs kimliği yok/) });
    // GitHub kipi: Sauce, GitHub koşusunun içinde bir job (sauce_durum). Koştuysa tamam; ulaşılamadıysa
    // nedeniyle yedek — "kimlik yok" denmez.
    const ghKosu = (d: "passed" | "error") =>
      yerelGirdi.kosular.map((k, i) => (i === 0 ? { ...k, kaynak: "github" as const, sauce_durum: d, sauce_neden: d === "error" ? "oturum sınırı dolu" : null } : k));
    expect(demoAdimlari({ ...yerelGirdi, kosular: ghKosu("passed") })[8]).toMatchObject({ hal: "tamam", kanit: expect.stringMatching(/Sauce Labs'ta da koştu/) });
    const ulasilamadi = demoAdimlari({ ...yerelGirdi, kosular: ghKosu("error") })[8];
    expect(ulasilamadi).toMatchObject({ hal: "yedek", kanit: expect.stringMatching(/ulaşılamadı \(oturum sınırı dolu\)/) });
    expect(ulasilamadi.kanit).not.toMatch(/kimliği yok/);
    // Her bağlantı portal içi bir ekrana çıkar.
    for (const x of a) if (x.baglanti) expect(x.baglanti.yol.startsWith("/")).toBe(true);
    expect(v.gereksinimler.length).toBeGreaterThan(0);
    expect(modOzeti(girdi)).toMatchObject({ mod: "replay", kaynak: "cekirdek", strict: false });
    expect(degerlendirmeOzeti(girdi).metin).toMatch(/7\/7 prompt paketi canlı değerlendirme bekliyor/);
  });

  it("kod/kırma/merge/triage/bug adımları: C2 kırma ✓, C3 ürün hatası → TPD-5'e bağlandı", () => {
    const g = { id: "r1", jira_key: "TPD-1", durum: "done", kaynak: "jira", kabul_kriterleri: [{ ref: "AC1", metin: "" }], kontrol_turu: 2, kontrol_turu_ust_sinir: 3, po: { durum: "approved", onaylayan: "po@sim.local", zaman: null, kanal: "jira", onaylanan_hash: "h" }, icerik_hash: "h", sayaclar: { bulgu_acik: 0, case_toplam: 2, case_onayli: 2 } } as unknown as GereksinimDetay;
    const c = (n: number) => ({ id: `c${n}`, requirement_id: "r1", sira_no: n, durum: "published", jira_test_key: `TPD-${8 + n}`, mode: "replay" }) as unknown as TestCase;
    const bv = (durum: string) => ({ durum, asamalar: [] });
    const scriptler = [
      { id: "s2", case_ids: ["c2"], requirement_key: "TPD-1", durum: "merged", pr: { number: 3, durum: "merged", merge_eden: "muhendis", merge_zamani: "2026-11-01T10:00:00Z" }, break_verify: bv("passed"), zayif_test: false, yerel_sinif: "gecti", engel: null, mode: "replay", olusturma: "2026-11-01T09:00:00Z" },
      { id: "s3", case_ids: ["c3"], requirement_key: "TPD-1", durum: "blocked", pr: null, break_verify: bv("not_started"), zayif_test: false, yerel_sinif: "defect_adayi", engel: { tur: "defect_candidate", neden: null }, mode: "replay", olusturma: "2026-11-01T09:00:00Z", failure_id: "f3" },
    ] as unknown as Script[];
    const kosu = (id: string, tetik: string) => ({ id, tetik, kaynak: "local", durum: "passed", baslangic: `2026-11-01T1${id}:00:00Z`, junit_url: "/api/j", allure_url: "/api/a" }) as unknown as Kosu;
    const hatalar = [{ id: "f3", script_id: "s3", sinif: "product_defect", karar_kaynagi: "rule", test_adi: "TPD-1 C3 6 adet", zaman: "2026-11-01T09:30:00Z", oneri: { tur: "bug_draft", bug_draft_id: "b1" }, mode: null }] as unknown as HataAnalizi[];
    const buglar = [{ id: "b1", icerik: { story_key: "TPD-1" }, durum: "published", karar: "link", link_key: "TPD-5", jira_key: "TPD-5", mode: "replay" }] as unknown as BugTaslagi[];
    const a = demoAdimlari({ ...BOS, gereksinim: g, caseler: [c(2), c(3)], scriptler, kosular: [kosu("1", "push"), kosu("2", "deploy")], hatalar, bugTaslaklari: buglar });
    const hal = (n: number) => a[n - 1].hal;
    expect([2, 3, 4, 5, 6, 7, 8, 10, 12, 13, 14].map(hal)).toEqual(Array(11).fill("tamam"));
    expect(a[4].kanit).toBe("PR: C2 · defect adayı: C3 (PR yok)");
    expect(a[5].kanit).toMatch(/Test hata yakalıyor ✓ C2/);
    expect(a[6].kanit).toMatch(/son: muhendis/);
    expect(a[7].kanit).toBe("Tetikler: push, deploy · 2 koşu");
    expect(hal(9)).toBe("yedek");
    expect(hal(11)).toBe("bekliyor"); // Kontrol Kulesi okunmadı: tamam sayılmaz
    expect(a[11].baglanti).toEqual({ yol: "/hatalar/f3", etiket: "Triage" });
    expect(a[13].kanit).toBe("TPD-5'e bağlandı");
  });

  it("locator yolu: ön koşul yoksa yönerge; kırık + triage + PR; GitHub kipinde engel", () => {
    const demo = demoDurumuUyarla({ forge: { testid: "cart-add" }, uygulama: {}, locator_durumu: "kirik", onarim_on_kosulu: { hazir: true, son_yesil_kosu: { run_id: "k1", commit: "abcdef0123", tetik: "push" } } });
    const loc = { id: "f1", sinif: "test_maintenance", zaman: "2026-11-01T10:00:00Z", oneri: { tur: "locator_fix", durum: "pr_open" } } as unknown as HataAnalizi;
    const a = locatorAdimlari({ demo, hatalar: [loc], kosular: [] });
    expect(a.map((x) => x.hal)).toEqual(["tamam", "tamam", "tamam", "tamam", "bekliyor"]);
    expect(a[0].kanit).toBe("Son yeşil: push abcdef01");
    const yok = locatorAdimlari({ demo: demoDurumuUyarla({ forge: {}, uygulama: {}, onarim_on_kosulu: { hazir: false, yonerge: "make demo-reset" } }), hatalar: [], kosular: [] });
    expect(yok[0]).toMatchObject({ hal: "bekliyor", ipucu: "make demo-reset" });
    const gh = locatorAdimlari({ demo: demoDurumuUyarla({ forge: {}, uygulama: {}, locator_demo: { destekleniyor: false, neden: "GitHub kipi" } }), hatalar: [], kosular: [] });
    expect(gh).toEqual([expect.objectContaining({ hal: "engel", kanit: "GitHub kipi" })]);
  });
});

describe("demo yol haritası: ekran", () => {
  it("sunucunun açılış ekranı: 14 adım, locator yolu, REPLAY/strict/değerlendirme şeridi, bağlantılar", async () => {
    await oturumAc("sunucu");
    uygulama("/");
    await waitFor(() => expect(screen.getByTestId("konum")).toHaveTextContent("/yol-haritasi"));
    expect(await screen.findByRole("heading", { level: 1, name: "Demo yol haritası" })).toBeInTheDocument();
    const liste = screen.getByRole("list", { name: "14 adımlı demo akışı" });
    expect(within(liste).getAllByRole("listitem")).toHaveLength(14);
    expect(screen.getByRole("list", { name: "Locator kırılma yolu" })).toBeInTheDocument();
    expect(screen.getByTestId("yh-mod")).toHaveTextContent("REPLAY");
    expect(screen.getByTestId("yh-strict")).toHaveTextContent("kapalı");
    expect(screen.getByTestId("yh-degerlendirme")).toHaveTextContent("canlı değerlendirme bekliyor");
    expect(screen.getByTestId("yh-ilerleme")).toHaveTextContent(/\d+\/14/);
    expect(within(screen.getByTestId("yh-adim-1")).getByRole("link", { name: "Story'yi aç →" })).toHaveAttribute("href", "/gereksinimler/req-tpd-1");
    expect(within(screen.getByTestId("yh-adim-11")).getByRole("link", { name: /Kontrol Kulesi/ })).toHaveAttribute("href", "/kontrol-kulesi");
    // Menüde yeni ekran ve sunucu odağı.
    const menu = screen.getByRole("navigation", { name: "Ana menü" });
    expect(within(menu).getByRole("link", { name: /Demo yol haritası/ })).toHaveAttribute("href", "/yol-haritasi");
  });

  it("canlı derleme: okunamayan uçlar listelenir, ilgili adımlar 'tamam' sayılmaz", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    const j = (status: number, govde: unknown) => Promise.resolve(new Response(JSON.stringify(govde), { status, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url === "/api/openapi.json") return j(200, { paths: { "/auth/me": { get: {} }, "/requirements": { get: {} } } });
        if (url === "/api/auth/me") return j(200, { id: "u1", kullanici_adi: "sunucu", rol: "presenter" });
        if (url.startsWith("/api/requirements")) return j(200, []);
        return j(404, { detail: "Not Found" });
      }),
    );
    try {
      uygulama("/yol-haritasi");
      expect(await screen.findByText(/Bazı kaynaklar okunamadı/)).toBeInTheDocument();
      expect(screen.getByText("Koşular (bu fazda yok)")).toBeInTheDocument();
      expect(screen.getByText("TPD-1 henüz yok")).toBeInTheDocument();
      expect(screen.getByTestId("yh-ilerleme")).toHaveTextContent("0/14");
      expect(screen.getByTestId("yh-mod")).toHaveTextContent("bilinmiyor");
      for (const li of screen.getAllByTestId(/^yh-adim-/)) expect(li).not.toHaveAttribute("data-hal", "tamam");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

// ------------------------------------------------------------------ kanıt bağlantıları

describe("triage kanıt bağlantıları", () => {
  it("aynı türün deneme kopyaları tek satırda deneme numarasıyla; aynı adres bir kez", () => {
    const g = kanitGruplari([
      { etiket: "Playwright trace", url: "/api/a/runs/k/x-retry1/trace.zip", tur: "trace" },
      { etiket: "Ekran görüntüsü", url: "/api/a/runs/k/x-retry1/test-failed-1.png", tur: "screenshot" },
      { etiket: "Hata anı sayfa snapshot'ı (error-context)", url: "/api/a/runs/k/x-retry1/error-context.md", tur: "error_context" },
      { etiket: "trace", url: "/api/a/runs/k/x/trace.zip", tur: "trace" },
      { etiket: "screenshot", url: "/api/a/runs/k/x/test-failed-1.png", tur: "screenshot" },
      { etiket: "error-context", url: "/api/a/runs/k/x/error-context.md", tur: "error-context" },
      { etiket: "trace", url: "/api/a/runs/k/x-retry1/trace.zip", tur: "trace" },
    ]);
    expect(g.map((x) => x.etiket)).toEqual(["Playwright trace", "Ekran görüntüsü", "Hata anı sayfa snapshot'ı (error-context)"]);
    expect(g[0].linkler).toEqual([
      { etiket: "1. deneme", url: "/api/a/runs/k/x/trace.zip" },
      { etiket: "2. deneme", url: "/api/a/runs/k/x-retry1/trace.zip" },
    ]);
    expect(kanitGruplari([{ etiket: "Video", url: null }])).toEqual([{ etiket: "Video", linkler: [{ etiket: "Video", url: null }] }]);
    expect(denemeEtiketi("/x-retry2/a.zip")).toBe("3. deneme");
    expect(denemeEtiketi(null)).toBeNull();
  });
});

// ------------------------------------------------------------------ demo durum ipuçları

describe("Demo kontrolleri: durum ipuçları", () => {
  afterEach(() => vi.unstubAllGlobals());

  function sahteCore(durum: Record<string, unknown>) {
    const j = (status: number, govde: unknown) => Promise.resolve(new Response(JSON.stringify(govde), { status, headers: { "Content-Type": "application/json" } }));
    return vi.fn().mockImplementation((url: string) => {
      if (url === "/api/openapi.json")
        return j(200, { paths: { "/auth/me": { get: {} }, "/demo/status": { get: {} }, "/runs": { get: {} }, "/demo/break-locator": { post: {} }, "/demo/reset": { post: {} } } });
      if (url === "/api/auth/me") return j(200, { id: "u1", kullanici_adi: "sunucu", rol: "presenter" });
      if (url === "/api/demo/status") return j(200, durum);
      if (url.startsWith("/api/runs")) return j(200, []);
      return j(404, { detail: "Not Found" });
    });
  }

  it("yeşil temel koşu yoksa kırma pasif ve yönerge görünür", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    vi.stubGlobal(
      "fetch",
      sahteCore({
        forge: { main: "7cd5c5bd4a67", testid: "add-to-cart", e2e_testid: "add-to-cart", baseline: "7cd5c5bd4a67", main_baseline_mi: true },
        uygulama: { sha: "7cd5c5bd4a67", main_ile_eslesiyor: true },
        web_yenileme_istegi: null,
        locator_demo: { destekleniyor: true, neden: null },
        onarim_on_kosulu: { hazir: false, son_yesil_kosu: null, yonerge: "Önce yeşil bir temel koşu gerekir: `make demo-reset`." },
        locator_durumu: "baseline",
      }),
    );
    uygulama("/demo");
    expect(await screen.findByTestId("on-kosul-yok")).toHaveTextContent("make demo-reset");
    expect(screen.getByRole("button", { name: "Önce yeşil temel koşu" })).toBeDisabled();
    expect(screen.getByText("yeşil temel koşu yok")).toBeInTheDocument();
    expect(screen.getByText("başlangıç")).toBeInTheDocument();
  });

  it("GitHub kipinde locator demosu yok: neden yazılır, düğme pasif", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    vi.stubGlobal(
      "fetch",
      sahteCore({
        forge: { main: "abc1234567", main_baseline_mi: true },
        uygulama: {},
        web_yenileme_istegi: null,
        locator_demo: { destekleniyor: false, neden: "GitHub kipinde locator demosu yok (çalışan uygulama main'den derlenmez)." },
        onarim_on_kosulu: { hazir: true, son_yesil_kosu: { run_id: "k1" }, yonerge: null },
      }),
    );
    uygulama("/demo");
    expect(await screen.findByTestId("locator-desteksiz")).toHaveTextContent("GitHub kipinde");
    expect(screen.getByRole("button", { name: "Bu kipte yok" })).toBeDisabled();
  });

  it("örnek veri: ön koşul hazır → son yeşil koşu bilgisi", async () => {
    await oturumAc("sunucu");
    uygulama("/demo");
    expect(await screen.findByTestId("on-kosul-hazir")).toHaveTextContent("ön koşul ✓");
    expect(screen.getByRole("button", { name: "Buton kimliğini değiştir" })).toBeEnabled();
  });
});

// ------------------------------------------------------------------ inceleme turu 2 düzeltmeleri

describe("Case review: REPLAY'de kazanç yüzdesi yok", () => {
  it("ölçülmüş baz + REPLAY + ≥ 5 sn review → '—' (verimlilik iddiası değil; hedef %30–50 yok)", () => {
    const baz = { ms: 1_800_000, deger_s: 1800, kaynak: "olcum" as const, giren: "analist", zaman: null, not: null };
    const ozet = { aiSure: 0, reviewSure: 45_000, olculenReview: 5 };
    const kz = caseKazanci(baz, ozet, true);
    expect(kz.oran).toBeNull();
    expect(kz.reviewOlculdu).toBe(true);
    expect(kz.neden).toBe(KAZANC_REPLAY_NEDENI);
    // Canlı (AI süresi ölçülmüş) aynı girdide oran hesaplanır.
    expect(caseKazanci(baz, { ...ozet, aiSure: 60_000 }, false).oran).toBeCloseTo(1 - 105_000 / 1_800_000);
  });

  it("ekran: ölçülmüş baz değer girilmiş REPLAY story'de Kazanç '—' ve REPLAY gerekçesi", async () => {
    await oturumAc("analist");
    const m = await api.caseMetrikleri("req-tpd-1");
    vi.spyOn(api, "caseMetrikleri").mockResolvedValue({
      ...m,
      karar_verilen: 5,
      bekleyen: 0,
      review_sure_ms: 6 * 60_000,
      ai_cagri_modlari: { replay: 3 },
      manuel_baz_ms: 30 * 60_000,
      manuel_baz_kaynagi: "olcum",
      manuel_baz: { deger_s: 1800, kaynak: "olcum", giren: "analist", zaman: "2026-10-30T10:00:00Z", not: null },
    } as typeof m);
    uygulama("/gereksinimler/req-tpd-1/caseler");
    const ozet = await screen.findByRole("region", { name: "Özet" });
    expect(await within(ozet).findByTestId("case-baz")).toHaveTextContent("Ölçüm");
    expect(within(ozet).getByTestId("case-kazanc")).toHaveTextContent("—");
    expect(within(ozet).queryByText(/hedef %30–50/)).toBeNull();
    expect(within(ozet).getByText(/REPLAY: AI süresi ölçülmedi — kazanç hesaplanmaz/)).toBeInTheDocument();
  });
});

describe("Bug taslakları: kasıtlı kırma koşusu işareti", () => {
  it("liste: BREAK_CAMPAIGN koşusundan gelen taslakta çip var, gerçek ürün hatası taslağında yok", async () => {
    await oturumAc("testci");
    uygulama("/bug-taslaklari");
    const kirmaSatiri = (await screen.findByText(/7 adet Portakal Gazozu/)).closest("tr")!;
    expect(await within(kirmaSatiri).findByTestId("kirma-cipi")).toHaveTextContent("Kasıtlı kırma koşusu (BREAK_CAMPAIGN)");
    const digerleri = screen.getAllByRole("row").filter((r) => r !== kirmaSatiri);
    for (const r of digerleri) expect(within(r).queryByTestId("kirma-cipi")).toBeNull();
  });

  it("detay: üstte 'gerçek hata değildir' uyarısı, Reddet önerilir, 'Onayla ve Jira'da aç' birincil değil", async () => {
    await oturumAc("testci");
    uygulama("/bug-taslaklari/bug-1");
    const uyari = await screen.findByTestId("kirma-uyarisi");
    expect(uyari).toHaveTextContent("Bu taslak bilerek bozulmuş");
    expect(uyari).toHaveTextContent("gerçek hata değildir");
    expect(uyari).toHaveTextContent("Önerilen karar: gerekçeyle reddedin");
    const onayla = screen.getByRole("button", { name: "Onayla ve Jira'da aç" });
    expect(onayla.className).toContain("dugme-ikincil");
    expect(onayla.className).not.toContain("dugme-birincil");
    expect(screen.getByRole("heading", { name: /Kayıt açma/ })).toHaveTextContent("Önerilen");
  });

  it("detay: kırma koşusundan gelmeyen taslakta uyarı yok, 'Onayla ve Jira'da aç' birincil", async () => {
    await oturumAc("testci");
    uygulama("/bug-taslaklari/bug-4");
    const onayla = await screen.findByRole("button", { name: "Onayla ve Jira'da aç" });
    await waitFor(() => expect(onayla.className).toContain("dugme-birincil"));
    expect(screen.queryByTestId("kirma-uyarisi")).toBeNull();
  });

  it("koşu/hata listesi okunamazsa işaret konmaz (yanlış 'kasıtlı' denmez)", async () => {
    vi.spyOn(api, "kosular").mockRejectedValue(new ApiError(503, "yok"));
    await oturumAc("testci");
    uygulama("/bug-taslaklari/bug-1");
    expect(await screen.findByRole("button", { name: "Onayla ve Jira'da aç" })).toBeInTheDocument();
    expect(screen.queryByTestId("kirma-uyarisi")).toBeNull();
  });
});

describe("demo yol haritası: açılış (make reset + make demo-reset)", () => {
  // demo-reset main için temel push CI'ı kuyruğa alır; story (TPD-1) henüz yok.
  const temel = {
    id: "run-taban",
    tetik: "push",
    kaynak: "local",
    durum: "passed",
    pr_no: null,
    commit: "abc1234",
    baslangic: "2026-11-01T08:00:00Z",
    junit_url: "/api/runs/run-taban/junit.xml",
    allure_url: "/api/runs/run-taban/allure/",
    break_campaign: false,
  } as unknown as Kosu;
  const kule = { son_kosular: [temel], gecme_orani: { oran: 1 }, flaky: [] } as unknown as YolGirdisi["kule"];

  it("story yokken temel CI koşusu adım 8–11'i doldurmaz: 0/14", () => {
    const a = demoAdimlari({ ...BOS, kosular: [temel], kule });
    expect(a.map((x) => x.hal).every((h) => h === "bekliyor")).toBe(true);
    expect(ilerleme(a)).toMatchObject({ tamam: 0, yedek: 0, toplam: 14 });
    expect(a[7].kanit).toMatch(/sayılmaz/);
  });

  it("story merge'ünden önceki koşular sayılmaz; sonrakiler ve story PR'ının CI'ı sayılır", () => {
    const g = { id: "r1", jira_key: "TPD-1", durum: "done", kaynak: "jira", kabul_kriterleri: [], kontrol_turu: 1, kontrol_turu_ust_sinir: 3, po: { durum: "approved" }, sayaclar: { bulgu_acik: 0 } } as unknown as GereksinimDetay;
    const s = { id: "s2", case_ids: [], requirement_key: "TPD-1", durum: "merged", pr: { number: 3, durum: "merged", merge_zamani: "2026-11-01T10:00:00Z" }, break_verify: { durum: "passed", asamalar: [] }, olusturma: "2026-11-01T09:00:00Z" } as unknown as Script;
    const girdi = { ...BOS, gereksinim: g, scriptler: [s], kosular: [temel], kule };
    expect(demoAdimlari(girdi).slice(7, 11).map((x) => x.hal)).toEqual(["bekliyor", "bekliyor", "bekliyor", "bekliyor"]);
    const prKosusu = { ...temel, id: "run-pr", tetik: "pr", pr_no: 3, baslangic: "2026-11-01T09:30:00Z" } as Kosu;
    const sonra = { ...temel, id: "run-push", baslangic: "2026-11-01T10:05:00Z" } as Kosu;
    const a = demoAdimlari({ ...girdi, kosular: [temel, prKosusu, sonra], kule: { ...kule!, son_kosular: [sonra] } });
    expect(a[7]).toMatchObject({ hal: "suruyor", kanit: expect.stringMatching(/2 koşu/) });
    expect(a[8].hal).toBe("yedek");
    expect(a[9]).toMatchObject({ hal: "tamam", baglanti: { yol: "/kosular/run-push" } });
    expect(a[10].hal).toBe("tamam");
  });
});
