// Demo-A yanıt uyarlayıcıları: portal şekli aynen geçer, veritabanı kolon adlı şekil (özellik
// şeritlerinin olası çıktısı) portal şekline çevrilir; çıktı modu uydurulmaz.
import { describe, expect, it } from "vitest";
import {
  bulguUyarla,
  caseUyarla,
  gereksinimDetayUyarla,
  gereksinimUyarla,
  jiraKayitAdresi,
  kabulKriteriUyarla,
  listeUyarla,
  modUyarla,
  yayinOnizlemeUyarla,
  yayinSonucuUyarla,
} from "./uyum";
import { ilkVeri } from "./mock/fixtures";

describe("modUyarla", () => {
  it("yalnızca live/replay/replay_miss tanınır; eksik veya bilinmeyen null olur (live uydurulmaz)", () => {
    expect(modUyarla("replay")).toBe("replay");
    expect(modUyarla("REPLAY-MISS")).toBe("replay_miss");
    expect(modUyarla("live")).toBe("live");
    expect(modUyarla(undefined)).toBeNull();
    expect(modUyarla("record")).toBeNull();
  });
});

describe("gereksinim", () => {
  it("portal şekli (mock) değişmeden geçer", () => {
    const g = ilkVeri().gereksinimler.find((x) => x.id === "req-tpd-1")!;
    const u = gereksinimDetayUyarla(JSON.parse(JSON.stringify(g)));
    expect(u).toEqual({ ...g, po: { ...g.po, onaylanan_hash: g.po.onaylanan_hash ?? null } });
  });

  it("veritabanı kolon adlarından PO durumu, sayaçlar ve ön inceleme türetilir", () => {
    const ham = {
      id: "6f1c",
      kaynak: "jira",
      jira_key: "TPD-1",
      baslik: "Kampanyalı sepet",
      aciklama: "a",
      kabul_kriterleri: ["AC1: Sepete ekle", { ref: "AC2", text: "6 al 1 bedava" }],
      durum: "cases_ready",
      olusturma: "2026-10-31T09:00:00Z",
      po_onaylayan: "po@sim.local",
      po_onay_zamani: "2026-10-31T10:00:00Z",
      po_onay_kaynagi: "jira_label",
      onaylanan_hash: "sha256:abc",
      icerik_hash: "sha256:abc",
      kontrol_turu: 2,
      review: { sorular: [{ id: "Q1", tur: "conflict", metin: "AC3 mü AC6 mı?", ac_ref: "AC3" }], verdict: "needs_po", uretim_modu: "replay", olusturma: "t" },
      sayaclar: { bulgu_acik: 1, case_toplam: 9, case_onayli: 4, bulgu_elenen: 2 },
    };
    const u = gereksinimDetayUyarla(ham);
    expect(u.kabul_kriterleri).toEqual([
      { ref: "AC1", metin: "Sepete ekle" },
      { ref: "AC2", metin: "6 al 1 bedava" },
    ]);
    expect(u.ac_missing).toBe(false);
    expect(u.po).toEqual({ durum: "approved", onaylayan: "po@sim.local", zaman: "2026-10-31T10:00:00Z", kanal: "jira", onaylanan_hash: "sha256:abc" });
    expect(u.cekim_zamani).toBe("2026-10-31T09:00:00Z");
    expect(u.on_inceleme).toMatchObject({ verdict: "needs_po", mode: "replay", questions: [{ id: "Q1", type: "conflict", text: "AC3 mü AC6 mı?", ac_ref: "AC3", cevap: null }] });
    expect(u.kontrol_turu_ust_sinir).toBe(3);
    expect(u.elenen_bulgu).toBe(2);
    expect(u.sayaclar).toEqual({ bulgu_acik: 1, case_toplam: 9, case_onayli: 4 });
  });

  it("pending_po: PO bekliyor; serbest metinde kanal portal; AC yoksa ac_missing", () => {
    const u = gereksinimUyarla({ id: 1, kaynak: "free_text", baslik: "x", durum: "pending_po", kabul_kriterleri: [] });
    expect(u.id).toBe("1");
    expect(u.po).toMatchObject({ durum: "pending", kanal: "portal", onaylayan: null });
    expect(u.ac_missing).toBe(true);
  });

  it("onaylayan kaydı olsa da PO onaylı olmayan durumda (ör. new'e döndü) onaylı gösterilmez", () => {
    expect(gereksinimUyarla({ id: "r", durum: "new", po_onaylayan: "po" }).po.durum).toBe("not_requested");
  });

  it("kabul kriteri metni ayrıştırma", () => {
    expect(kabulKriteriUyarla("AC 3 - Minimum tutar", 0)).toEqual({ ref: "AC3", metin: "Minimum tutar" });
    expect(kabulKriteriUyarla("serbest", 4)).toEqual({ ref: "AC5", metin: "serbest" });
    expect(kabulKriteriUyarla(7, 0)).toBeNull();
  });
});

describe("bulgu", () => {
  it("kolon adları (tur, kanitlar, onerilen_metin, analist_karari, uretim_modu) eşlenir", () => {
    const b = bulguUyarla({
      id: "f1",
      requirement_id: "r1",
      tur: "doc_vs_code",
      doc_ref: "AC2",
      kanitlar: [
        { kind: "code", repo: "demo-app", path: "api/src/demoapp_api/campaign.py", line: "23", snippet: "return adet // 6" },
        { kind: "data", query: "SELECT 1", result_digest: "sha256:x" },
        { kind: "bilinmeyen" },
      ],
      kanit_dogrulandi: true,
      severity: "blocking",
      onerilen_metin: "her 5 adede 1 bedava",
      analist_karari: "fix_doc",
      durum: "decided",
      icerik_hash: "sha256:f",
      uretim_modu: "replay_miss",
    });
    expect(b.type).toBe("doc_vs_code");
    expect(b.evidence).toEqual([
      { kind: "code", repo: "demo-app", path: "api/src/demoapp_api/campaign.py", line: 23, snippet: "return adet // 6" },
      { kind: "data", query: "SELECT 1", result_digest: "sha256:x", result_preview: null },
    ]);
    expect(b.karar).toBe("fix_doc");
    // core fix_doc düzenlemesini onerilen_metin'e yazar: karar metni odur.
    expect(b.karar_metni).toBe("her 5 adede 1 bedava");
    expect(b.mode).toBe("replay_miss");
  });

  it("kanıt doğrulandı bayrağı yalnızca açık true ise", () => {
    expect(bulguUyarla({ id: "f", kanit_dogrulandi: "true" }).kanit_dogrulandi).toBe(false);
    expect(bulguUyarla({ id: "f" }).durum).toBe("unverified");
    expect(bulguUyarla({ id: "f" }).mode).toBeNull();
  });
});

describe("case", () => {
  it("portal şekli değişmeden geçer", () => {
    for (const c of ilkVeri().caseler) {
      // v3 (011): core alanları yoksa readiness/legacy içerikten türetilir (eski case: hazır + legacy).
      expect(caseUyarla(JSON.parse(JSON.stringify(c)))).toEqual({
        ...c,
        goruntulenme: c.goruntulenme ?? null,
        readiness: c.icerik.readiness ?? "ready",
        legacy: c.icerik.readiness === undefined,
      });
    }
  });

  it("eksik içerik dizileri tamamlanır, external_key Jira anahtarı olur, mod uretim_modu'ndan", () => {
    const c = caseUyarla({ id: "c", requirement_id: "r", sira_no: 2, icerik: { title: "t", steps: [{ action: "a", expected: "e" }] }, external_key: "TPD-9", uretim_modu: "replay" });
    expect(c.icerik.steps).toEqual([{ id: "S1", action: "a", data: null, expected: "e" }]);
    expect(c.icerik.preconditions).toEqual([]);
    expect(c.jira_test_key).toBe("TPD-9");
    expect(c.mode).toBe("replay");
    expect(c.karar).toBeNull();
    expect(c.review_sure_ms).toBeNull();
  });
});

describe("yayın", () => {
  it("önizleme ve sonuç İngilizce alan adlarıyla da gelir", () => {
    const o = yayinOnizlemeUyarla({ requirement_id: "r", target: "xray", project: "TPD", items: [{ case_id: "c", title: "T", islem: "create" }], warnings: ["w"] });
    expect(o).toMatchObject({ hedef: "xray", proje: "TPD", uyarilar: ["w"] });
    expect(o.kalemler[0]).toMatchObject({ case_id: "c", summary: "T", issue_type: "Test", islem: "create" });
    const s = yayinSonucuUyarla({ results: [{ case_id: "c", durum: "created", external_key: "TPD-12", url: "http://127.0.0.1:8090/browse/TPD-12" }, { case_id: "d", durum: "boom" }] });
    expect(s.sonuclar).toEqual([
      { case_id: "c", durum: "created", external_key: "TPD-12", url: "http://127.0.0.1:8090/browse/TPD-12", hata: null },
      { case_id: "d", durum: "failed", external_key: null, url: null, hata: null },
    ]);
  });

  it("arka plan işi döndüren yayın: sonuç boş, job_id dolu", () => {
    expect(yayinSonucuUyarla({ job_id: 42, durum: "queued" })).toEqual({ hedef: "jira", sonuclar: [], job_id: "42" });
  });

  it("Jira kayıt adresi: url > browse kökü > story adresinden türetme; hiçbiri yoksa null", () => {
    expect(jiraKayitAdresi("TPD-9", { url: "https://x.atlassian.net/browse/TPD-9" })).toBe("https://x.atlassian.net/browse/TPD-9");
    expect(jiraKayitAdresi("TPD-9", { browseKoku: "http://127.0.0.1:8090/" })).toBe("http://127.0.0.1:8090/browse/TPD-9");
    expect(jiraKayitAdresi("TPD-9", { browseKoku: "http://127.0.0.1:8090/browse" })).toBe("http://127.0.0.1:8090/browse/TPD-9");
    expect(jiraKayitAdresi("TPD-9", { storyAdresi: "http://127.0.0.1:8090/browse/TPD-1" })).toBe("http://127.0.0.1:8090/browse/TPD-9");
    expect(jiraKayitAdresi("TPD-9", { url: "javascript:alert(1)" })).toBeNull();
    expect(jiraKayitAdresi(null, {})).toBeNull();
  });
});

describe("liste", () => {
  it("dizi ya da {items} kabul eder; başka şekil hata", () => {
    expect(listeUyarla([{ id: 1 }, 3], (x) => x.id)).toEqual([1]);
    expect(listeUyarla({ items: [{ id: 2 }] }, (x) => x.id)).toEqual([2]);
    expect(() => listeUyarla({}, (x) => x)).toThrow();
  });
});

describe("Faz 2 entegrasyon alanları", () => {
  it("soru düzeltme bayrağı, inceleme özeti, önceki karar ve güvenilmez denetim taşınır", async () => {
    const { onIncelemeUyarla, bulguUyarla, gereksinimDetayUyarla } = await import("./uyum");
    const on = onIncelemeUyarla({
      verdict: "needs_po",
      questions: [{ id: "Q1", type: "conflict", text: "t", ac_ref: "AC6", cevap: null, duzeltmeyle_degisti: true }],
      mode: "replay",
      zaman: "z",
      ozet: "AI özeti",
    })!;
    expect(on.questions[0].duzeltmeyle_degisti).toBe(true);
    expect(on.ozet).toBe("AI özeti");
    const b = bulguUyarla({
      id: "f", type: "missing_in_code", doc_ref: "AC4", durum: "stale", karar: "code_defect", kontrol_turu: 2,
      onceki_karar: { finding_id: "o", bulgu_no: "F4", kontrol_turu: 1, karar: "code_defect", gerekce: "g", karar_veren: "analist", karar_zamani: null },
    });
    expect(b.onceki_karar).toMatchObject({ finding_id: "o", kontrol_turu: 1, karar: "code_defect" });
    expect(bulguUyarla({ id: "x" }).onceki_karar).toBeNull();
    const d = gereksinimDetayUyarla({ id: "r", baslik: "b", durum: "findings_open", denetim_guvenilmez: "REPLAY-MISS", insan_karari_gerekli: true });
    expect(d.denetim_guvenilmez).toBe("REPLAY-MISS");
    expect(d.insan_karari_gerekli).toBe(true);
  });
});
