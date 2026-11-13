// 011 D şeridi: P8 review ve P9 denetim — mock arka uç akışı (golden'larla), paneller ve yayın özeti.
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { KAYNAK } from "../api/mock/fixtures";
import { ayar, bekleyenMockIs, mockVerisi } from "../api/mock/handlers";
import type { CaseDenetimGorunumu, CaseReviewGorunumu } from "../api/types";
import { OturumProvider } from "../auth";
import { oturumAc, sar } from "../test/yardimci";
import { BildirimProvider } from "./Bildirim";
import { DenetimOzeti, DenetimPaneli, gonderBirincilMi, ReviewPaneli } from "./KalitePanelleri";

const RID = "req-tpd-4";

const bekleIsler = async () => {
  const son = Date.now() + 5000;
  do await new Promise((r) => setTimeout(r, 10));
  while (bekleyenMockIs() > 0 && Date.now() < son);
};

/** TPD-4'ü PO onaylı yap, case üret (golden TPD-4 → REPLAY), işler bitene dek bekle. */
async function uret() {
  const g = mockVerisi().gereksinimler.find((x) => x.id === RID)!;
  g.durum = "po_approved";
  g.po = { durum: "approved", onaylayan: "po@sim.local", zaman: "2026-11-11T10:00:00Z", kanal: "jira", onaylanan_hash: g.icerik_hash };
  await oturumAc("testci");
  await api.caseUret(RID);
  await bekleIsler();
}

/** 012 iki adım: Testçi kabul eder, Analist son onayı verir; oturum Analistte kalır (denetime gönderen). */
async function ikiAdimOnay(ids: string[]) {
  const hash = (id: string) => mockVerisi().caseler.find((x) => x.id === id)!.icerik_hash;
  await oturumAc("testci");
  for (const id of ids) await api.caseKarari(id, { icerik_hash: hash(id), karar: "accept" });
  await oturumAc("analist");
  for (const id of ids) await api.caseKarari(id, { icerik_hash: hash(id), karar: "approve" });
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

describe("mock: review (P8) ve denetim (P9) akışı", () => {
  beforeEach(() => {
    ayar.isAdimiMs = 0;
  });

  it("üretimden sonra review otomatik; denetim KABUL yayın kapısını açar; set değişince bayat", async () => {
    await uret();
    const r = await api.caseReview(RID);
    expect(r.review?.durum).toBe("tamamlandi");
    expect(r.review?.skor).toBe(11);
    expect(r.review?.icerik.items).toHaveLength(12);
    expect(r.review?.icerik.items?.[8].finding).toBe("UYGUN — platform eki yok");

    const caseler = mockVerisi().caseler.filter((c) => c.requirement_id === RID);
    await ikiAdimOnay(caseler.map((c) => c.id));
    let p = await api.yayinOnizleme(RID);
    expect(p.kalemler.map((k) => k.islem)).toEqual(["blocked_gate", "blocked_gate"]);
    expect(p.kalemler[0].neden).toMatch(/^Yayınlanamaz: Agent Probe denetimi kararı yok/);

    const d0 = await api.caseDenetimGonder(RID);
    expect(d0.calisiyor).toBe(true);
    await bekleIsler();
    const d = await api.caseDenetim(RID);
    expect(d.guncel_karar?.karar).toBe("KABUL");
    expect(d.guncel_karar?.talep_no).toMatch(/^AP-2026-/);
    expect(d.yayin_engeli).toBeNull();
    p = await api.yayinOnizleme(RID);
    expect(p.kalemler.map((k) => k.islem)).toEqual(["create", "create"]);

    // Bir case reddedildi: set değişti → karar bayat, review bayat, kapı kapanır.
    const c = mockVerisi().caseler.find((x) => x.requirement_id === RID)!;
    await oturumAc("testci");
    await api.caseYenidenAc(c);
    await api.caseKarari(c.id, { icerik_hash: mockVerisi().caseler.find((x) => x.id === c.id)!.icerik_hash, karar: "reject", ret_nedeni: "duplicate" });
    await oturumAc("analist");
    const bayat = await api.caseDenetim(RID);
    expect(bayat.guncel_karar).toBeNull();
    expect(bayat.denetim?.guncel).toBe(false);
    expect(bayat.yayin_engeli).toMatch(/^Yayınlanamaz: Agent Probe denetimi kararı bayat/);
    expect((await api.caseReview(RID)).bayat).toBe(true);
    // Yeni set golden'a uymaz: dürüst REPLAY-MISS, karar yok.
    await api.caseDenetimGonder(RID);
    await bekleIsler();
    const miss = await api.caseDenetim(RID);
    expect(miss.denetim?.durum).toBe("hata");
    expect(miss.yayin_engeli).toMatch(/^Yayınlanamaz: Agent Probe denetimi yapılamadı/);
    // Core gibi ham istisna sınıfıyla gelir; portal ayıklar (KalitePanelleri testleri).
    expect(miss.denetim?.hata).toMatch(/^ReplayNoOutput: /);
  });

  it("denetime gönder koşulu: review tamamlanmadıysa en az bir onaylı case", async () => {
    await uret();
    const k = mockVerisi().kalite![RID];
    k.review = { ...k.review!, durum: "hata", hata: "test" };
    const d = await api.caseDenetim(RID);
    expect(d.gonder_engeli).toMatch(/review'u tamamlanmadı ve onaylı case yok/);
    await oturumAc("analist");
    await expect(api.caseDenetimGonder(RID)).rejects.toMatchObject({ status: 409 });
    const c = mockVerisi().caseler.find((x) => x.requirement_id === RID)!;
    await ikiAdimOnay([c.id]);
    expect((await api.caseDenetim(RID)).gonder_engeli).toBeNull();
  });

  it("golden kopyası: review/denetim çıktıları rules/replay ile aynı adlarla", () => {
    const k = KAYNAK as unknown as { case_review: Record<string, unknown>; case_audit: Record<string, { decision: string }> };
    expect(Object.keys(k.case_audit).sort()).toEqual([
      "SERBEST",
      "TPD-1",
      "TPD-3",
      "TPD-4",
      "c10-reddedildi/TPD-1",
      "f2-kod-hatasi-c10-reddedildi/TPD-1",
      "f2-kod-hatasi/TPD-1",
    ]);
    expect(k.case_audit["TPD-1"].decision).toBe("KABUL");
    expect(k.case_audit["TPD-3"].decision).toBe("DÜZELTME_GEREKLİ");
    expect(Object.keys(k.case_review)).toHaveLength(7);
  });

  it("case review sayfası: daralmış paneller, karar bekleyen varken ikincil + onay ile Agent Probe'a gönder, KABUL yönlendirmesi", async () => {
    await uret();
    const c = mockVerisi().caseler.find((x) => x.requirement_id === RID)!;
    await ikiAdimOnay([c.id]);
    const u = userEvent.setup();
    uygulama(`/gereksinimler/${RID}/caseler`);
    expect(await screen.findByTestId("review-skor")).toHaveTextContent("11/12");
    // Review paneli özet satırına daralmış başlar; ayrıntı aria-expanded düğmeyle açılır.
    const reviewKart = within(document.getElementById("review-bulgulari")!);
    expect(screen.getByTestId("review-ayrinti")).not.toBeVisible();
    const ac = reviewKart.getByRole("button", { name: "Ayrıntıları göster" });
    expect(ac).toHaveAttribute("aria-expanded", "false");
    await u.click(ac);
    expect(reviewKart.getByRole("button", { name: "Ayrıntıları gizle" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("review-ayrinti")).toBeVisible();
    expect(within(screen.getByTestId("review-maddeleri")).getAllByRole("listitem")).toHaveLength(12);

    // Bir case hâlâ karar bekliyor: düğme ikincil, tıklayınca sayfa içi onay.
    const gonder = screen.getByRole("button", { name: "Agent Probe'a gönder" });
    expect(gonder).toHaveClass("dugme-ikincil");
    await u.click(gonder);
    const onay = screen.getByTestId("denetim-gonder-onayi");
    expect(onay).toHaveTextContent("2 case'ten 1 tanesi hâlâ karar bekliyor. Denetim yalnız bugünkü seti değerlendirir; case'ler değişirse karar bayatlar.");
    await u.click(within(onay).getByRole("button", { name: "Yine de gönder" }));
    await bekleIsler();
    expect(await screen.findByTestId("denetim-karari", {}, { timeout: 3000 })).toHaveTextContent("KABUL");
    const yon = screen.getByTestId("denetim-yonlendirme");
    expect(yon).toHaveTextContent("Yayına hazır: Yayın sayfasına geç");
    expect(within(yon).getByRole("link", { name: "Yayın sayfasına geç" })).toHaveAttribute("href", `/gereksinimler/${RID}/yayin`);
    expect(screen.getByTestId("denetim-gerekce")).not.toBeVisible();
    await u.click(within(document.getElementById("denetim")!).getByRole("button", { name: "Ayrıntıları göster" }));
    expect(screen.getByTestId("denetim-gerekce")).toHaveTextContent("AC1–AC2");
    expect(screen.getByTestId("serit-denetim")).toHaveTextContent("Agent Probe denetimi: KABUL");
  });

  it("durum şeridi: sayılar ve bölüm bağlantıları; tek birincil eylem", async () => {
    await uret();
    const u = userEvent.setup();
    uygulama(`/gereksinimler/${RID}/caseler`);
    const serit = await screen.findByRole("navigation", { name: "Case review durumu" });
    const bekleyen = within(serit).getByTestId("serit-bekleyen");
    expect(bekleyen).toHaveTextContent("2 karar bekliyor");
    expect(bekleyen).toHaveAttribute("href", `/gereksinimler/${RID}/caseler#case-kararlari`);
    expect(within(serit).getByTestId("serit-hazir-degil")).toHaveTextContent(/^\d+ hazır değil$/);
    expect(within(serit).getByTestId("serit-hazir-degil")).toHaveAttribute("href", `/gereksinimler/${RID}/caseler?filtre=hazir-degil#case-kararlari`);
    await waitFor(() => expect(within(serit).getByTestId("serit-denetim")).toHaveTextContent("Agent Probe denetimi: karar yok"));
    expect(within(serit).getByTestId("serit-denetim")).toHaveAttribute("href", `/gereksinimler/${RID}/caseler#denetim`);
    expect(within(serit).getByTestId("serit-yayin")).toHaveTextContent("Yayın: kapalı");
    expect(within(serit).getByTestId("serit-yayin")).toHaveAttribute("href", `/gereksinimler/${RID}/yayin`);
    expect(document.getElementById("case-kararlari")).not.toBeNull();
    // Karar bekleyen varken ne gönder ne yayın birincil.
    expect(screen.getByRole("button", { name: "Agent Probe'a gönder" })).toHaveClass("dugme-ikincil");
    expect(screen.getByRole("link", { name: "Yayın önizleme" })).toHaveClass("dugme-ikincil");

    // Hepsi onaylandı: gönder birincil olur, yayın önizleme ikincil kalır (sayfada tek birincil).
    await ikiAdimOnay(mockVerisi().caseler.filter((x) => x.requirement_id === RID).map((c) => c.id));
    await u.click(within(serit).getByTestId("serit-bekleyen"));
    await waitFor(() => expect(screen.getByTestId("serit-bekleyen")).toHaveTextContent("Karar bekleyen yok"), { timeout: 3000 });
    await waitFor(() => expect(screen.getByRole("button", { name: "Agent Probe'a gönder" })).toHaveClass("dugme-birincil"));
    expect(screen.getByRole("link", { name: "Yayın önizleme" })).toHaveClass("dugme-ikincil");
  });
});

const REVIEW: CaseReviewGorunumu = {
  requirement_id: "r",
  set_hash: "h2",
  bayat: true,
  calisiyor: false,
  yeniden_calistirilabilir: true,
  review: {
    id: "1",
    durum: "tamamlandi",
    set_hash: "h1",
    uretim_no: 1,
    skor: 10,
    hata: null,
    isteyen: "system",
    mode: "replay",
    olusturma: "",
    guncelleme: "",
    bayat: true,
    icerik: {
      items: [{ no: 10, title: "Tekrar eden case", verdict: "UYGUN_DEGIL", finding: "C10 = C2", missing_case: "C10 kaldırılmalı", question: null, owner: "" }],
      remove_or_merge: [{ case_refs: [2, 10], action: "merge", reason: "aynı sepet" }],
      missing_cases: [{ ac_ref: "AC2", item: 3, description: "12 adet", technique: "BVA" }],
      case_haritasi: { "2": { id: "c2", sira_no: 2, uretim_no: 1, title: "C2" }, "10": { id: "c10", sira_no: 10, uretim_no: 1, title: "C10" } },
    },
  },
};

const DENETIM: CaseDenetimGorunumu = {
  requirement_id: "r",
  set_hash: "h1",
  calisiyor: false,
  gonder_engeli: "Bu set için review sürüyor; review bitince Agent Probe'a gönderin",
  kapi_acik: true,
  yayin_engeli: "DÜZELTME_GEREKLİ: sentetik değil",
  denetim: null,
  guncel_karar: {
    id: "a",
    durum: "tamamlandi",
    set_hash: "h1",
    karar: "DÜZELTME_GEREKLİ",
    model_karari: "KABUL",
    kaynak: "tp-gecit",
    talep_no: "AP-2026-ABCDEF12",
    hata: null,
    isteyen: "analist",
    olusturma: "",
    guncelleme: "",
    guncel: true,
    icerik: {
      decision_rationale: "sentetik değil",
      findings: [{ finding_id: "AP-001", case_ref: 1, control_no: 2, issue: "gerçek e-posta", rationale: "KVKK", risk: "Yüksek", suggested_fix: "sentetik yap" }],
      deterministik_bulgular: [{ kural: "sentetik_degil", case_ref: 1, alt_sinir: "DÜZELTME_GEREKLİ", aciklama: "Test verisi sentetik değil" }],
      sertlestirildi: true,
      missing_scenarios: ["Kilit senaryosu"],
      case_haritasi: { "1": { id: "c1", sira_no: 1, uretim_no: 1, title: "C1" } },
    },
  },
};

describe("paneller", () => {
  it("review: skor, bayat uyarısı, birleştir önerisi case bağlantılı", async () => {
    await oturumAc("analist");
    sar(<ReviewPaneli gorunum={REVIEW} calistir={() => undefined} baslangictaAcik />);
    expect(screen.getByTestId("review-skor")).toHaveTextContent("10/12");
    expect(screen.getByTestId("review-skor")).toHaveTextContent("bayat — set değişti");
    expect(screen.getByText("Review bayat")).toBeVisible();
    const refs = within(screen.getByTestId("review-birlestir")).getAllByTestId("case-ref");
    expect(refs.map((a) => a.getAttribute("href"))).toEqual(["#case-c2", "#case-c10"]);
    expect(screen.getByTestId("review-eksik")).toHaveTextContent("12 adet");
  });

  it("review hatası: 'review çalışmadı, yeniden dene'; ham sınıf adı ayıklanır, hata tonunda", async () => {
    await oturumAc("testci");
    sar(
      <ReviewPaneli
        gorunum={{ ...REVIEW, bayat: false, review: { ...REVIEW.review!, durum: "hata", hata: "REPLAY-MISS: bu set için kayıtlı review çıktısı yok (ReplayNoOutput)" } }}
        calistir={() => undefined}
      />,
    );
    expect(screen.getByText("Review çalışmadı, yeniden deneyin").closest(".uyari-kutusu")).toHaveClass("uyari-hata");
    expect(screen.getByTestId("review-hata")).toHaveTextContent(/^REPLAY-MISS: bu set için kayıtlı review çıktısı yok$/);
    await waitFor(() => expect(screen.getByRole("button", { name: "Yeniden çalıştır" })).toBeEnabled());
  });

  it("denetim: sertleştirme, bulgu, kapalı düğmenin nedeni; yayın engeli ayrıntıda Uyari", async () => {
    await oturumAc("analist");
    sar(<DenetimPaneli gorunum={DENETIM} gonder={() => undefined} baslangictaAcik />);
    expect(screen.getByRole("heading", { name: "Agent Probe denetimi" })).toBeInTheDocument();
    expect(screen.getByTestId("denetim-karari")).toHaveTextContent("DÜZELTME GEREKLİ");
    expect(screen.getByText("Karar kodda sertleştirildi")).toBeInTheDocument();
    expect(screen.getByTestId("denetim-bulgulari")).toHaveTextContent("AP-001");
    expect(screen.getByRole("button", { name: "Agent Probe'a gönder" })).toBeDisabled();
    expect(await screen.findByText(/review bitince Agent Probe'a gönderin/)).toBeInTheDocument();
    expect(screen.getByTestId("denetim-yayin-engeli")).toHaveTextContent(/^Yayınlanamaz: DÜZELTME_GEREKLİ: sentetik değil$/);
  });

  it("yayın özeti: karar ve engel (önek bir kez)", async () => {
    sar(<DenetimOzeti gorunum={DENETIM} reviewYolu="/gereksinimler/r/caseler" />);
    await waitFor(() => expect(screen.getByTestId("yayin-denetim-ozeti")).toHaveTextContent("DÜZELTME GEREKLİ"));
    expect(screen.getByTestId("yayin-denetim-engeli")).toHaveTextContent(/^Yayınlanamaz: DÜZELTME_GEREKLİ: sentetik değil$/);
    expect(screen.getByRole("link", { name: /Agent Probe'a gönder/ })).toHaveAttribute("href", "/gereksinimler/r/caseler#denetim");
  });

  it("yayın özeti: core öneki varsa ikinci kez yazılmaz; kapı kapalı metninde ortam değişkeni yok", async () => {
    sar(<DenetimOzeti gorunum={{ ...DENETIM, yayin_engeli: "Yayınlanamaz: ENGELLE — gerçek kart verisi" }} reviewYolu="/r" />);
    await waitFor(() => expect(screen.getByTestId("yayin-denetim-engeli")).toHaveTextContent(/^Yayınlanamaz: ENGELLE — gerçek kart verisi$/));
    cleanup();
    sar(<DenetimOzeti gorunum={{ ...DENETIM, kapi_acik: false }} reviewYolu="/r" />);
    await waitFor(() => expect(screen.getByTestId("yayin-denetim-ozeti")).toHaveTextContent("denetim kapısı kapalı"));
    expect(document.body).toHaveTextContent("Denetim kapısı yönetici tarafından kapatıldı; yayın için denetim kararı aranmıyor.");
    expect(document.body.textContent).not.toMatch(/TP_DENETIM/);
  });
});

describe("DenetimPaneli: gönder, yönlendirme, kapı, hata (UX-7)", () => {
  const KABUL: CaseDenetimGorunumu = {
    ...DENETIM,
    gonder_engeli: null,
    yayin_engeli: null,
    guncel_karar: { ...DENETIM.guncel_karar!, karar: "KABUL", model_karari: "KABUL", icerik: { decision_rationale: "uygun" } },
  };
  const YOK: CaseDenetimGorunumu = { ...DENETIM, gonder_engeli: null, guncel_karar: null, denetim: null, yayin_engeli: "Yayınlanamaz: karar yok" };

  it("karar bekleyen varken ikincil + sayfa içi onay; vazgeç göndermez", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    const gonder = vi.fn();
    sar(<DenetimPaneli gorunum={YOK} gonder={gonder} bekleyen={4} toplam={6} />);
    const d = screen.getByRole("button", { name: "Agent Probe'a gönder" });
    await waitFor(() => expect(d).toBeEnabled());
    expect(d).toHaveClass("dugme-ikincil");
    await u.click(d);
    expect(screen.getByTestId("denetim-gonder-onayi")).toHaveTextContent(
      "6 case'ten 4 tanesi hâlâ karar bekliyor. Denetim yalnız bugünkü seti değerlendirir; case'ler değişirse karar bayatlar.",
    );
    await u.click(screen.getByRole("button", { name: "Vazgeç" }));
    expect(screen.queryByTestId("denetim-gonder-onayi")).toBeNull();
    expect(gonder).not.toHaveBeenCalled();
    await u.click(d);
    await u.click(screen.getByRole("button", { name: "Yine de gönder" }));
    expect(gonder).toHaveBeenCalledTimes(1);
  });

  it("bekleyen yoksa birincil ve doğrudan gönderir; güncel KABUL varken ikincil", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    const gonder = vi.fn();
    const { unmount } = sar(<DenetimPaneli gorunum={YOK} gonder={gonder} bekleyen={0} toplam={6} />);
    const d = screen.getByRole("button", { name: "Agent Probe'a gönder" });
    expect(d).toHaveClass("dugme-birincil");
    expect(gonderBirincilMi(YOK, 0)).toBe(true);
    await waitFor(() => expect(d).toBeEnabled());
    await u.click(d);
    expect(gonder).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("denetim-gonder-onayi")).toBeNull();
    unmount();
    sar(<DenetimPaneli gorunum={KABUL} gonder={gonder} bekleyen={0} yayinYolu="/gereksinimler/r/yayin" />);
    expect(screen.getByRole("button", { name: "Agent Probe'a gönder" })).toHaveClass("dugme-ikincil");
    expect(gonderBirincilMi(KABUL, 0)).toBe(false);
    expect(gonderBirincilMi({ ...YOK, kapi_acik: false }, 0)).toBe(false);
  });

  it.each([
    ["KABUL", true, "Sonraki adım: Yayına hazır: Yayın sayfasına geç"],
    ["DÜZELTME_GEREKLİ", true, "Sonraki adım: Bulgulardaki case'leri düzeltin, sonra yeniden gönderin."],
    ["ENGELLE", true, "Sonraki adım: Set yayınlanamaz; bulgulardaki engelleri giderip yeniden üretin ya da gönderin."],
    ["KABUL", false, "Sonraki adım: Case'ler denetimden sonra değişti; yeniden gönderin."],
  ] as const)("yönlendirme: %s (güncel: %s)", async (karar, guncel, metin) => {
    await oturumAc("analist");
    const k = { ...DENETIM.guncel_karar!, karar, guncel };
    const g: CaseDenetimGorunumu = guncel ? { ...DENETIM, guncel_karar: k } : { ...DENETIM, guncel_karar: null, denetim: k };
    sar(<DenetimPaneli gorunum={g} gonder={() => undefined} yayinYolu="/gereksinimler/r/yayin" />);
    expect(screen.getByTestId("denetim-yonlendirme")).toHaveTextContent(metin);
  });

  it("kapı kapalı: yönetici metni, ortam değişkeni adı yok", async () => {
    await oturumAc("analist");
    sar(<DenetimPaneli gorunum={{ ...YOK, kapi_acik: false }} gonder={() => undefined} />);
    expect(screen.getByTestId("denetim-kapi-kapali")).toHaveTextContent("Denetim kapısı yönetici tarafından kapatıldı; yayın için denetim kararı aranmıyor.");
    expect(document.body.textContent).not.toMatch(/TP_DENETIM/);
  });

  it("denetim hatası tek yerde, ham sınıf adı ayıklanmış, hata tonunda; işlem hatası panel içinde", async () => {
    await oturumAc("analist");
    const hata: CaseDenetimGorunumu = {
      ...YOK,
      yayin_engeli: "Yayınlanamaz: Agent Probe denetimi yapılamadı (ReplayNoOutput: bu set için kayıtlı denetim çıktısı yok (REPLAY-MISS)); yeniden gönderin",
      denetim: { ...DENETIM.guncel_karar!, durum: "hata", karar: null, hata: "ReplayNoOutput: bu set için kayıtlı denetim çıktısı yok (REPLAY-MISS)", icerik: {} },
    };
    sar(<DenetimPaneli gorunum={hata} gonder={() => undefined} islemHata="TimeoutError: Agent Probe 30 sn içinde yanıt vermedi" />);
    const h = screen.getByTestId("denetim-hata");
    expect(h).toHaveTextContent(/^Bu set için kayıtlı denetim çıktısı yok \(REPLAY-MISS\)$/);
    expect(h.closest(".uyari-kutusu")).toHaveClass("uyari-hata");
    expect(screen.getAllByText(/kayıtlı denetim çıktısı yok/)).toHaveLength(1);
    expect(screen.queryByTestId("denetim-yayin-engeli")).toBeNull();
    expect(document.body.textContent).not.toMatch(/ReplayNoOutput|TimeoutError/);
    expect(screen.getByText("Agent Probe 30 sn içinde yanıt vermedi")).toBeInTheDocument();
  });
});
