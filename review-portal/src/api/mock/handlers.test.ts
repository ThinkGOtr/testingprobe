import { beforeEach, describe, expect, it } from "vitest";
import { api } from "../client";
import { ApiError } from "../http";
import { sha256Hex, kanonikJson } from "../../lib/sha256";
import { ayar, mockVerisi } from "./handlers";

const bekleIsler = () => new Promise((r) => setTimeout(r, 30));

// Kararlar ekranda görülen içeriğin hash'ini taşır (§5): testler de GET'ten okunan değeri gönderir.
const v = () => mockVerisi();
const bulguH = (id: string) => ({ icerik_hash: v().bulgular.find((b) => b.id === id)!.icerik_hash });
const caseH = (id: string) => ({ icerik_hash: v().caseler.find((c) => c.id === id)!.icerik_hash });
const bugH = (id: string) => ({ icerik_hash: v().bugTaslaklari.find((b) => b.id === id)!.icerik_hash });
const gereksinim = (id: string) => v().gereksinimler.find((g) => g.id === id)!;
const scriptPr = (id: string) => v().scriptler.find((s) => s.id === id)!.pr!;

async function girisYap(k: string) {
  await api.logout().catch(() => undefined);
  return api.login(k, "Demo123!");
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
    await expect(api.poOnayla(gereksinim("req-ft-1"))).rejects.toMatchObject({ status: 403 });
    await expect(api.bugKarari("bug-1", { ...bugH("bug-1"), karar: "new" })).rejects.toMatchObject({ status: 403 });
    await expect(api.ciTetikle("deploy")).rejects.toMatchObject({ status: 403 });
    await expect(api.tokenOlustur("submit")).rejects.toMatchObject({ status: 403 });
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
    await girisYap("analist");
    await expect(api.caseUret("req-ft-1")).rejects.toMatchObject({ status: 409 });
    await expect(api.duzeltmeleriUygula("req-ft-1")).rejects.toMatchObject({ status: 409 });

    const bulgular = await api.bulgular("req-ft-1");
    const h5 = bulgular.find((b) => b.id === "fnd-5")!.icerik_hash;
    const h6 = bulgular.find((b) => b.id === "fnd-6")!.icerik_hash;
    await api.bulguKarari("fnd-5", { icerik_hash: h5, karar: "fix_doc", metin: "Kaldırma sonrası indirim her 6 adette 1 bedava kuralıyla hesaplanır." });
    await api.bulguKarari("fnd-6", { icerik_hash: h6, karar: "accept_difference", gerekce: "Ayar değeri ürün kararıyla 750" });
    await api.duzeltmeleriUygula("req-ft-1");
    await bekleIsler();

    let g = await api.gereksinim("req-ft-1");
    expect(g.durum).toBe("pending_po");
    expect(g.kabul_kriterleri[1].metin).toBe("Kaldırma sonrası indirim her 6 adette 1 bedava kuralıyla hesaplanır.");
    expect(g.kontrol_turu).toBe(2);
    // fix_doc yazıldı → resolved (core: decided → resolved); "applied" diye ayrı durum yok.
    expect((await api.bulgular("req-ft-1")).map((b) => [b.id, b.durum])).toEqual([
      ["fnd-5", "resolved"],
      ["fnd-6", "resolved"],
    ]);

    // PO teyidi yalnızca PO rolüyle; Jira yolunda portaldan verilemez.
    await expect(api.poOnayla(g)).rejects.toMatchObject({ status: 403 });
    await girisYap("po");
    await expect(api.poOnayla(await api.gereksinim("req-tpd-3"))).rejects.toMatchObject({ status: 409 });
    g = await api.poOnayla(g);
    expect(g.po).toMatchObject({ durum: "approved", onaylayan: "po", kanal: "portal" });

    await girisYap("analist");
    await api.caseUret("req-ft-1");
    await bekleIsler();
    const caseler = await api.caseler("req-ft-1");
    expect(caseler.length).toBe(3);
    expect(caseler.every((c) => c.durum === "draft" && c.mode === "replay")).toBe(true);
    expect((await api.gereksinim("req-ft-1")).durum).toBe("cases_ready");
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
  it("ret nedeni zorunlu; düzeltme hash'i günceller; yalnızca onaylılar yayınlanır", async () => {
    await girisYap("analist");
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
    expect(duzeltilmis.durum).toBe("approved");
    expect(duzeltilmis.icerik_hash).not.toBe(once.icerik_hash);
    expect(duzeltilmis.onaylanan_hash).toBe(duzeltilmis.icerik_hash);
    expect(duzeltilmis.duzeltme_olcusu).toBeGreaterThan(0);

    p = await api.yayinOnizleme("req-tpd-1");
    expect(p.kalemler.find((k) => k.case_id === "case-1-5")?.islem).toBe("create");
    const s = await api.yayinla(["case-1-5", "case-1-1", "case-1-6"]);
    expect(s.sonuclar.map((x) => x.durum)).toEqual(["created", "exists", "failed"]);
    await expect(api.caseKarari("case-1-5", { ...caseH("case-1-5"), karar: "approve" })).rejects.toMatchObject({ status: 409 });
  });
});

describe("mock arka uç: kod, kırma, merge, onarım, bug", () => {
  beforeEach(() => {
    ayar.isAdimiMs = 0;
  });

  it("replay ıskalanan case için PR açılmaz (REPLAY-MISS, sahte başarı yok)", async () => {
    await girisYap("muhendis");
    await expect(api.kodUret(["case-1-5"])).rejects.toMatchObject({ status: 409 });
    await api.kodUret(["case-1-4"]);
    for (let i = 0; i < 14; i++) await bekleIsler();
    const s = (await api.scriptler()).find((x) => x.case_ids.includes("case-1-4"))!;
    const detay = await api.script(s.id);
    expect(detay.adimlar.map((a) => a.sira)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
    expect(detay).toMatchObject({ mode: "replay_miss", durum: "failed", pr: null, zayif_test: false });
    expect(detay.hata).toContain("REPLAY-MISS");
  });

  it("merge kırarak doğrulamadan önce reddedilir; sonra kabul edilir", async () => {
    await girisYap("muhendis");
    const s = mockVerisi().scriptler.find((x) => x.id === "scr-2")!;
    s.break_verify = { durum: "not_started", asamalar: [] };
    s.durum = "pr_open";
    await expect(api.prBirlestir(scriptPr("scr-2"))).rejects.toMatchObject({ status: 409 });
    await api.kirarakDogrula("scr-2");
    for (let i = 0; i < 10; i++) await bekleIsler();
    const sonra = await api.script("scr-2");
    expect(sonra.break_verify.asamalar.map((a) => a.sonuc)).toEqual(["passed", "failed", "passed"]);
    // core durumu pr_open kalır; "merge'e hazır" türetilir (scriptIsareti).
    expect(sonra).toMatchObject({ durum: "pr_open", zayif_test: false });
    expect((await api.prBirlestir(sonra.pr!)).durum).toBe("merged");
    expect((await api.script("scr-2")).durum).toBe("merged");
    await expect(api.prBirlestir(sonra.pr!)).rejects.toMatchObject({ status: 409 });
  });

  it("zayıf test işaretli PR merge edilemez", async () => {
    await girisYap("muhendis");
    const s = await api.script("scr-1");
    expect(s).toMatchObject({ durum: "pr_open", zayif_test: true });
    await expect(api.prBirlestir(s.pr!)).rejects.toMatchObject({ status: 409 });
  });

  it("locator onarım PR'ı yalnızca bir kez açılır", async () => {
    await girisYap("muhendis");
    await api.onarimPrAc("fail-2");
    await expect(api.onarimPrAc("fail-2")).rejects.toMatchObject({ status: 409 });
    await expect(api.onarimPrAc("fail-1")).rejects.toMatchObject({ status: 409 });
    const h = await api.hata("fail-2");
    expect(h.oneri).toMatchObject({ tur: "locator_fix", durum: "pr_open", eski_test_id: "add-to-cart", yeni_test_id: "cart-add" });
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
    const b = await api.bugKarari("bug-1", { ...bugH("bug-1"), karar: "dismiss" });
    expect(b).toMatchObject({ durum: "dismissed", karar: "dismiss", jira_key: null, link_key: null });
    await expect(api.bugKarari("bug-1", { ...bugH("bug-1"), karar: "new" })).rejects.toMatchObject({ status: 409 });
  });
});

describe("mock arka uç: denetim zinciri", () => {
  it("zincir sha256(prev_hash + kanonik JSON) ile hesaplanır ve doğrulanır", async () => {
    await girisYap("analist");
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

  it("case kararı: hash yoksa 422, düzeltme sonrası eski hash'le onay 409", async () => {
    await girisYap("analist");
    await expect(api.caseKarari("case-1-7", { karar: "approve" } as never)).rejects.toMatchObject({ status: 422 });
    const gorulen = caseH("case-1-7");
    const c = v().caseler.find((x) => x.id === "case-1-7")!;
    // Aynı case başka kanaldan (IDE) düzeltildi: içerik ve hash değişti.
    c.icerik = { ...c.icerik, title: `${c.icerik.title} (IDE)` };
    c.icerik_hash = `sha256:${"0".repeat(16)}`;
    await expect(api.caseKarari("case-1-7", { ...gorulen, karar: "approve" })).rejects.toMatchObject({ status: 409 });
    expect(v().caseler.find((x) => x.id === "case-1-7")!.durum).toBe("draft");
  });

  it("PO onayı: hash yoksa 422, açıklama değiştiyse 409", async () => {
    await girisYap("po");
    const g = gereksinim("req-ft-1");
    g.durum = "pending_po";
    const gorulen = { id: g.id, icerik_hash: g.icerik_hash };
    await expect(api.poOnayla({ id: g.id } as never)).rejects.toMatchObject({ status: 422 });
    g.aciklama = `${g.aciklama} (PO görmeden değişti)`;
    await expect(api.poOnayla(gorulen)).rejects.toMatchObject({ status: 409 });
    expect(gereksinim("req-ft-1").durum).toBe("pending_po");
    const guncel = await api.gereksinim("req-ft-1");
    await expect(api.poOnayla(guncel)).resolves.toMatchObject({ durum: "po_approved" });
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
    await expect(api.prBirlestir(guncel)).resolves.toMatchObject({ durum: "merged" });
  });

  it("locator onarım PR'ı da içerik + head ile birleştirilir", async () => {
    await girisYap("muhendis");
    await api.onarimPrAc("fail-2");
    await bekleIsler();
    const h = await api.hata("fail-2");
    const pr = h.oneri?.tur === "locator_fix" ? h.oneri.pr! : null;
    expect(pr?.icerik_hash).toMatch(/^sha256:/);
    await expect(api.prBirlestir({ number: pr!.number } as never)).rejects.toMatchObject({ status: 422 });
    await expect(api.prBirlestir(pr!)).resolves.toMatchObject({ durum: "merged" });
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
