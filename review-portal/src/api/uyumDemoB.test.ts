import { describe, expect, it } from "vitest";
import {
  adresUyarla,
  ajanAdimiUyarla,
  kirmaUyarla,
  kontrolKulesiUyarla,
  kosuDetayUyarla,
  prUyarla,
  scriptUyarla,
  yerelKontrolUyarla,
} from "./uyumDemoB";

describe("Demo-B uyarlayıcıları", () => {
  it("adres: tam adres ve /api/ korunur, core kök yolu /api önekini alır, göreli artefakt tahmin edilmez", () => {
    expect(adresUyarla("https://app.saucelabs.com/tests/1")).toBe("https://app.saucelabs.com/tests/1");
    expect(adresUyarla("/api/artifacts/x.png")).toBe("/api/artifacts/x.png");
    expect(adresUyarla("/runs/r1/report/index.html")).toBe("/api/runs/r1/report/index.html");
    expect(adresUyarla("screens/1.png")).toBeNull();
    expect(adresUyarla("")).toBeNull();
  });

  it("PR: GitHub check adları/sonuçları; CI özeti zorunlu check'lerden türetilir", () => {
    const pr = prUyarla({
      number: 3,
      state: "open",
      checks: [
        { name: "test-local", conclusion: "success", required: true },
        { name: "sauce", conclusion: "failure", required: false },
        { name: "semgrep", status: "in_progress", required: true },
      ],
    });
    expect(pr.checks!.map((c) => c.durum)).toEqual(["passed", "failed", "pending"]);
    expect(pr.ci).toBe("pending");
    expect(prUyarla({ number: 3, checks: [{ name: "local-ci", conclusion: "failure" }] }).ci).toBe("failed");
    expect(prUyarla({ number: 3, ci: "passed" }).ci).toBe("passed");
    expect(prUyarla({ number: 3 }).ci).toBeNull();
  });

  it("kırarak doğrulama: dizi, adlı anahtar ve sonuçtan türetilen durum", () => {
    expect(kirmaUyarla({ baseline: "passed", broken: "failed", restored: "passed" }, false).durum).toBe("passed");
    expect(kirmaUyarla({ baseline: { sonuc: "passed" }, broken: { sonuc: "passed" }, restored: { sonuc: "passed" } }, false).durum).toBe("weak");
    expect(kirmaUyarla({ durum: "running", asamalar: [{ ad: "baseline", sonuc: "running", run_id: 5 }] }, false)).toMatchObject({
      durum: "running",
      asamalar: [{ ad: "baseline", sonuc: "running", run_id: "5" }, { sonuc: "pending" }, { sonuc: "pending" }],
    });
    expect(kirmaUyarla(null, true).durum).toBe("weak");
    expect(kirmaUyarla(undefined, false).durum).toBe("not_started");
  });

  it("yerel kontrol: toolchain /check şekli; assertion → defect adayı; derleme hatası sınıfı türetilir", () => {
    expect(yerelKontrolUyarla({ tsc: { ok: true }, eslint: { ok: true }, ast_guard: { ok: true }, repeat_each: 3, run: { run_id: "r", status: "failed" }, sinif: "assertion" })).toMatchObject({
      tsc: true,
      tekrar: 3,
      sonuc: "failed",
      sinif: "defect_adayi",
      run_id: "r",
    });
    expect(yerelKontrolUyarla({ tsc: false })?.sinif).toBe("derleme");
    expect(yerelKontrolUyarla(null)).toBeNull();
  });

  it("ajan adımı: core olayında doğrulama yoksa null (izinli ≠ doğrulandı)", () => {
    const a = ajanAdimiUyarla({ script_id: "s", arac: "browser_click", ozet: "tıklandı", izinli: true }, 4);
    expect(a).toMatchObject({ sira: 4, arac: "browser_click", aciklama: "tıklandı", verified: null, ekran_goruntusu_url: null });
  });

  it("script: test_case_ids, uretim_modu, pr_no; mod bilinmiyorsa live uydurulmaz", () => {
    const s = scriptUyarla({ id: "s", test_case_ids: ["c"], durum: "pr_open", pr_no: 9, branch: "tp/case-x" });
    expect(s).toMatchObject({ case_ids: ["c"], mode: null, pr: { number: 9, branch: "tp/case-x" } });
    expect(scriptUyarla({ id: "s", durum: "bilinmeyen" }).durum).toBe("pending");
  });

  it("koşu: run tablosu kolonları (sonuc, baslama, artefaktlar, ortam.BREAK_CAMPAIGN, saglik)", () => {
    const k = kosuDetayUyarla({
      id: "r1",
      tetik: "break_verify",
      kaynak: "local",
      sonuc: "error",
      baslama: "2026-10-31T10:00:00Z",
      ortam: { BREAK_CAMPAIGN: "1" },
      artefaktlar: { html: "/runs/r1/report/index.html", saglik: { ok: false, hata: "web 502" } },
      sonuclar: [
        { id: "t1", test_adi: "a", sonuc: "passed", retry: 0 },
        { id: "t2", test_adi: "b", sonuc: "flaky", retry: 1 },
        { id: "t3", test_adi: "c", sonuc: "timedout" },
      ],
    });
    expect(k).toMatchObject({
      durum: "error",
      baslangic: "2026-10-31T10:00:00Z",
      break_campaign: true,
      rapor_url: "/api/runs/r1/report/index.html",
      saglik_hatasi: "web 502",
      toplam: 3,
      gecen: 2,
      flaky: 1,
      basarisiz: 1,
    });
    expect(k.sonuclar.map((t) => t.durum)).toEqual(["passed", "flaky", "failed"]);
  });

  it("Kontrol Kulesi: eksik ölçüler null; kaynaklar metin ya da {kaynak}", () => {
    const k = kontrolKulesiUyarla({ gecme_orani: 0.8, ai_katkisi: {}, kaynaklar: { flaky: "test_result", a11y: { kaynak: "axe" }, bilinmeyen: "x" } });
    expect(k.gecme_orani.oran).toBe(0.8);
    expect(k.ai_katkisi).toMatchObject({ kabul_orani: null, manuel_baz_ms: null, maliyet_usd_toplam: null, kabul_hedefi: 0.7 });
    expect(k.a11y).toBeNull();
    expect(k.kaynaklar).toEqual({ flaky: "test_result", a11y: "axe" });
    expect(k.gecme_hedefi).toBeNull();
  });
});

describe("core codegen views.detail şekli", () => {
  const govde = {
    id: "s-1",
    case_ids: ["c-1"],
    requirement_key: "TPD-1",
    baslik: "6 adet",
    dosya_yolu: "e2e/tests/generated/tpd-1/c3.spec.ts",
    branch: "tp/case-x",
    durum: "blocked",
    pr: null,
    pass_at_1: false,
    zayif_test: false,
    break_verify: { durum: "not_started", asamalar: [{ ad: "baseline", sonuc: "pending", run_id: null, zaman: null }], neden: null },
    yerel_sinif: "defect_adayi",
    mode: "replay",
    engel: { tur: "defect_candidate", neden: "assertion" },
    olusturma: "2026-10-31T10:00:00Z",
    hata: "assertion",
    kod: "x",
    adimlar: [{ sira: 1, step_id: "", arac: "browser_navigate", aciklama: "goto", po: null, method: null, args: [], verified: true, izinli: true, ekran_goruntusu_url: "/api/scripts/s-1/screenshots/1", zaman: "t" }],
    eslemeler: [{ adim_no: 1, step_id: "S4", po: "CartPage", method: "expectDiscount", args: ["0,00 TL"], beklenen: true, verified: true, kaynak_metin: "indirim 0,00 TL", kanit_ref: null }],
    yerel_kontrol: { tsc: true, eslint: true, ast_guard: true, tekrar: 3, sonuc: "failed", sinif: "defect_adayi", aciklama: "Defect adayı", run_id: "r", duzeltme_turu: 0, basarisiz: [], atlandi: false },
    merge_engelleri: ["PR merge edilebilir durumda değil (durum: blocked)"],
    uyarilar: ["Eşleme REPLAY kaydından geldi"],
  };
  it("izinli ham adımın 'verified'ı gösterilmez; engel, uyarılar, eşleme, yerel kontrol uyarlanır", async () => {
    const { scriptDetayUyarla } = await import("./uyumDemoB");
    const s = scriptDetayUyarla(govde);
    expect(s.adimlar[0]).toMatchObject({ verified: null, ekran_goruntusu_url: "/api/scripts/s-1/screenshots/1" });
    expect(s).toMatchObject({ engel: { tur: "defect_candidate" }, yerel_sinif: "defect_adayi", uyarilar: ["Eşleme REPLAY kaydından geldi"], mode: "replay" });
    expect(s.eslemeler[0]).toMatchObject({ beklenen: true, kaynak_metin: "indirim 0,00 TL" });
    expect(s.yerel_kontrol).toMatchObject({ sonuc: "failed", sinif: "defect_adayi" });
  });
  it("merge kapısı: core'un gerekçeleri tek kaynak; kırma yapılmadı kapı değil, kabul isteyen uyarı", async () => {
    const { mergeEngelleri, mergeUyarilari } = await import("../lib/kapi");
    const { scriptDetayUyarla } = await import("./uyumDemoB");
    const s = scriptDetayUyarla({
      ...govde,
      durum: "pr_open",
      yerel_sinif: "gecti",
      engel: null,
      pr: { number: 3, durum: "open", ci: "passed", head_sha: "a", icerik_hash: "h", checks: [] },
      merge_engelleri: [],
    });
    expect(mergeEngelleri(s)).toEqual([]);
    expect(mergeUyarilari(s)).toEqual([expect.stringMatching(/^Kırarak doğrulama yapılmadı/)]);
    // core enum'ları Türkçe gösterilir
    expect(mergeEngelleri({ ...s, merge_engelleri: ["PR merge edilebilir durumda değil (durum: blocked)"] })).toEqual([
      "PR merge edilebilir durumda değil (durum: insana düştü)",
    ]);
    const kosuyor = { ...s, break_verify: { ...s.break_verify, durum: "running" as const }, merge_engelleri: ["Kırarak doğrulama sürüyor"] };
    expect(mergeEngelleri(kosuyor)).toEqual(["Kırarak doğrulama sürüyor"]);
  });
  it("merge kabulü: core'un merge_kabul_gerekli listesi tek kaynak; boşsa not gönderilmez", async () => {
    const { mergeUyarilari, mergeOnayNotu } = await import("../lib/kapi");
    const { scriptDetayUyarla } = await import("./uyumDemoB");
    const temel = {
      ...govde,
      durum: "pr_open",
      yerel_sinif: "gecti",
      engel: null,
      pr: { number: 3, durum: "open", ci: "passed", head_sha: "a", icerik_hash: "h", checks: [] },
      merge_engelleri: [],
    };
    const zayif = scriptDetayUyarla({ ...temel, merge_kabul_gerekli: ["Zayıf test: kırılmada yeşil kaldı (açık kabul gerekir)."] });
    expect(mergeUyarilari(zayif)).toEqual(["Zayıf test: kırılmada yeşil kaldı (açık kabul gerekir)."]);
    expect(mergeOnayNotu(zayif)).toBeTruthy();
    const temiz = scriptDetayUyarla({ ...temel, merge_kabul_gerekli: [] });
    expect(mergeUyarilari(temiz)).toEqual([]);
    expect(mergeOnayNotu(temiz)).toBeNull();
  });
  it("ajan adımı ham çıktısı ve eşleme doğrulama notu uyarlanır", async () => {
    const { scriptDetayUyarla } = await import("./uyumDemoB");
    const s = scriptDetayUyarla({
      ...govde,
      adimlar: [{ sira: 1, arac: "browser_type", aciklama: "Parola yazıldı", ham_cikti: "fill('***')", izinli: true }],
      eslemeler: [{ adim_no: 1, step_id: "S2", po: "LoginPage", method: "login", args: ["bayi1"], verified: true, dogrulama_notu: "doğrulandı (ajan bayisi bayi3 ile; test bayi1 ile koşar)" }],
    });
    expect(s.adimlar[0]).toMatchObject({ aciklama: "Parola yazıldı", ham_cikti: "fill('***')" });
    expect(s.eslemeler[0].dogrulama_notu).toMatch(/ajan bayisi bayi3/);
  });
});
