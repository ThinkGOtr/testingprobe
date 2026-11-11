import type { LocatorOnarimi } from "../types";
import { beforeEach, describe, expect, it } from "vitest";
import { api } from "../client";
import { ApiError } from "../http";
import { sha256Hex, kanonikJson } from "../../lib/sha256";
import { ayar, mockOrtam, mockPoEtiketi, mockVerisi } from "./handlers";

// Mock arka plan işleri setTimeout zinciridir; sabit süre yük altında yetmez: işler bitene dek bekle.
const bekleIsler = async () => {
  const { bekleyenMockIs } = await import("./handlers");
  const son = Date.now() + 5000;
  do await new Promise((r) => setTimeout(r, 10));
  while (bekleyenMockIs() > 0 && Date.now() < son);
};

// Kararlar ekranda görülen içeriğin hash'ini taşır (§5): testler de GET'ten okunan değeri gönderir.
const v = () => mockVerisi();
const bulguH = (id: string) => ({ icerik_hash: v().bulgular.find((b) => b.id === id)!.icerik_hash });
const caseH = (id: string) => ({ icerik_hash: v().caseler.find((c) => c.id === id)!.icerik_hash });
const bugH = (id: string) => ({ icerik_hash: v().bugTaslaklari.find((b) => b.id === id)!.icerik_hash });
const scriptPr = (id: string) => v().scriptler.find((s) => s.id === id)!.pr!;

async function girisYap(k: string) {
  await api.logout().catch(() => undefined);
  return api.login(k, "Demo123!");
}

/** Testçi kabul eder, Analist son onayı verir (ANALIZ 012 §5); oturum Analist'te kalır. */
async function kabulVeOnay(id: string) {
  await girisYap("testci");
  await api.caseKarari(id, { ...caseH(id), karar: "accept" });
  await girisYap("analist");
  return api.caseKarari(id, { ...caseH(id), karar: "approve" });
}

describe("mock arka uç: oturum ve roller", () => {
  beforeEach(() => {
    ayar.isAdimiMs = 0;
  });

  it("oturumsuz istek 401, hatalı giriş 401", async () => {
    await expect(api.gereksinimler()).rejects.toMatchObject({ status: 401 });
    await expect(api.login("yok", "x")).rejects.toMatchObject({ status: 401, detail: "Kullanıcı adı veya parola hatalı." });
    await expect(api.login("analist", "")).rejects.toBeInstanceOf(ApiError);
  });

  it("rol yetkisi her uçta kontrol edilir", async () => {
    await girisYap("muhendis");
    await expect(api.jiradanCek()).rejects.toMatchObject({ status: 403 });
    await expect(api.caseUret("req-tpd-1")).rejects.toMatchObject({ status: 403, kod: "yetki_yok" });
    await expect(api.bugKarari("bug-1", { ...bugH("bug-1"), karar: "new" })).rejects.toMatchObject({ status: 403 });
    await expect(api.tokenOlustur("submit")).rejects.toMatchObject({ status: 403 });
  });

  it("/auth/me izinleri rolün katalogdaki izinleridir (core rol_izinleri)", async () => {
    const { rolIzinleri } = await import("../../lib/yetki");
    for (const k of ["sunucu", "denetci", "analist", "po", "testci", "muhendis", "gelistirici", "izleyici"]) {
      await girisYap(k);
      const me = await api.me();
      expect(me.izinler).toEqual(rolIzinleri(me.rol));
    }
    await girisYap("sunucu");
    expect((await api.me()).rol).toBe("admin");
  });

  it("CI tetikleri: engineer hepsi; developer yalnız manuel ve prod dışında; diğerleri 403", async () => {
    await girisYap("muhendis");
    await expect(api.ciTetikle("deploy")).resolves.toMatchObject({ durum: "queued" });
    await expect(api.ciTetikle("manual")).resolves.toMatchObject({ durum: "queued" });
    await girisYap("gelistirici");
    await expect(api.ciTetikle("nightly")).rejects.toMatchObject({ status: 403, kod: "yetki_yok" });
    await expect(api.ciTetikle("manual")).resolves.toMatchObject({ durum: "queued" });
    mockOrtam.ortam = "prod";
    try {
      await expect(api.ciTetikle("manual")).rejects.toMatchObject({ status: 403 });
    } finally {
      mockOrtam.ortam = "dev";
    }
    for (const k of ["sunucu", "testci", "izleyici"]) {
      await girisYap(k);
      await expect(api.ciTetikle("manual")).rejects.toMatchObject({ status: 403 });
    }
  });

  it("demo kontrolleri: admin + engineer, yalnız demo kipinde", async () => {
    await girisYap("testci");
    await expect(api.demoSifirla()).rejects.toMatchObject({ status: 403, kod: "yetki_yok" });
    await girisYap("muhendis");
    mockOrtam.demoModu = false;
    try {
      expect((await api.demoDurumu()).demo_modu).toBe(false);
      await expect(api.demoSifirla()).rejects.toMatchObject({ status: 403 });
    } finally {
      mockOrtam.demoModu = true;
    }
    await expect(api.demoSifirla()).resolves.toMatchObject({ durum: "done" });
  });

  it("portal PO onayı Jira story'sinde 410 (po_onayi_jira); serbest metinde hash ister; denetim kaydı rolün kapsamıyla", async () => {
    await girisYap("po");
    const tpd = v().gereksinimler.find((g) => g.id === "req-tpd-1")!;
    tpd.durum = "pending_po";
    await expect(api.poOnayla(tpd)).rejects.toMatchObject({ status: 410, kod: "po_onayi_jira" });
    expect(tpd.durum).toBe("pending_po");
    const ft = v().gereksinimler.find((g) => g.id === "req-ft-1")!;
    ft.durum = "pending_po";
    const gorulen = { id: ft.id, icerik_hash: ft.icerik_hash };
    await expect(api.poOnayla({ id: ft.id } as never)).rejects.toMatchObject({ status: 422 });
    ft.aciklama = `${ft.aciklama} (PO görmeden değişti)`;
    await expect(api.poOnayla(gorulen)).rejects.toMatchObject({ status: 409 });
    await expect(api.poOnayla(await api.gereksinim("req-ft-1"))).resolves.toMatchObject({ durum: "po_approved" });
    await girisYap("analist");
    await expect(api.poOnayla(await api.gereksinim("req-ft-1"))).rejects.toMatchObject({ status: 403 });
    await girisYap("testci");
    const kendi = await api.denetim(false);
    expect(kendi.olaylar.every((o) => o.aktor === "testci")).toBe(true);
    await expect(api.denetim(true)).rejects.toMatchObject({ status: 403 });
    await girisYap("denetci");
    const tum = await api.denetim(true);
    expect(tum.dogrulama?.gecerli).toBe(true);
    expect(new Set(tum.olaylar.map((o) => o.aktor)).size).toBeGreaterThan(1);
    await girisYap("izleyici");
    await expect(api.denetim(false)).rejects.toMatchObject({ status: 403 });
  });
});

describe("mock arka uç: tutarlılık → PO → case (insan kapıları)", () => {
  beforeEach(() => {
    ayar.isAdimiMs = 0;
  });

  it("bilinçli fark gerekçesiz reddedilir", async () => {
    await girisYap("analist");
    await expect(api.bulguKarari("fnd-5", { ...bulguH("fnd-5"), karar: "accept_difference" })).rejects.toMatchObject({ status: 422 });
    await expect(api.bulguKarari("fnd-5", { ...bulguH("fnd-5"), karar: "accept_difference", gerekce: "  " })).rejects.toMatchObject({
      status: 422,
    });
  });

  it("serbest metin akışı: kararlar → düzeltmeler → PO teyidi → case üretimi", async () => {
    await girisYap("testci");
    await expect(api.caseUret("req-ft-1")).rejects.toMatchObject({ status: 409 });
    await girisYap("analist");
    await expect(api.duzeltmeleriUygula("req-ft-1")).rejects.toMatchObject({ status: 409 });

    const bulgular = await api.bulgular("req-ft-1");
    const h5 = bulgular.find((b) => b.id === "fnd-5")!.icerik_hash;
    const h6 = bulgular.find((b) => b.id === "fnd-6")!.icerik_hash;
    await api.bulguKarari("fnd-5", { icerik_hash: h5, karar: "fix_doc", metin: "Kaldırma sonrası indirim her 6 adette 1 bedava kuralıyla hesaplanır." });
    await api.bulguKarari("fnd-6", { icerik_hash: h6, karar: "accept_difference", gerekce: "Ayar değeri ürün kararıyla 750" });
    // Doküman düzeltmesini Analist uygular (requirement.review); PO uygulayamaz.
    await girisYap("po");
    await expect(api.duzeltmeleriUygula("req-ft-1")).rejects.toMatchObject({ status: 403, kod: "yetki_yok" });
    await girisYap("analist");
    await api.duzeltmeleriUygula("req-ft-1");
    await bekleIsler();

    let g = await api.gereksinim("req-ft-1");
    expect(g.durum).toBe("pending_po");
    expect(g.kabul_kriterleri[1].metin).toBe("Kaldırma sonrası indirim her 6 adette 1 bedava kuralıyla hesaplanır.");
    expect(g.kontrol_turu).toBe(2);
    // fix_doc yazıldı → resolved (core: decided → resolved); "applied" diye ayrı durum yok.
    // Karar verilmemiş F3 yeni turda geçersizleşir (open → stale); 2. tur golden'ı (SERBEST-r2) bulgusuz.
    expect((await api.bulgular("req-ft-1")).map((b) => [b.id, b.durum])).toEqual([
      ["fnd-5", "resolved"],
      ["fnd-6", "resolved"],
      ["fnd-9", "stale"],
    ]);

    // Serbest metinde PO teyidi portalda yalnız PO rolüyle (requirement.po_approve_free_text); case üretimi Testçide.
    await expect(api.poOnayla(g)).rejects.toMatchObject({ status: 403 });
    await girisYap("po");
    g = await api.poOnayla(g);
    expect(g.po).toMatchObject({ durum: "approved", onaylayan: "po", kanal: "portal" });

    await girisYap("testci");
    await api.caseUret("req-ft-1");
    await bekleIsler();
    const caseler = await api.caseler("req-ft-1");
    // Analist AC2'yi golden önerisinden farklı yazdı: case golden'ının girdisi tutmaz → REPLAY-MISS
    // (kural tabanlı yedek iskelet; canlı ya da replay gibi gösterilmez).
    expect(caseler.length).toBe(3);
    expect(caseler.every((c) => c.durum === "draft" && c.mode === "replay_miss")).toBe(true);
    expect((await api.gereksinim("req-ft-1")).durum).toBe("cases_ready");
  });

  it("serbest metin golden önerileri kabul edilince case'ler SERBEST case golden'ından (REPLAY)", async () => {
    await girisYap("analist");
    const h = (id: string) => mockVerisi().bulgular.find((b) => b.id === id)!.icerik_hash;
    await api.bulguKarari("fnd-5", { icerik_hash: h("fnd-5"), karar: "fix_doc" });
    await api.bulguKarari("fnd-6", { icerik_hash: h("fnd-6"), karar: "fix_doc" });
    await api.bulguKarari("fnd-9", { icerik_hash: h("fnd-9"), karar: "accept_difference", gerekce: "F2 ile aynı AC3 düzeltmesi" });
    await api.duzeltmeleriUygula("req-ft-1");
    await bekleIsler();
    expect((await api.gereksinim("req-ft-1")).durum).toBe("pending_po");
    await girisYap("po");
    await api.poOnayla(await api.gereksinim("req-ft-1"));
    await girisYap("testci");
    await api.caseUret("req-ft-1");
    await bekleIsler();
    const { KAYNAK } = await import("./fixtures");
    const caseler = await api.caseler("req-ft-1");
    expect(caseler.map((c) => c.icerik)).toEqual(KAYNAK.case_generation.SERBEST.cases);
    expect(caseler.every((c) => c.mode === "replay")).toBe(true);
  });

  it("code_defect kararı bug taslağı oluşturur", async () => {
    await girisYap("analist");
    const b = await api.bulguKarari("fnd-5", { ...bulguH("fnd-5"), karar: "code_defect" });
    expect(b.bug_draft_id).toBeTruthy();
    const taslak = await api.bugTaslagi(b.bug_draft_id!);
    expect(taslak).toMatchObject({ kaynak: "consistency", finding_id: "fnd-5", durum: "draft" });
  });
});

describe("mock arka uç: case kararı ve yayın", () => {
  it("ret nedeni zorunlu; düzeltme hash'i günceller; Analist onaylar; yalnızca onaylılar yayınlanır", async () => {
    await girisYap("testci");
    await expect(api.caseKarari("case-1-5", { ...caseH("case-1-5"), karar: "reject" })).rejects.toMatchObject({ status: 422 });

    const once = (await api.caseler("req-tpd-1")).find((c) => c.id === "case-1-5")!;
    let p = await api.yayinOnizleme("req-tpd-1");
    expect(p.kalemler.find((k) => k.case_id === "case-1-5")?.islem).toBe("blocked_not_approved");
    expect(p.kalemler.find((k) => k.case_id === "case-1-1")?.islem).toBe("skip_existing");
    expect(p.kalemler.some((k) => k.case_id === "case-1-6")).toBe(false);

    const duzeltilmis = await api.caseKarari("case-1-5", {
      icerik_hash: once.icerik_hash,
      karar: "edit",
      icerik: { ...once.icerik, title: `${once.icerik.title} (düzeltildi)` },
    });
    expect(duzeltilmis.durum).toBe("ready");
    expect(duzeltilmis.icerik_hash).not.toBe(once.icerik_hash);
    expect(duzeltilmis.onaylanan_hash).toBeNull();
    expect(duzeltilmis.duzeltme_olcusu).toBeGreaterThan(0);
    // Testçi son onayı veremez; Analist yalnız `ready` case'i onaylar.
    await expect(api.caseKarari("case-1-5", { ...caseH("case-1-5"), karar: "approve" })).rejects.toMatchObject({ status: 403 });
    p = await api.yayinOnizleme("req-tpd-1");
    expect(p.kalemler.find((k) => k.case_id === "case-1-5")?.islem).toBe("blocked_not_approved");
    await girisYap("analist");
    await expect(api.caseKarari("case-1-5", { ...caseH("case-1-5"), karar: "accept" })).rejects.toMatchObject({ status: 403 });
    const onayli = await api.caseKarari("case-1-5", { ...caseH("case-1-5"), karar: "approve" });
    expect(onayli).toMatchObject({ durum: "approved", onaylayan: "analist", testci_karari: "edit" });
    expect(onayli.onaylanan_hash).toBe(onayli.icerik_hash);
    await expect(api.yayinOnizleme("req-tpd-1")).rejects.toMatchObject({ status: 403 });

    await girisYap("testci");
    p = await api.yayinOnizleme("req-tpd-1");
    expect(p.kalemler.find((k) => k.case_id === "case-1-5")?.islem).toBe("create");
    const s = await api.yayinla(["case-1-5", "case-1-1", "case-1-6"]);
    expect(s.sonuclar.map((x) => x.durum)).toEqual(["created", "exists", "failed"]);
    await expect(api.caseKarari("case-1-5", { ...caseH("case-1-5"), karar: "accept" })).rejects.toMatchObject({ status: 409 });
  });

  it("Analist geri gönderme gerekçe ister ve case'i taslağa döndürür; developer yalnız onaylıları görür", async () => {
    await girisYap("testci");
    await api.caseKarari("case-1-5", { ...caseH("case-1-5"), karar: "accept" });
    await girisYap("analist");
    await expect(api.caseKarari("case-1-5", { ...caseH("case-1-5"), karar: "send_back" })).rejects.toMatchObject({ status: 422 });
    const geri = await api.caseKarari("case-1-5", { ...caseH("case-1-5"), karar: "send_back", gerekce: "AC2 adımı eksik" });
    expect(geri).toMatchObject({ durum: "draft", karar: "send_back", gerekce: "AC2 adımı eksik" });
    await expect(api.caseKarari("case-1-5", { ...caseH("case-1-5"), karar: "send_back", gerekce: "x" })).rejects.toMatchObject({ status: 409 });

    await girisYap("gelistirici");
    const gorunen = await api.caseler("req-tpd-1");
    expect(gorunen.length).toBeGreaterThan(0);
    expect(gorunen.every((c) => c.durum === "approved" || c.durum === "published")).toBe(true);
    expect(gorunen.every((c) => c.karar === null && c.karar_veren === null)).toBe(true);
    await expect(api.caseKarari("case-1-5", { ...caseH("case-1-5"), karar: "accept" })).rejects.toMatchObject({ status: 403 });
  });
});

describe("mock arka uç: kod, kırma, merge, onarım, bug", () => {
  beforeEach(() => {
    ayar.isAdimiMs = 0;
  });

  it("replay ıskalanan case için PR açılmaz (REPLAY-MISS, sahte başarı yok)", async () => {
    await girisYap("muhendis");
    await expect(api.kodUret(["case-1-5"])).rejects.toMatchObject({ status: 409 });
    // case-1-1'in örnek veride doğrulama/eşleme golden'ı yok: başka case'in adımları gösterilmez.
    await api.kodUret(["case-1-1"]);
    for (let i = 0; i < 14; i++) await bekleIsler();
    const s = (await api.scriptler()).find((x) => x.case_ids.includes("case-1-1") && x.id !== "scr-1")!;
    const detay = await api.script(s.id);
    expect(detay.adimlar).toEqual([]);
    expect(detay).toMatchObject({ mode: "replay_miss", durum: "failed", pr: null, zayif_test: false, kod: null, eslemeler: [] });
    expect(detay.hata).toContain("REPLAY-MISS");
  });

  it("Demo-B: assertion kırmızısı defect adayıdır (PR yok, insana düşer); minimum sipariş case'i PR açar", async () => {
    await girisYap("muhendis");
    await api.kodUret(["case-1-4"]);
    for (let i = 0; i < 20; i++) await bekleIsler();
    const yeni = (await api.scriptler()).find((x) => x.case_ids.includes("case-1-4"))!;
    const d4 = await api.script(yeni.id);
    expect(d4).toMatchObject({ mode: "replay", durum: "pr_open", yerel_sinif: "gecti", pass_at_1: true });
    expect(d4.pr?.checks).toEqual([expect.objectContaining({ ad: "local-ci", durum: "passed", zorunlu: true })]);
    expect(d4.eslemeler.find((e) => e.method === "expectMinOrderWarning")).toMatchObject({
      beklenen: true,
      verified: true,
      args: ["Minimum sipariş tutarı 750,00 TL"],
    });
    expect(d4.kod).toContain('expectMinOrderWarning("Minimum sipariş tutarı 750,00 TL")');
    const kontrol = await api.kosu(d4.yerel_kontrol!.run_id!);
    expect(kontrol).toMatchObject({ tetik: "local_check", durum: "passed", script_id: yeni.id });

    const d3 = await api.script("scr-3");
    expect(d3).toMatchObject({ durum: "blocked", pr: null, yerel_sinif: "defect_adayi" });
    expect(d3.yerel_kontrol).toMatchObject({ sonuc: "failed", sinif: "defect_adayi", duzeltme_turu: 0 });
  });

  it("kırarak doğrulama sürerken merge reddedilir (core request_merge); bitince kabul edilir", async () => {
    await girisYap("muhendis");
    const s = mockVerisi().scriptler.find((x) => x.id === "scr-2")!;
    s.break_verify = { durum: "not_started", asamalar: [] };
    s.durum = "pr_open";
    await api.kirarakDogrula("scr-2");
    expect((await api.script("scr-2")).break_verify.durum).toBe("running");
    await expect(api.prBirlestir(scriptPr("scr-2"))).rejects.toMatchObject({ status: 409 });
    for (let i = 0; i < 10; i++) await bekleIsler();
    const sonra = await api.script("scr-2");
    expect(sonra.break_verify.asamalar.map((a) => a.sonuc)).toEqual(["passed", "failed", "passed"]);
    // core durumu pr_open kalır; "merge'e hazır" türetilir (scriptIsareti).
    expect(sonra).toMatchObject({ durum: "pr_open", zayif_test: false });
    expect(await api.prBirlestir(sonra.pr!)).toMatchObject({ birlesti: true, mesaj: "PR #12 birleştirildi." });
    expect((await api.script("scr-2")).durum).toBe("merged");
    await expect(api.prBirlestir(sonra.pr!)).rejects.toMatchObject({ status: 409 });
  });

  it("zayıf test işaretli PR merge edilebilir (işaret, kapı değil); kabul notu denetime yazılır", async () => {
    await girisYap("muhendis");
    const s = await api.script("scr-1");
    expect(s).toMatchObject({ durum: "pr_open", zayif_test: true });
    expect(await api.prBirlestir({ ...s.pr!, onay_notu: "Zayıf test olarak merge edildi (insan kabulü)." })).toMatchObject({ birlesti: true });
    const sonra = await api.script("scr-1");
    expect(sonra.durum).toBe("merged");
    expect(sonra.pr).toMatchObject({ durum: "merged", merge_eden: "muhendis" });
    expect(sonra.pr?.merge_sha).toBeTruthy();
    expect(mockVerisi().denetim.at(-1)).toMatchObject({ eylem: "pr.merge", ozet: expect.stringContaining("Zayıf test olarak merge edildi") });
  });

  it("locator onarım PR'ı yalnızca bir kez açılır", async () => {
    await girisYap("muhendis");
    await api.onarimPrAc("fail-2");
    // İş sürerken (AST koruması → yerel kontrol → bot PR) ikinci istek de reddedilir.
    expect((await api.hata("fail-2")).oneri).toMatchObject({ durum: "checking" });
    await expect(api.onarimPrAc("fail-2")).rejects.toMatchObject({ status: 409 });
    await expect(api.onarimPrAc("fail-1")).rejects.toMatchObject({ status: 409 });
    // Ortam hatası için onarım yok.
    await expect(api.onarimPrAc("fail-3")).rejects.toMatchObject({ status: 409 });
    await bekleIsler();
    const h = await api.hata("fail-2");
    expect(h.oneri).toMatchObject({ tur: "locator_fix", durum: "pr_open", eski_test_id: "add-to-cart", yeni_test_id: "cart-add" });
    const o = h.oneri as LocatorOnarimi;
    expect(o.ast_guard).toEqual({ ok: true, ihlaller: [] });
    expect(o.yerel_kontrol).toMatchObject({ sonuc: "passed", gecen: 3, toplam: 3 });
    expect(o.degisen_dosyalar).toEqual(["demo-app/e2e/pages/catalog/locators.ts"]);
    expect(o.pr).toMatchObject({ branch: "tp/repair-addToCart", ci: "passed" });
  });

  it("bug taslağı: link anahtarı doğrulanır, karar bir kez verilir", async () => {
    await girisYap("testci");
    const taslak = await api.bugTaslagi("bug-1");
    await expect(api.bugKarari("bug-1", { icerik_hash: taslak.icerik_hash, karar: "link", link_key: "yanlis" })).rejects.toMatchObject({
      status: 422,
    });
    const b = await api.bugKarari("bug-1", { icerik_hash: taslak.icerik_hash, karar: "link", link_key: "tpd-5" });
    // core bug_draft makinesi: "linked" diye durum yok → published + karar link + link_key.
    expect(b).toMatchObject({ durum: "published", karar: "link", link_key: "TPD-5", jira_key: "TPD-5", onaylayan: "testci" });
    await expect(api.bugKarari("bug-1", { ...bugH("bug-1"), karar: "new" })).rejects.toMatchObject({ status: 409 });
  });

  it("bug taslağı reddedilebilir (dismiss → dismissed); Jira'ya yazılmaz", async () => {
    await girisYap("testci");
    // core: ret gerekçesi zorunlu (422).
    await expect(api.bugKarari("bug-1", { ...bugH("bug-1"), karar: "dismiss" })).rejects.toMatchObject({ status: 422 });
    const b = await api.bugKarari("bug-1", { ...bugH("bug-1"), karar: "dismiss", gerekce: "kasıtlı kırma koşusu" });
    expect(b).toMatchObject({ durum: "dismissed", karar: "dismiss", jira_key: null, link_key: null, ret_gerekcesi: "kasıtlı kırma koşusu" });
    // Taslağa al (reopen) → yeniden karar bekler.
    const r = await api.bugKarari("bug-1", { ...bugH("bug-1"), karar: "reopen" });
    expect(r).toMatchObject({ durum: "draft", karar: null });
    // Reddedilmişken taslağa alınmadan karar verilemez; taslağa alınca yeniden karar verilebilir.
    await api.bugKarari("bug-1", { ...bugH("bug-1"), karar: "dismiss", gerekce: "yine değil" });
    await expect(api.bugKarari("bug-1", { ...bugH("bug-1"), karar: "new" })).rejects.toMatchObject({ status: 409 });
  });
});

describe("mock arka uç: denetim zinciri", () => {
  it("zincir sha256(prev_hash + kanonik JSON) ile hesaplanır ve doğrulanır", async () => {
    await girisYap("denetci");
    const d = await api.denetim(true);
    expect(d.dogrulama?.gecerli).toBe(true);
    const sirali = [...d.olaylar].sort((a, b) => a.sira - b.sira);
    let onceki = "0".repeat(64);
    for (const o of sirali) {
      expect(o.prev_hash).toBe(onceki);
      const ham = mockVerisi().denetim[o.sira - 1];
      expect(o.hash).toBe(sha256Hex(onceki + kanonikJson(ham)));
      onceki = o.hash;
    }
    expect(d.dogrulama?.son_hash).toBe(onceki);
  });
});

describe("mock arka uç: karar içerik bağı (icerik_hash, TOCTOU — MIMARI-SOZLESME §5)", () => {
  beforeEach(() => {
    ayar.isAdimiMs = 0;
  });

  // core record_approval ile aynı: hash yoksa 422, eskiyse 409 ve karar kaydedilmez.
  it("bulgu kararı: hash yoksa 422, eskiyse 409; karar yazılmaz", async () => {
    await girisYap("analist");
    const govde = { karar: "code_defect" as const };
    await expect(api.bulguKarari("fnd-5", govde as never)).rejects.toMatchObject({ status: 422 });
    await expect(api.bulguKarari("fnd-5", { ...govde, icerik_hash: "" })).rejects.toMatchObject({ status: 422 });
    const gorulen = bulguH("fnd-5");
    // Analist ekrana baktıktan sonra bulgunun önerisi değişti (ör. yeni kontrol turu).
    v().bulgular.find((b) => b.id === "fnd-5")!.suggested_doc_text = "Başka bir öneri";
    await expect(api.bulguKarari("fnd-5", { ...govde, ...gorulen })).rejects.toMatchObject({ status: 409 });
    expect(v().bulgular.find((b) => b.id === "fnd-5")!).toMatchObject({ karar: null, durum: "open" });
    // Güncel içerikle (yeniden yüklenen hash) karar kabul edilir.
    const guncel = (await api.bulgular("req-ft-1")).find((b) => b.id === "fnd-5")!;
    expect(guncel.icerik_hash).not.toBe(gorulen.icerik_hash);
    await expect(api.bulguKarari("fnd-5", { ...govde, icerik_hash: guncel.icerik_hash })).resolves.toMatchObject({ durum: "resolved" });
  });

  it("kanıtı doğrulanmamış (unverified) bulguya karar verilemez", async () => {
    await girisYap("analist");
    const b = v().bulgular.find((x) => x.id === "fnd-6")!;
    b.durum = "unverified";
    await expect(api.bulguKarari("fnd-6", { ...bulguH("fnd-6"), karar: "fix_doc", metin: "x" })).rejects.toMatchObject({ status: 409 });
  });

  it("case kararı: hash yoksa 422, düzeltme sonrası eski hash'le kabul 409", async () => {
    await girisYap("testci");
    await expect(api.caseKarari("case-1-7", { karar: "accept" } as never)).rejects.toMatchObject({ status: 422 });
    const gorulen = caseH("case-1-7");
    const c = v().caseler.find((x) => x.id === "case-1-7")!;
    // Aynı case başka kanaldan (IDE) düzeltildi: içerik ve hash değişti.
    c.icerik = { ...c.icerik, title: `${c.icerik.title} (IDE)` };
    c.icerik_hash = `sha256:${"0".repeat(16)}`;
    await expect(api.caseKarari("case-1-7", { ...gorulen, karar: "accept" })).rejects.toMatchObject({ status: 409 });
    expect(v().caseler.find((x) => x.id === "case-1-7")!.durum).toBe("draft");
  });

  it("bug kararı: hash yoksa 422, taslak değiştiyse 409", async () => {
    await girisYap("testci");
    await expect(api.bugKarari("bug-1", { karar: "new" } as never)).rejects.toMatchObject({ status: 422 });
    const gorulen = bugH("bug-1");
    v().bugTaslaklari.find((b) => b.id === "bug-1")!.icerik.actual = "değişti";
    await expect(api.bugKarari("bug-1", { ...gorulen, karar: "new" })).rejects.toMatchObject({ status: 409 });
    expect(v().bugTaslaklari.find((b) => b.id === "bug-1")!.durum).toBe("draft");
  });

  it("merge: hash/head_sha yoksa 422; head değiştiyse veya içerik değiştiyse 409", async () => {
    await girisYap("muhendis");
    const pr = (await api.script("scr-2")).pr!;
    expect(pr.head_sha).toMatch(/^[0-9a-f]{40}$/);
    await expect(api.prBirlestir({ number: 12 } as never)).rejects.toMatchObject({ status: 422 });
    await expect(api.prBirlestir({ number: 12, icerik_hash: pr.icerik_hash } as never)).rejects.toMatchObject({ status: 422 });
    await expect(api.prBirlestir({ ...pr, head_sha: "f".repeat(40) })).rejects.toMatchObject({ status: 409 });
    // İnceleme sonrası dala yeni commit: kod değişti → içerik hash'i ve head değişti.
    v().scriptler.find((s) => s.id === "scr-2")!.kod += "\n// sonradan eklendi\n";
    await expect(api.prBirlestir(pr)).rejects.toMatchObject({ status: 409 });
    expect(v().scriptler.find((s) => s.id === "scr-2")!.durum).toBe("pr_open");
    const guncel = (await api.script("scr-2")).pr!;
    expect(guncel.head_sha).not.toBe(pr.head_sha);
    await expect(api.prBirlestir(guncel)).resolves.toMatchObject({ birlesti: true });
  });

  it("locator onarım PR'ı da içerik + head ile birleştirilir", async () => {
    await girisYap("muhendis");
    await api.onarimPrAc("fail-2");
    await bekleIsler();
    const h = await api.hata("fail-2");
    const pr = h.oneri?.tur === "locator_fix" ? h.oneri.pr! : null;
    expect(pr?.icerik_hash).toMatch(/^sha256:/);
    await expect(api.prBirlestir({ number: pr!.number } as never)).rejects.toMatchObject({ status: 422 });
    await expect(api.prBirlestir(pr!)).resolves.toMatchObject({ birlesti: true });
  });
});

describe("mock arka uç: ön inceleme ve tutarlılık golden REPLAY çıktısını gösterir", () => {
  beforeEach(() => {
    ayar.isAdimiMs = 0;
  });

  it("TPD-4: golden 'ready', soru yok, bulgu yok → doc_final üzerinden PO bekler; REPLAY etiketli", async () => {
    await girisYap("analist");
    await api.incelemeBaslat("req-tpd-4");
    await bekleIsler();
    const g = await api.gereksinim("req-tpd-4");
    expect(g.on_inceleme).toMatchObject({ verdict: "ready", mode: "replay", questions: [] });
    expect(await api.bulgular("req-tpd-4")).toEqual([]);
    expect(g.durum).toBe("pending_po");
  });

  it("serbest metinde golden yok: ön inceleme REPLAY-MISS olarak işaretlenir (sahte replay yok)", async () => {
    await girisYap("analist");
    const g = await api.serbestMetin({ baslik: "Deneme", aciklama: "Açıklama", ac: ["Sepet tutarı 500,00 TL altındaysa uyarı gösterilir."] });
    await api.incelemeBaslat(g.id);
    await bekleIsler();
    const sonra = await api.gereksinim(g.id);
    expect(sonra.on_inceleme?.mode).toBe("replay_miss");
  });
});

describe("mock arka uç: Demo-A ölçüm, yeniden açma, token, olaylar", () => {
  beforeEach(() => {
    ayar.isAdimiMs = 0;
  });

  it("review süresi ilk görüntülemeden karara kadar ölçülür; görüntüleme idempotenttir", async () => {
    await girisYap("testci");
    // core yanıtı: {case_id, ilk_goruntuleme, yeni}
    const ilk = (await api.caseGoruntulendi("case-1-7")) as { case_id: string; ilk_goruntuleme: string; yeni: boolean };
    expect(ilk).toMatchObject({ case_id: "case-1-7", yeni: true });
    await new Promise((r) => setTimeout(r, 15));
    const ikinci = (await api.caseGoruntulendi("case-1-7")) as typeof ilk;
    expect(ikinci).toEqual({ ...ilk, yeni: false });
    const karar = await api.caseKarari("case-1-7", { ...caseH("case-1-7"), karar: "accept" });
    expect(karar.review_sure_ms).toBeGreaterThanOrEqual(10);
    // Görüntülenmeden verilen kararda süre uydurulmaz.
    const olcumsuz = await api.caseKarari("case-1-8", { ...caseH("case-1-8"), karar: "reject", ret_nedeni: "out_of_scope" });
    expect(olcumsuz.review_sure_ms).toBeNull();
  });

  it("taslağa al: onaylı/reddedilmiş case taslağa döner (hash zorunlu); yayınlanmış case açılamaz", async () => {
    await girisYap("testci");
    await expect(api.caseYenidenAc({ id: "case-1-6", icerik_hash: "" })).rejects.toMatchObject({ status: 422 });
    await expect(api.caseYenidenAc({ id: "case-1-6", icerik_hash: "sha256:eski" })).rejects.toMatchObject({ status: 409 });
    const acildi = await api.caseYenidenAc({ id: "case-1-6", ...caseH("case-1-6") });
    // core: durum draft, onay hash'i düşer; son karar kaydı (reject) değişmez (yeni karar gerekir).
    expect(acildi).toMatchObject({ durum: "draft", karar: "reject", onaylanan_hash: null });
    const yeniKarar = await api.caseKarari("case-1-6", { ...caseH("case-1-6"), karar: "accept" });
    expect(yeniKarar).toMatchObject({ durum: "ready", karar: "accept" });
    // Onaya hazır case de taslağa alınabilir (Testçi).
    expect((await api.caseYenidenAc({ id: "case-1-6", ...caseH("case-1-6") })).durum).toBe("draft");
    const onayli = await api.caseYenidenAc({ id: "case-1-4", ...caseH("case-1-4") });
    expect(onayli.durum).toBe("draft");
    // Yeniden açılan onaylı case yayın önizlemesinde artık engelli (onaylı değil).
    const p = await api.yayinOnizleme("req-tpd-1");
    expect(p.kalemler.find((k) => k.case_id === "case-1-4")?.islem).toBe("blocked_not_approved");
    await expect(api.caseYenidenAc({ id: "case-1-1", ...caseH("case-1-1") })).rejects.toMatchObject({ status: 409 });
    await expect(api.caseYenidenAc({ id: "case-1-7", ...caseH("case-1-7") })).rejects.toMatchObject({ status: 409 });
    await girisYap("muhendis");
    await expect(api.caseYenidenAc({ id: "case-1-6", ...caseH("case-1-6") })).rejects.toMatchObject({ status: 403 });
  });

  it("case ölçümleri core alanlarıyla döner; kabul oranı hedefle", async () => {
    await girisYap("analist");
    const m = await api.caseMetrikleri("req-tpd-1");
    // Ana yol (f2-kod-hatasi): C3 golden'ı story'yi esas alır, analist düzenlemeden onaylar.
    expect(m).toMatchObject({ uretilen: 10, karar_verilen: 6, bekleyen: 4, kabul: 4, kabul_hedefi: 0.7 });
    expect(m.kabul_orani).toBeCloseTo(4 / 10);
    expect(Object.keys(m.ai_cagri_modlari).every((k) => k === "replay" || k === "replay_miss")).toBe(true);
  });

  it("yayın sonucu Jira adresini taşır; önizleme browse kökünü verir", async () => {
    await kabulVeOnay("case-1-7");
    await girisYap("testci");
    const p = await api.yayinOnizleme("req-tpd-1");
    expect(p.jira_browse_url).toBe("http://127.0.0.1:8090");
    const s = await api.yayinla(["case-1-7"]);
    expect(s.sonuclar[0]).toMatchObject({ durum: "created", url: `http://127.0.0.1:8090/browse/${s.sonuclar[0].external_key}` });
  });

  it("token listesi ham token içermez; iptal edilen token listede iptal görünür", async () => {
    await girisYap("testci");
    const t = await api.tokenOlustur("publish");
    const liste = await api.tokenlar();
    expect(liste).toHaveLength(1);
    expect(JSON.stringify(liste)).not.toContain(t.token);
    await api.tokenIptal(liste[0].id);
    expect((await api.tokenlar())[0].iptal).toBe(true);
    await expect(api.tokenIptal("yok")).rejects.toMatchObject({ status: 404 });
  });

  it("PO onayı po.approved, inceleme finding.verified olayı yayımlar", async () => {
    const { mockOlaylaraAbone } = await import("./olaylar");
    const gelen: string[] = [];
    const iptal = mockOlaylaraAbone((o) => gelen.push(o.type));
    await girisYap("analist");
    const g = await api.serbestMetin({ baslik: "Sepet", aciklama: "a", ac: ["Kampanyada 7 adet alana 1 bedava"] });
    await api.incelemeBaslat(g.id);
    await bekleIsler();
    expect(gelen).toContain("finding.verified");
    // Bulgusuz serbest metin: doküman son hâl → PO bekler; PO Jira etiketiyle onaylar (simülatör).
    const temiz = await api.serbestMetin({ baslik: "Giriş", aciklama: "a", ac: ["Bayi giriş yapar"] });
    await api.incelemeBaslat(temiz.id);
    await bekleIsler();
    const onayli = mockPoEtiketi(temiz.id);
    expect(onayli.po).toMatchObject({ durum: "approved", kanal: "jira", onaylanan_hash: onayli.icerik_hash });
    expect(gelen).toContain("po.approved");
    iptal();
  });

  it("örnek veride hiçbir model çıktısı 'live' olarak işaretli değildir (golden kökenli → replay)", () => {
    const modlar: unknown[] = [];
    const tara = (x: unknown) => {
      if (Array.isArray(x)) x.forEach(tara);
      else if (x && typeof x === "object") {
        for (const [k, d] of Object.entries(x)) {
          if (k === "mode") modlar.push(d);
          else tara(d);
        }
      }
    };
    tara(v());
    expect(modlar.length).toBeGreaterThan(10);
    // null: model çağrısı yok (ör. code_defect bulgusunun şablon bug taslağı); "live" hiç yok.
    expect(modlar.every((m) => m === "replay" || m === "replay_miss" || m === null)).toBe(true);
    expect(modlar.filter((m) => m !== null).length).toBeGreaterThan(10);
  });
});
