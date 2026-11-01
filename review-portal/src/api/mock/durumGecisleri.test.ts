// Mock karar uçları core durum makinelerine (sozlesme/durum-makineleri.json) uyar: her başlangıç
// durumu × her karar için mock ya izinli bir yoldan geçer ya da 409 "Bu durumdan bu karara
// geçilemez" döner. Böylece mock, gerçek core'un 409 vereceği bir geçişi asla göstermez.
import { beforeEach, describe, expect, it } from "vitest";
import { api } from "../client";
import { ApiError } from "../http";
import makineler from "../sozlesme/durum-makineleri.json";
import { CASE_KARAR_HEDEFI, caseKarariVerilebilir, gecisVar, GECIS_YOK, yolGecerli } from "../sozlesme/durumMakinesi";
import type { BugTaslagi, Bulgu, CaseKararGirdisi, TestCase } from "../types";
import { ayar, mockVerisi } from "./handlers";
import { oturumAc } from "../../test/yardimci";

type Makine = { initial: string; states: string[]; transitions: Record<string, string[]> };
const M = makineler as Record<string, Makine>;

async function sonuc<T>(p: Promise<T>): Promise<{ ok: true; deger: T } | { ok: false; status: number; detail: string }> {
  try {
    return { ok: true, deger: await p };
  } catch (e) {
    if (e instanceof ApiError) return { ok: false, status: e.status, detail: e.detail };
    throw e;
  }
}

beforeEach(() => {
  ayar.isAdimiMs = 0;
});

describe("test_case kararları ↔ core test_case makinesi", () => {
  const kararlar: CaseKararGirdisi["karar"][] = ["approve", "edit", "reject"];
  const durumlar = M.test_case.states as TestCase["durum"][];

  it("tablo: kararlar yalnızca draft'tan; rejected onaylanamaz, approved reddedilemez", () => {
    expect(caseKarariVerilebilir("draft", "approve")).toBe(true);
    expect(caseKarariVerilebilir("draft", "reject")).toBe(true);
    expect(caseKarariVerilebilir("rejected", "approve")).toBe(false);
    expect(caseKarariVerilebilir("rejected", "edit")).toBe(false);
    expect(caseKarariVerilebilir("approved", "reject")).toBe(false);
  });

  for (const durum of durumlar) {
    for (const karar of kararlar) {
      it(`${durum} + ${karar}`, async () => {
        await oturumAc("analist");
        const c = mockVerisi().caseler.find((x) => x.id === "case-1-7")!;
        c.durum = durum;
        const once = c.durum;
        const govde: CaseKararGirdisi = {
          icerik_hash: c.icerik_hash,
          karar,
          ...(karar === "reject" ? { ret_nedeni: "duplicate" as const } : {}),
          ...(karar === "edit" ? { icerik: { ...c.icerik, title: `${c.icerik.title} (d)` } } : {}),
        };
        const r = await sonuc(api.caseKarari(c.id, govde));
        const izinli = gecisVar("test_case", once, CASE_KARAR_HEDEFI[karar]);
        if (izinli) {
          expect(r.ok, JSON.stringify(r)).toBe(true);
          expect(mockVerisi().caseler.find((x) => x.id === c.id)!.durum).toBe(CASE_KARAR_HEDEFI[karar]);
        } else {
          expect(r).toMatchObject({ ok: false, status: 409 });
          // Reddedilen karar hiçbir şeyi değiştirmez (yarım geçiş yok).
          const sonra = mockVerisi().caseler.find((x) => x.id === c.id)!;
          expect(sonra.durum).toBe(once);
          expect(sonra.icerik.title).toBe(c.icerik.title);
          if (once !== "published" && once !== "superseded") expect(r).toMatchObject({ detail: GECIS_YOK });
        }
      });
    }
  }

  it("bildirilen senaryo: reddedilmiş case #4 onaylanamaz, onaylı #5 reddedilemez", async () => {
    await oturumAc("analist");
    const v = mockVerisi();
    const red = v.caseler.find((c) => c.requirement_id === "req-tpd-1" && c.durum === "rejected")!;
    const onayli = v.caseler.find((c) => c.requirement_id === "req-tpd-1" && c.durum === "approved")!;
    await expect(api.caseKarari(red.id, { icerik_hash: red.icerik_hash, karar: "approve" })).rejects.toMatchObject({ status: 409, detail: GECIS_YOK });
    await expect(
      api.caseKarari(onayli.id, { icerik_hash: onayli.icerik_hash, karar: "reject", ret_nedeni: "duplicate" }),
    ).rejects.toMatchObject({ status: 409, detail: GECIS_YOK });
    expect(v.caseler.find((c) => c.id === red.id)!.durum).toBe("rejected");
    expect(v.caseler.find((c) => c.id === onayli.id)!.durum).toBe("approved");
  });
});

describe("bug_draft kararları ↔ core bug_draft makinesi", () => {
  const kararlar = ["new", "link", "dismiss"] as const;
  for (const durum of M.bug_draft.states as BugTaslagi["durum"][]) {
    for (const karar of kararlar) {
      it(`${durum} + ${karar}`, async () => {
        await oturumAc("testci");
        const b = mockVerisi().bugTaslaklari.find((x) => x.id === "bug-1")!;
        b.durum = durum;
        const r = await sonuc(api.bugKarari(b.id, { icerik_hash: b.icerik_hash, karar, ...(karar === "link" ? { link_key: "TPD-5" } : {}), ...(karar === "dismiss" ? { gerekce: "hata değil" } : {}) }));
        const yol = karar === "dismiss" ? ["dismissed"] : ["approved", "published"];
        if (yolGecerli("bug_draft", durum, yol)) {
          expect(r.ok, JSON.stringify(r)).toBe(true);
          expect(mockVerisi().bugTaslaklari.find((x) => x.id === b.id)!.durum).toBe(yol[yol.length - 1]);
        } else {
          expect(r).toMatchObject({ ok: false, status: 409 });
          expect(mockVerisi().bugTaslaklari.find((x) => x.id === b.id)!.durum).toBe(durum);
        }
      });
    }
  }
});

describe("consistency_finding kararları ↔ core consistency_finding makinesi", () => {
  const kararlar = ["fix_doc", "code_defect", "accept_difference"] as const;
  for (const durum of M.consistency_finding.states as Bulgu["durum"][]) {
    for (const karar of kararlar) {
      it(`${durum} + ${karar}`, async () => {
        await oturumAc("analist");
        const b = mockVerisi().bulgular.find((x) => x.id === "fnd-5")!;
        b.durum = durum;
        const r = await sonuc(api.bulguKarari(b.id, { icerik_hash: b.icerik_hash, karar, metin: "Yeni metin", gerekce: "Gerekçe" }));
        // core: open → decided (kapı); karar değişikliği decided → open → decided; fix_doc dışı → resolved.
        const yol = [...(durum === "decided" ? ["open"] : []), "decided", ...(karar === "fix_doc" ? [] : ["resolved"])];
        if (yolGecerli("consistency_finding", durum, yol)) {
          expect(r.ok, JSON.stringify(r)).toBe(true);
          expect(mockVerisi().bulgular.find((x) => x.id === b.id)!.durum).toBe(yol[yol.length - 1]);
        } else {
          expect(r).toMatchObject({ ok: false, status: 409 });
          expect(mockVerisi().bulgular.find((x) => x.id === b.id)!.durum).toBe(durum);
        }
      });
    }
  }
});

describe("requirement PO teyidi ↔ core requirement makinesi", () => {
  for (const durum of M.requirement.states) {
    it(`${durum} + po-approve`, async () => {
      await oturumAc("po");
      const g = mockVerisi().gereksinimler.find((x) => x.id === "req-ft-1")!;
      g.durum = durum as typeof g.durum;
      const r = await sonuc(api.poOnayla({ ...g }));
      if (durum === "pending_po") {
        expect(gecisVar("requirement", durum, "po_approved")).toBe(true);
        expect(r.ok, JSON.stringify(r)).toBe(true);
      } else {
        expect(r).toMatchObject({ ok: false, status: 409 });
        expect(mockVerisi().gereksinimler.find((x) => x.id === "req-ft-1")!.durum).toBe(durum);
      }
    });
  }
});

describe("uçtan uca akışlar yalnızca izinli geçişlerden geçer", () => {
  it("serbest metin: inceleme → bulgu kararları → düzeltme → PO → case → karar → (story'siz yayın engeli); her adım tabloda", async () => {
    const izlenen: [string, string, string][] = [];
    const gozle = () => {
      const v = mockVerisi();
      const satir = (m: string, id: string, d: string): [string, [string, string]] => [`${m}:${id}`, [m, d]];
      return new Map<string, [string, string]>([
        ...v.gereksinimler.map((g) => satir("requirement", g.id, g.durum)),
        ...v.bulgular.map((b) => satir("consistency_finding", b.id, b.durum)),
        ...v.caseler.map((c) => satir("test_case", c.id, c.durum)),
      ]);
    };
    let once = gozle();
    const kaydet = () => {
      const sonra = gozle();
      for (const [k, [m, d]] of sonra) {
        const e = once.get(k);
        if (e && e[1] !== d) izlenen.push([m, e[1], d]);
      }
      once = sonra;
    };
    const bekle = () => new Promise((r) => setTimeout(r, 20));

    await oturumAc("analist");
    const h = (id: string) => mockVerisi().bulgular.find((b) => b.id === id)!.icerik_hash;
    await api.bulguKarari("fnd-5", { icerik_hash: h("fnd-5"), karar: "fix_doc" });
    kaydet();
    await api.bulguKarari("fnd-6", { icerik_hash: h("fnd-6"), karar: "accept_difference", gerekce: "Ürün kararı" });
    kaydet();
    await api.duzeltmeleriUygula("req-ft-1");
    kaydet();
    await bekle();
    kaydet();
    await oturumAc("po");
    await api.poOnayla(mockVerisi().gereksinimler.find((g) => g.id === "req-ft-1")!);
    kaydet();
    await oturumAc("analist");
    await api.caseUret("req-ft-1");
    kaydet();
    await bekle();
    kaydet();
    const c = mockVerisi().caseler.find((x) => x.requirement_id === "req-ft-1")!;
    await api.caseKarari(c.id, { icerik_hash: c.icerik_hash, karar: "approve" });
    kaydet();
    // core ile aynı: serbest metnin Jira story'si yok → Test issue bağlanamaz, yayın engellenir.
    const engelli = await api.yayinla([c.id]);
    expect(engelli.sonuclar[0]).toMatchObject({ durum: "failed", hata: expect.stringContaining("story'si yok") });
    kaydet();
    // Jira story'li gereksinimin onaylı case'i yayınlanır (approved → published).
    const tpd = mockVerisi().caseler.find((x) => x.id === "case-1-4")!;
    await api.yayinla([tpd.id]);
    kaydet();

    expect(izlenen.length).toBeGreaterThan(6);
    for (const [m, a, b] of izlenen) {
      // Tek istekte birden çok adım atılmış olabilir (ör. in_review → doc_final → pending_po): yol var mı?
      const ulasilir = (bas: string, hedef: string, gorulen = new Set<string>()): boolean =>
        (M[m].transitions[bas] ?? []).some((x) => x === hedef || (!gorulen.has(x) && (gorulen.add(x), ulasilir(x, hedef, gorulen))));
      expect(ulasilir(a, b), `${m}: ${a} → ${b}`).toBe(true);
    }
    expect(izlenen).toContainEqual(["test_case", "draft", "approved"]);
    expect(izlenen).toContainEqual(["test_case", "approved", "published"]);
  });
});
