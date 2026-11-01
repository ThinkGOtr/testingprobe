// Faz 4 dönüştürücüleri: core triage / repair / bugs şeritlerinin gerçek yanıt şekilleri (serialize,
// views.onarim, bug_draft_view) portal türlerine eksiksiz ve uydurmasız iner.
import { describe, expect, it } from "vitest";
import { bugIcerikCoreBicimi, bugIcerikUyarla, bugTaslagiUyarla, degerlendirmeUyarla, faz4AramaUyarla, hataAnaliziUyarla, onarimUyarla, sinifUyarla } from "./uyumTriage";

const SAGLIK = {
  ok: true,
  zaman: "2026-10-31T10:00:00Z",
  web: { url: "http://demo-web:8080/", status: 200, ms: 40, hata: null },
  api: { url: "http://demo-api:8000/health", status: 200, ms: 9, hata: null },
  hata: null,
};

/** tp_core.features.triage.service.serialize çıktısı (locator önerili). */
const TRIAGE_LOCATOR = {
  id: "11111111-1111-1111-1111-111111111111",
  run_id: "22222222-2222-2222-2222-222222222222",
  test_result_id: null,
  test_adi: "katalog › sepete ekle",
  hata_imzasi: "locator_not_found:add-to-cart",
  hata_mesaji: "waiting for getByTestId('add-to-cart')",
  sinif: "test_maintenance",
  alt_tur: "locator",
  eslesen_sinyaller: [
    { kod: "saglik_ok", aciklama: "Sağlık kontrolü başarılı", kanit: "web 200" },
    { kod: "locator_0_eleman", aciklama: "add-to-cart 0 eleman", kanit: null },
  ],
  karar_kaynagi: "rule",
  kural: "test_maintenance/locator",
  gerekce: "Locator 0 eleman; rol + ad kartta var, testId farklı",
  llm_yorumu: null,
  oneri: {
    tur: "locator_fix",
    dosya: "demo-app/e2e/pages/catalog/locators.ts",
    anahtar: "addToCart",
    eski_test_id: "add-to-cart",
    yeni_test_id: "cart-add",
    rol: "button",
    ad: "Sepete ekle",
    within: "product-card-",
    scope_test_id: "product-card-P-001",
    dogrulama: ["Sağlık kontrolü başarılı"],
    durum: "proposed",
    pr: null,
    locator_key: "addToCart",
    old_testid: "add-to-cart",
    new_testid: "cart-add",
    son_yesil_run_id: "33333333-3333-3333-3333-333333333333",
    probe: { matches: 1, test_id: "cart-add" },
  },
  oneri_turu: "locator_fix",
  oneri_durumu: "none",
  oneri_yok_nedeni: null,
  bug_draft_id: null,
  kanit: {
    hata_mesaji: "waiting for getByTestId('add-to-cart')",
    beklenen: null,
    gerceklesen: null,
    konum: null,
    aria_snippet: '- button "Sepete ekle"',
    locator_probe: {
      rol: "button",
      ad: "Sepete ekle",
      scope_test_id: "product-card-P-001",
      matches: 1,
      test_id: "cart-add",
      olculen: "calisan_uygulama",
      uygulama_sha: "abc123",
      sha_eslesmesi: "eslesiyor",
      uyari: null,
      oneri_uretilebilir: true,
    },
    saglik: SAGLIK,
    hata_turu: "locator_not_found",
    adim: "CatalogPage.addToCart",
    locator: "getByTestId('add-to-cart')",
    tekrar_durumlari: ["failed", "failed"],
    deneme_durumlari: [],
    uyarilar: ["trace okunamadı"],
  },
  kanit_linkleri: [{ etiket: "Trace", url: "/artifacts/runs/x/trace.zip", tur: "trace" }],
  mode: null,
  ai_call_id: null,
  zaman: "2026-10-31T10:01:00Z",
  script_id: null,
  kaynak: "ci",
  kirma: false,
};

describe("triage dönüştürücüsü (core serialize şekli)", () => {
  it("sınıf, kural, kanıt, probe, sağlık ve öneri eksiksiz iner", () => {
    const h = hataAnaliziUyarla(TRIAGE_LOCATOR);
    expect(h).toMatchObject({ sinif: "test_maintenance", alt_tur: "locator", karar_kaynagi: "rule", kural: "test_maintenance/locator", mode: null });
    expect(h.gerekce).toMatch(/testId farklı/);
    expect(h.eslesen_sinyaller[0]).toEqual({ kod: "saglik_ok", aciklama: "Sağlık kontrolü başarılı", kaynak: "", kanit: "web 200" });
    expect(h.kanit?.locator_probe).toMatchObject({ matches: 1, test_id: "cart-add", sha_eslesmesi: "eslesiyor", scope_test_id: "product-card-P-001" });
    expect(h.kanit?.saglik?.ok).toBe(true);
    expect(h.kanit?.konum).toBe("CatalogPage.addToCart");
    expect(h.kanit?.tekrarlar).toEqual(["failed", "failed"]);
    expect(h.kanit?.uyarilar).toEqual(["trace okunamadı"]);
    expect(h.kanit_linkleri).toEqual([{ etiket: "Trace", url: "/api/artifacts/runs/x/trace.zip", tur: "trace" }]);
    expect(h.oneri).toMatchObject({ tur: "locator_fix", eski_test_id: "add-to-cart", yeni_test_id: "cart-add", within: "product-card-", durum: "proposed" });
  });

  it("birleşik sınıf (test_maintenance/locator) ve bilinmeyen değer", () => {
    expect(sinifUyarla("test_maintenance/locator")).toEqual({ sinif: "test_maintenance", alt_tur: "locator" });
    expect(sinifUyarla("ortam")).toEqual({ sinif: "environment", alt_tur: null });
    expect(sinifUyarla("bambaşka")).toEqual({ sinif: "unknown", alt_tur: null });
  });

  it("bug önerisi üst düzey bug_draft_id'den de çıkar; LLM kararı ayrı", () => {
    const h = hataAnaliziUyarla({ ...TRIAGE_LOCATOR, oneri: null, bug_draft_id: "b1", karar_kaynagi: "llm", llm_yorumu: "olası ürün hatası", mode: "replay" });
    expect(h.oneri).toEqual({ tur: "bug_draft", bug_draft_id: "b1" });
    expect(h).toMatchObject({ karar_kaynagi: "llm", llm_yorumu: "olası ürün hatası", mode: "replay" });
  });

  it("ortam hatası: sağlık başarısız, öneri yok", () => {
    const h = hataAnaliziUyarla({
      id: "f",
      run_id: "r",
      sinif: "environment",
      karar_kaynagi: "rule",
      eslesen_sinyaller: [],
      oneri: null,
      oneri_yok_nedeni: "Ortam hatası: onarım/bug yok",
      kanit: { saglik: { ok: false, web: { url: "http://w", status: null, ms: 5000, hata: "bağlantı reddedildi" }, api: null, hata: "web yanıt vermedi" } },
    });
    expect(h.sinif).toBe("environment");
    expect(h.oneri).toBeNull();
    expect(h.kanit?.saglik).toMatchObject({ ok: false, hata: "web yanıt vermedi" });
    expect(h.kanit?.saglik?.web?.hata).toBe("bağlantı reddedildi");
  });
});

describe("onarım dönüştürücüsü (repair views.onarim şekli)", () => {
  const ONARIM = {
    tur: "locator_fix",
    script_id: "s1",
    failure_id: "f1",
    script_durumu: "pr_open",
    durum: "pr_open",
    dosya: "demo-app/e2e/pages/catalog/locators.ts",
    anahtar: "catalog.addToCart",
    eski_test_id: "add-to-cart",
    yeni_test_id: "cart-add",
    rol: "button",
    ad: "Sepete ekle",
    dogrulama: ["Rol + ad eşleşmesi çalışan uygulamada tek eleman verdi"],
    probe: { matches: 1 },
    aria: { gecerli: true, kaynak: "run 3333", neden: "button \"Sepete ekle\" son yeşil koşuda var" },
    ast_guard: { ok: true, violations: [] },
    yerel_kontrol: { sonuc: "success", run_id: "r9" },
    etkilenen_testler: ["catalog.spec.ts", { test_adi: "cart.spec.ts", durum: "passed" }],
    engel: null,
    pr: { number: 21, url: null, baslik: "fix", branch: "tp/repair-addToCart", durum: "open", head_sha: "abc", icerik_hash: "sha256:x" },
    mode: null,
  };

  it("aria{gecerli}, AST, yerel kontrol (success), etkilenen testler ve PR", () => {
    const o = onarimUyarla(ONARIM);
    expect(o.durum).toBe("pr_open");
    expect(o.aria_dogrulama).toEqual({ eslesti: true, aciklama: 'run 3333: button "Sepete ekle" son yeşil koşuda var', run_id: null, kaynak: "run 3333" });
    expect(o.dogrulama_kaynagi).toBe("onarim");
    expect(o.ast_guard).toEqual({ ok: true, ihlaller: [] });
    expect(o.yerel_kontrol).toMatchObject({ sonuc: "passed", run_id: "r9" });
    expect(o.etkilenen_testler).toEqual([
      { test_adi: "catalog.spec.ts", durum: null },
      { test_adi: "cart.spec.ts", durum: "passed" },
    ]);
    expect(o.pr).toMatchObject({ number: 21, branch: "tp/repair-addToCart", durum: "open", head_sha: "abc", icerik_hash: "sha256:x" });
  });

  it("engellenen onarım (yoklama): eski/yeni testId null kalır (boş \"\" → \"\" farkı yok); bilinen aria kaynağı etikete taşınır", () => {
    const o = onarimUyarla({ ...ONARIM, script_durumu: "blocked", eski_test_id: null, yeni_test_id: null, pr: null, engel: { adim: "yoklama", neden: "sha farkli; öneri üretilmez" } });
    expect(o).toMatchObject({ durum: "failed", eski_test_id: null, yeni_test_id: null });
    const s = onarimUyarla({ ...ONARIM, aria: { gecerli: true, kaynak: "sozlesme_testi", neden: "aria snapshot dosyası yoktu" } });
    expect(s.aria_dogrulama).toMatchObject({ eslesti: true, kaynak: "sozlesme_testi", aciklama: "aria snapshot dosyası yoktu" });
    // Triage önerisi (repair bloğu yok): dogrulama triage gözlemidir.
    expect(onarimUyarla({ tur: "locator_fix", old_testid: "a", new_testid: "b", dogrulama: ["x"] }).dogrulama_kaynagi).toBe("triage");
  });

  it("engellenen onarım: script blocked → failed + engel gerekçesi; süren onarım checking", () => {
    const o = onarimUyarla({ ...ONARIM, script_durumu: "blocked", durum: "proposed", pr: null, engel: { adim: "ast_guard", neden: "role alanı değişmiş" }, ast_guard: { ok: false, violations: [{ mesaj: "field_changed: role" }] } });
    expect(o.durum).toBe("failed");
    expect(o.neden).toBe("ast_guard: role alanı değişmiş");
    expect(o.ast_guard).toEqual({ ok: false, ihlaller: ["field_changed: role"] });
    expect(onarimUyarla({ ...ONARIM, script_durumu: "checking", pr: null }).durum).toBe("checking");
  });
});

describe("bug taslağı dönüştürücüsü (bugs bug_draft_view şekli)", () => {
  const VIEW = {
    id: "b1",
    kaynak: "triage",
    failure_id: "f1",
    finding_id: null,
    icerik: {
      summary: "Sepet: 6 adet",
      steps: ["giriş", "6 adet ekle"],
      expected: "0",
      actual: "1",
      environment: "yerel",
      evidence: [{ tur: "trace", url: "/artifacts/runs/r/trace.zip", etiket: "Trace" }],
      story_key: "TPD-1",
      test_case_key: "TPD-11",
      severity_suggestion: "critical",
      labels: ["AI-generated"],
    },
    mukerrer_adaylari: [
      { key: "TPD-6", summary: "Sipariş geçmişi", status: "In Progress", skor: 0.1, rank: 2, likelihood: "low", rationale: "Farklı alan", ai: true, url: "http://jira:8090/browse/TPD-6" },
      { key: "TPD-5", summary: "Kampanya indirimi", status: "To Do", skor: 0.8, rank: 1, likelihood: "high", rationale: "Aynı belirti", ai: true, url: "http://jira:8090/browse/TPD-5" },
    ],
    karar: null,
    durum: "draft",
    link_key: null,
    icerik_hash: "sha256:h",
    onaylayan: null,
    onay_zamani: null,
    ret_gerekcesi: null,
    jira_key: null,
    jira_url: null,
    mode: "replay",
    mode_label: "REPLAY",
    olusturma: "2026-10-31T10:00:00Z",
    hazirlik: { durum: "hazir", no: 1, hata: null, job_id: null },
    uretim: "ai",
    jql: 'project = TPD AND issuetype = Bug AND text ~ "kampanya"',
    arama: { durum: "yapildi" },
    oneri: { recommendation: "link", link_key: "TPD-5", neden: null },
    dup_mode: "replay",
    yayin: {},
    mukerrer_aramasi_yapildi: true,
  };

  it("adaylar AI sırasıyla, olasılık/gerekçe/Jira adresi; arama özeti ve öneri", () => {
    const b = bugTaslagiUyarla(VIEW);
    expect(b.mukerrer_adaylari.map((a) => a.key)).toEqual(["TPD-5", "TPD-6"]);
    expect(b.mukerrer_adaylari[0]).toMatchObject({ durum: "To Do", olasilik: "high", gerekce: "Aynı belirti", sira: 1, url: "http://jira:8090/browse/TPD-5" });
    expect(b.mukerrer_arama).toMatchObject({ durum: "yapildi", oneri: "link", oneri_link_key: "TPD-5", mode: "replay", jql: VIEW.jql });
    expect(b.jira_browse_url).toBe("http://jira:8090/browse");
    expect(b.icerik.uretim).toBe("ai");
    expect(b.icerik.evidence[0].url).toBe("/api/artifacts/runs/r/trace.zip");
    expect(b.yayin_hatasi).toBeNull();
  });

  it("hazırlık sürüyor / arama atlandı / arama hatası", () => {
    expect(faz4AramaUyarla({ hazirlik: { durum: "hazirlaniyor" } })?.durum).toBe("suruyor");
    expect(faz4AramaUyarla({ hazirlik: { durum: "hazir" }, arama: { durum: "atlandi", neden: "imzada terim yok" } })).toMatchObject({ durum: "yapilmadi", neden: "imzada terim yok" });
    expect(faz4AramaUyarla({ hazirlik: { durum: "hazir" }, arama: { durum: "hata", hata: "JiraError" } })).toMatchObject({ durum: "basarisiz", hata: "JiraError" });
    expect(faz4AramaUyarla({})).toBeNull();
  });

  it("REPLAY-MISS sıralaması: adaylar AI'sız (olasılık/gerekçe yok)", () => {
    const b = bugTaslagiUyarla({ ...VIEW, dup_mode: null, oneri: { recommendation: "new", link_key: null, neden: "AI sıralaması yapılamadı: ReplayNoOutput" }, mukerrer_adaylari: VIEW.mukerrer_adaylari.map((a) => ({ ...a, rank: null, likelihood: null, rationale: null, ai: false })) });
    expect(b.mukerrer_adaylari.every((a) => a.olasilik === null && a.gerekce === "")).toBe(true);
    // Model adayları karşılaştırmadı: "yeni kayıt" önerisi uydurulmaz, istisna adı arayüze sızmaz, REPLAY-MISS etiketlenir.
    expect(b.mukerrer_arama).toMatchObject({ oneri: null, oneri_link_key: null, neden: null, mode: "replay_miss", ai_onerisi_yok: "REPLAY-MISS: kayıtlı sıralama yok" });
    expect(JSON.stringify(b.mukerrer_arama)).not.toContain("ReplayNoOutput");
  });

  it("sıralama gateway hatası (replay değil) ve tipli core nedeni; model 'new' döndürdüyse öneri korunur", () => {
    const sirasiz = VIEW.mukerrer_adaylari.map((a) => ({ ...a, rank: null, likelihood: null, rationale: null, ai: false }));
    const hata = bugTaslagiUyarla({ ...VIEW, dup_mode: null, oneri: { recommendation: "new", link_key: null, neden: "AI sıralaması yapılamadı: GatewayTimeout" }, mukerrer_adaylari: sirasiz });
    expect(hata.mukerrer_arama).toMatchObject({ oneri: null, mode: null, ai_onerisi_yok: "AI sıralaması yapılamadı" });
    const tipli = bugTaslagiUyarla({ ...VIEW, dup_mode: "replay_miss", oneri: { recommendation: null, link_key: null, neden_turu: "replay_miss" }, mukerrer_adaylari: sirasiz });
    expect(tipli.mukerrer_arama).toMatchObject({ oneri: null, mode: "replay_miss", ai_onerisi_yok: "REPLAY-MISS: kayıtlı sıralama yok" });
    const model = bugTaslagiUyarla({ ...VIEW, oneri: { recommendation: "new", link_key: null, neden: null } });
    expect(model.mukerrer_arama).toMatchObject({ oneri: "new", ai_onerisi_yok: null });
  });

  it("yayın: tamam → Jira adresi; başarısız → yayın hatası; karar yanıtı yayin_sonucu", () => {
    const pub = bugTaslagiUyarla({ id: "b1", icerik: {}, mukerrer_adaylari: [], durum: "published", karar: "link", link_key: "TPD-5", jira_key: "TPD-5", jira_url: "http://jira:8090/browse/TPD-5", yayin: { durum: "tamam", key: "TPD-5" } });
    expect(pub).toMatchObject({ durum: "published", karar: "link", jira_url: "http://jira:8090/browse/TPD-5", yayin_hatasi: null });
    expect(bugTaslagiUyarla({ ...VIEW, durum: "approved", yayin: { durum: "basarisiz", hata: "Jira 502" } }).yayin_hatasi).toBe("Jira 502");
    expect(bugTaslagiUyarla({ ...VIEW, durum: "approved", yayin: { durum: "kuyrukta" } }).yayin_suruyor).toBe(true);
    expect(bugTaslagiUyarla({ ...VIEW, durum: "approved", yayin_sonucu: { durum: "failed", hata: "zaman aşımı" } }).yayin_hatasi).toBe("zaman aşımı");
  });

  it("demo sıfırlamasında silinen Jira kaydı: browse kökünden bağlantı yeniden kurulmaz", () => {
    const sil = bugTaslagiUyarla({ ...VIEW, durum: "published", karar: "new", jira_key: "TPD-19", jira_url: null, jira_silindi: true, sonuc_metni: "Jira'da açılmıştı: TPD-19 (demo sıfırlamasında silindi)" });
    expect(sil).toMatchObject({ durum: "published", jira_key: "TPD-19", jira_url: null, jira_silindi: true });
    expect(bugTaslagiUyarla({ ...VIEW, durum: "published", karar: "new", jira_key: "TPD-18", jira_url: null }).jira_url).toMatch(/\/browse\/TPD-18$/);
  });

  it("değerlendirme durumu: yalnızca bilinen değerler", () => {
    expect(degerlendirmeUyarla("pending")).toEqual({ durum: "pending", etiket: null });
    expect(degerlendirmeUyarla({ durum: "stale", etiket: "bayat" })).toEqual({ durum: "stale", etiket: "bayat" });
    expect(degerlendirmeUyarla("bilinmez")).toBeNull();
    expect(bugTaslagiUyarla({ ...VIEW, degerlendirme: { durum: "pending" } }).degerlendirme?.durum).toBe("pending");
  });
});

describe("bugIcerikUyarla — core kanıt şeması {ref, kind}", () => {
  it("bağlantılı ve düz referanslı kanıtları ayırır", () => {
    const i = bugIcerikUyarla({
      summary: "x",
      evidence: [
        { ref: "/api/artifacts/runs/r1/src/e2e/results/artifacts/a/trace.zip", kind: "trace" },
        { ref: "/api/artifacts/runs/r1/runner.log", kind: "log" },
        { ref: "api/src/demoapp_api/campaign.py:23", kind: "code" },
      ],
    });
    expect(i.evidence).toEqual([
      { tur: "trace", url: "/api/artifacts/runs/r1/src/e2e/results/artifacts/a/trace.zip", etiket: "trace: trace.zip", ref: "/api/artifacts/runs/r1/src/e2e/results/artifacts/a/trace.zip" },
      { tur: "log", url: "/api/artifacts/runs/r1/runner.log", etiket: "log: runner.log", ref: "/api/artifacts/runs/r1/runner.log" },
      { tur: "code", url: null, etiket: "api/src/demoapp_api/campaign.py:23", ref: "api/src/demoapp_api/campaign.py:23" },
    ]);
    // Karar gövdesi core şemasına geri döner (portal alanları atılır, ham ref korunur).
    const core = bugIcerikCoreBicimi({ ...i, uretim: "ai" });
    expect(core).not.toHaveProperty("uretim");
    expect(core.evidence).toEqual([
      { kind: "trace", ref: "/api/artifacts/runs/r1/src/e2e/results/artifacts/a/trace.zip" },
      { kind: "log", ref: "/api/artifacts/runs/r1/runner.log" },
      { kind: "code", ref: "api/src/demoapp_api/campaign.py:23" },
    ]);
  });
});

describe("bug taslağı sonuç metni (core bug_draft_view.sonuc_metni)", () => {
  it("sonuç metni ve yeniden açılabilirlik portal türüne iner", () => {
    const b = bugTaslagiUyarla({ id: "b1", icerik: {}, mukerrer_adaylari: [], durum: "published", karar: "link", link_key: "TPD-5", jira_key: "TPD-5", sonuc_metni: "Mevcut kayda bağlandı: TPD-5", yeniden_acilabilir: false });
    expect(b.sonuc_metni).toBe("Mevcut kayda bağlandı: TPD-5");
    expect(b.yeniden_acilabilir).toBe(false);
    const c = bugTaslagiUyarla({ id: "b2", icerik: {}, mukerrer_adaylari: [] });
    expect(c.sonuc_metni).toBeNull();
  });
});
