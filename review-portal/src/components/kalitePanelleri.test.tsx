// 011 D şeridi: P8 review ve P9 denetim — mock arka uç akışı (golden'larla), paneller ve yayın özeti.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { KAYNAK } from "../api/mock/fixtures";
import { ayar, bekleyenMockIs, mockVerisi } from "../api/mock/handlers";
import type { CaseDenetimGorunumu, CaseReviewGorunumu } from "../api/types";
import { OturumProvider } from "../auth";
import { oturumAc, sar } from "../test/yardimci";
import { BildirimProvider } from "./Bildirim";
import { DenetimOzeti, DenetimPaneli, ReviewPaneli } from "./KalitePanelleri";

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
  await oturumAc("analist");
  await api.caseUret(RID);
  await bekleIsler();
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
    for (const c of caseler) await api.caseKarari(c.id, { icerik_hash: c.icerik_hash, karar: "approve" });
    let p = await api.yayinOnizleme(RID);
    expect(p.kalemler.map((k) => k.islem)).toEqual(["blocked_gate", "blocked_gate"]);
    expect(p.kalemler[0].neden).toMatch(/^Denetim kararı yok/);

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
    await api.caseYenidenAc(c);
    await api.caseKarari(c.id, { icerik_hash: mockVerisi().caseler.find((x) => x.id === c.id)!.icerik_hash, karar: "reject", ret_nedeni: "duplicate" });
    const bayat = await api.caseDenetim(RID);
    expect(bayat.guncel_karar).toBeNull();
    expect(bayat.denetim?.guncel).toBe(false);
    expect(bayat.yayin_engeli).toMatch(/^Denetim kararı bayat/);
    expect((await api.caseReview(RID)).bayat).toBe(true);
    // Yeni set golden'a uymaz: dürüst REPLAY-MISS, karar yok.
    await api.caseDenetimGonder(RID);
    await bekleIsler();
    const miss = await api.caseDenetim(RID);
    expect(miss.denetim?.durum).toBe("hata");
    expect(miss.yayin_engeli).toMatch(/^Denetim yapılamadı/);
  });

  it("denetime gönder koşulu: review tamamlanmadıysa en az bir onaylı case", async () => {
    await uret();
    const k = mockVerisi().kalite![RID];
    k.review = { ...k.review!, durum: "hata", hata: "test" };
    const d = await api.caseDenetim(RID);
    expect(d.gonder_engeli).toMatch(/review'u tamamlanmadı ve onaylı case yok/);
    await expect(api.caseDenetimGonder(RID)).rejects.toMatchObject({ status: 409 });
    const c = mockVerisi().caseler.find((x) => x.requirement_id === RID)!;
    await api.caseKarari(c.id, { icerik_hash: c.icerik_hash, karar: "approve" });
    expect((await api.caseDenetim(RID)).gonder_engeli).toBeNull();
  });

  it("golden kopyası: review/denetim çıktıları rules/replay ile aynı adlarla", () => {
    const k = KAYNAK as unknown as { case_review: Record<string, unknown>; case_audit: Record<string, { decision: string }> };
    expect(Object.keys(k.case_audit).sort()).toEqual(["SERBEST", "TPD-1", "TPD-3", "TPD-4", "f2-kod-hatasi/TPD-1"]);
    expect(k.case_audit["TPD-1"].decision).toBe("KABUL");
    expect(k.case_audit["TPD-3"].decision).toBe("DÜZELTME_GEREKLİ");
    expect(Object.keys(k.case_review)).toHaveLength(5);
  });

  it("case review sayfası: review bulguları ve denetim paneli, Denetime gönder", async () => {
    await uret();
    const c = mockVerisi().caseler.find((x) => x.requirement_id === RID)!;
    await api.caseKarari(c.id, { icerik_hash: c.icerik_hash, karar: "approve" });
    const u = userEvent.setup();
    uygulama(`/gereksinimler/${RID}/caseler`);
    expect(await screen.findByTestId("review-skor")).toHaveTextContent("11/12");
    expect(within(screen.getByTestId("review-maddeleri")).getAllByRole("listitem")).toHaveLength(12);
    await u.click(screen.getByRole("button", { name: "Denetime gönder" }));
    await bekleIsler();
    expect(await screen.findByTestId("denetim-karari", {}, { timeout: 3000 })).toHaveTextContent("KABUL");
    expect(screen.getByTestId("denetim-gerekce")).toHaveTextContent("AC1–AC2");
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
  gonder_engeli: "Bu set için review sürüyor; review bitince denetime gönderin",
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
    sar(<ReviewPaneli gorunum={REVIEW} calistir={() => undefined} />);
    expect(screen.getByTestId("review-skor")).toHaveTextContent("10/12");
    expect(screen.getByText("Review bayat")).toBeInTheDocument();
    const refs = within(screen.getByTestId("review-birlestir")).getAllByTestId("case-ref");
    expect(refs.map((a) => a.getAttribute("href"))).toEqual(["#case-c2", "#case-c10"]);
    expect(screen.getByTestId("review-eksik")).toHaveTextContent("12 adet");
  });

  it("review hatası: 'review çalışmadı, yeniden dene'", async () => {
    await oturumAc("analist");
    sar(<ReviewPaneli gorunum={{ ...REVIEW, bayat: false, review: { ...REVIEW.review!, durum: "hata", hata: "REPLAY-MISS" } }} calistir={() => undefined} />);
    expect(screen.getByText("Review çalışmadı, yeniden deneyin")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Yeniden çalıştır" })).toBeEnabled());
  });

  it("denetim: sertleştirme, bulgu, kapalı düğmenin nedeni", async () => {
    await oturumAc("analist");
    sar(<DenetimPaneli gorunum={DENETIM} gonder={() => undefined} />);
    expect(screen.getByTestId("denetim-karari")).toHaveTextContent("DÜZELTME GEREKLİ");
    expect(screen.getByText("Karar kodda sertleştirildi")).toBeInTheDocument();
    expect(screen.getByTestId("denetim-bulgulari")).toHaveTextContent("AP-001");
    expect(screen.getByRole("button", { name: "Denetime gönder" })).toBeDisabled();
    expect(await screen.findByText(/review bitince denetime gönderin/)).toBeInTheDocument();
  });

  it("yayın özeti: karar ve engel", async () => {
    sar(<DenetimOzeti gorunum={DENETIM} reviewYolu="/gereksinimler/r/caseler" />);
    await waitFor(() => expect(screen.getByTestId("yayin-denetim-ozeti")).toHaveTextContent("DÜZELTME GEREKLİ"));
    expect(screen.getByText("DÜZELTME_GEREKLİ: sentetik değil")).toBeInTheDocument();
  });
});
