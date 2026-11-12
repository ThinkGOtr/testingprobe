// 012 Ş7 — mock arka ucun sözleşme davranışı: ifade dili, durum makinesi, roller, hash çakışması,
// kontrol sonuçları, §4.3 kapı tablosu, istisna, önerilen içerik kontrolü, ilişkiden türetme.
import { describe, expect, it } from "vitest";
import { api } from "../client";
import { ApiError } from "../http";
import type { KararTablosu, TestCase, TestCaseIcerik } from "../types";
import { oturumAc } from "../../test/yardimci";
import { caseOracleYanitiUyarla } from "../uyumKalite";
import { TPD1_GOLDEN_CASELER } from "./fixtures";
import { bekleyenMockIs, mockIstek, mockVerisi } from "./handlers";
import { kaliteVerisi, kismiDegerlendir, tabloDegerlendir, tabloDogrula, turetilenBaslik } from "./kalite";
import { ayristir, hesapla, IfadeHatasi, sayiAyristir, sayiBicimle, turCikar } from "./kaliteIfade";
import { IKI_KAT_ILISKISI, KAMPANYA_TABLOSU, MIN_SIPARIS_DOGRU, MIN_SIPARIS_TABLOSU, T2_PO_SORUSU, YEDI_ARTIS_ILISKISI } from "./kaliteVerisi";
import { t2Duzelt, t2Onayla, t2Taslak } from "../../test/kaliteYardimci";

const REQ = "req-tpd-1";
const isBitsin = async () => {
  for (let i = 0; i < 200 && bekleyenMockIs() > 0; i++) await new Promise((r) => setTimeout(r, 5));
  expect(bekleyenMockIs()).toBe(0);
};
const hata = async (p: Promise<unknown>): Promise<ApiError> => {
  try {
    await p;
  } catch (e) {
    return e as ApiError;
  }
  throw new Error("hata bekleniyordu");
};
const tablolar = async () => (await api.kararTablolari(REQ)).tablolar;
const tablo = async (ad: RegExp): Promise<KararTablosu> => (await tablolar()).find((t) => ad.test(t.icerik.ad) && t.durum !== "superseded")!;
const caseBul = async (id: string): Promise<TestCase> => (await api.caseler(REQ)).find((c) => c.id === id)!;
/**
 * Demo adımı 2 (u2 N2): PO T2'deki AI sınır hatasını (`<= 750`) değişiklik isteğiyle geri gönderir, analist `< 750`
 * yapar, PO onaylar. C6 (case-1-7, AI'ın "750,00 TL'de uyarı görünür" hatası) yüksek riskli uyuşmazlık olur.
 */
async function minSiparisOnayla() {
  await t2Onayla();
  await isBitsin();
}

describe("sınırlı ifade dili (ANALIZ §4.2)", () => {
  const h = (ifade: string, ortam: Record<string, number | string | boolean> = {}) => hesapla(ayristir(ifade), ortam);
  it("işleçler, işlevler ve öncelik", () => {
    expect(h("1 + 2 * 3")).toBe(7);
    expect(h("(1 + 2) * 3")).toBe(9);
    expect(h("adet // 7", { adet: 15 })).toBe(2);
    expect(h("adet % 7 == 0 ve degil (adet > 20)", { adet: 14 })).toBe(true);
    expect(h("eger(adet >= 7, min(adet, 10), max(0, -1))", { adet: 3 })).toBe(0);
    expect(h("yuvarla(2.345, 2)")).toBe(2.35);
    expect(h("taban(2.7) + tavan(2.1)")).toBe(5);
    expect(h('"a" == "a" veya yanlis')).toBe(true);
    expect(h("0.1 + 0.2")).toBe(0.3);
  });
  it("hatalar: bilinmeyen ad, tür uyuşmazlığı, sıfıra bölme, sözdizimi, derinlik", () => {
    expect(() => h("adett > 1", { adet: 1 })).toThrow(/bilinmeyen ad 'adett'/);
    expect(() => turCikar(ayristir("adet + dogru"), { adet: "sayi" })).toThrow(/tür uyuşmazlığı/);
    expect(() => h("1 / 0")).toThrow(/sıfıra bölme/);
    expect(() => ayristir("adet >")).toThrow(IfadeHatasi);
    expect(() => ayristir(`${"(".repeat(40)}1${")".repeat(40)}`)).toThrow(/derin/);
    expect(() => ayristir("x".repeat(301))).toThrow(/300/);
  });
  it("sayı ayrıştırma ve biçimleme", () => {
    expect(sayiAyristir("1.250,00 TL")).toBe(1250);
    expect(sayiAyristir("−25,00 TL")).toBe(-25);
    expect(sayiAyristir("7")).toBe(7);
    expect(sayiAyristir("yedi")).toBeNull();
    expect(sayiBicimle(300, "150,00 TL")).toBe("300,00 TL");
    expect(sayiBicimle(14, "7")).toBe("14");
    expect(sayiBicimle(1250, "750,00 TL")).toBe("1.250,00 TL");
  });
  it("tablo doğrulama mesajları alan yoluyla başlar; değerlendirme ilk eşleşen satırı verir", () => {
    expect(tabloDogrula(KAMPANYA_TABLOSU)).toEqual([]);
    const bozuk = JSON.parse(JSON.stringify(KAMPANYA_TABLOSU)) as typeof KAMPANYA_TABLOSU;
    bozuk.satirlar[0].kosul = "adett >= 7";
    bozuk.satirlar[1].cikti.indirim = "";
    bozuk.girdiler[1].ad = "adet";
    const h2 = tabloDogrula(bozuk);
    expect(h2.some((m) => /^satirlar\[0\]\.kosul: bilinmeyen ad 'adett'/.test(m))).toBe(true);
    expect(h2).toContain("satirlar[1].cikti.indirim: çıktı ifadesi boş");
    expect(h2.some((m) => m.startsWith("girdiler[1].ad: 'adet' adı birden çok"))).toBe(true);
    // V9: indirim = yuvarla(ara_toplam / adet * (adet // 7), 2), toplam = ara_toplam - indirim.
    expect(tabloDegerlendir(KAMPANYA_TABLOSU, { adet: 7, ara_toplam: 175 })).toMatchObject({ satir_id: "R1", ciktilar: { bedava_adet: 1, indirim: 25, toplam: 150 } });
    expect(tabloDegerlendir(KAMPANYA_TABLOSU, { adet: 14, ara_toplam: 350 })).toMatchObject({ satir_id: "R1", ciktilar: { bedava_adet: 2, indirim: 50, toplam: 300 } });
    expect(tabloDegerlendir(KAMPANYA_TABLOSU, { adet: 7 })).toMatchObject({ satir_id: null, eksik_girdiler: ["ara_toplam"] });
    expect(tabloDegerlendir({ ...MIN_SIPARIS_TABLOSU, satirlar: MIN_SIPARIS_TABLOSU.satirlar.slice(0, 2) }, { sepet_tutari: 1000, kampanyali_sepet: false })).toMatchObject({ satir_id: null, eksik_girdiler: [], hata: null });
  });
  it("u2 N11: türetilen başlıkta önce ilişki adı kısaltılır, case başlığı korunur (≤ 120)", () => {
    expect(turetilenBaslik("Kısa", "İlişki")).toBe("Kısa (ilişki: İlişki)");
    const c2 = turetilenBaslik("14 adet kampanyalı üründe 2 adet bedava verilir", "Adet iki katına çıkınca bedava adet ve tutarlar iki katına çıkar");
    expect(c2.length).toBeLessThanOrEqual(120);
    expect(c2).toMatch(/^14 adet kampanyalı üründe 2 adet bedava verilir \(ilişki: Adet iki katına.*…\)$/);
    const uzun = turetilenBaslik("x".repeat(115), "y".repeat(100));
    expect(uzun.length).toBeLessThanOrEqual(120);
    expect(uzun).toMatch(/^x+… \(ilişki: y+…\)$/);
  });
  it("kısmi değerlendirme (core `kismi_degerlendir`): eksik girdi yalnız onu kullanan koşulu/çıktıyı etkiler", () => {
    // 7 adet, ara toplam yok: R1 seçilir; bedava adet hesaplanır, indirim ve toplam (ara toplama dayanır) hesaplanamaz.
    expect(kismiDegerlendir(KAMPANYA_TABLOSU, { adet: 7 })).toEqual({
      satir_id: "R1",
      ciktilar: { bedava_adet: 1 },
      hesaplanamayan: { indirim: ["ara_toplam"], toplam: ["ara_toplam"] },
      eksik_girdiler: [],
      hata: null,
    });
    // 6 adet: R2 sabit çıktılar hesaplanır; toplam ara toplama dayanır.
    expect(kismiDegerlendir(KAMPANYA_TABLOSU, { adet: 6 })).toEqual({ satir_id: "R2", ciktilar: { bedava_adet: 0, indirim: 0 }, hesaplanamayan: { toplam: ["ara_toplam"] }, eksik_girdiler: [], hata: null });
    // Koşulu eksik girdi kullanan ilk satırda durulur.
    expect(kismiDegerlendir(MIN_SIPARIS_DOGRU, { sepet_tutari: 750 })).toMatchObject({ satir_id: null, eksik_girdiler: ["kampanyali_sepet"] });
    expect(kismiDegerlendir(MIN_SIPARIS_DOGRU, { kampanyali_sepet: false, sepet_tutari: 750 })).toMatchObject({ satir_id: "R3", ciktilar: { minimum_uyarisi: false } });
  });
});

describe("karar tablosu uçları", () => {
  it("liste: TPD-1'de onaylı kampanya tablosu, PO onayı bekleyen AI taslağı minimum sipariş (AI sınır hatası `<= 750`), golden'daki tek ilişki", async () => {
    await oturumAc("testci");
    const y = await api.kararTablolari(REQ);
    expect(y.tablolar.map((t) => [t.sira_no, t.durum, t.ai_generated, t.bayat])).toEqual([
      [1, "approved", true, false],
      [2, "pending_po", true, false],
    ]);
    expect(y.tablolar[0]).toMatchObject({ onaylayan: "po", onaylanan_hash: y.tablolar[0].icerik_hash });
    // Analist/PO 20: golden'da olmayan elle ilişki örnek veriden çıkarıldı.
    expect(y.iliskiler.map((r) => [r.durum, r.karar_tablosu_id, r.tablo_engeli])).toEqual([["approved", y.tablolar[0].id, null]]);
    // u2 N2: T2 AI taslağı olduğu gibi (analist değiştirmedi): R2 `<= 750` AI'ın sınır hatası; açıklamada PO'ya soru.
    expect(y.tablolar[1].ai_icerik).toEqual(MIN_SIPARIS_TABLOSU);
    expect(y.tablolar[1].icerik).toEqual(MIN_SIPARIS_TABLOSU);
    expect(y.tablolar[1].icerik.satirlar.find((x) => x.id === "R2")!.kosul).toBe("sepet_tutari <= 750");
    expect(y.tablolar[1].icerik.aciklama).toContain(T2_PO_SORUSU);
    expect(y.tablolar[1].gecmis?.map((g) => g.karar)).toEqual(["submit"]);
    expect((await api.kararTablolari("req-tpd-3")).tablolar).toEqual([]);
  });

  it("kaydet: yalnız analist, yalnız taslak; hash eskiyse 409; geçersiz içerik 422 + mesaj listesi", async () => {
    await t2Taslak();
    await oturumAc("po");
    const t = await tablo(/Minimum/);
    expect((await hata(api.kararTablosuKaydet(t.id, { icerik: t.icerik, icerik_hash: t.icerik_hash }))).status).toBe(403);
    await oturumAc("analist");
    expect((await hata(api.kararTablosuKaydet(t.id, { icerik: t.icerik, icerik_hash: "sha256:eski" }))).status).toBe(409);
    const bozuk = { ...t.icerik, satirlar: [{ ...t.icerik.satirlar[0], kosul: "toplam >" }, ...t.icerik.satirlar.slice(1)] };
    const e = await hata(api.kararTablosuKaydet(t.id, { icerik: bozuk, icerik_hash: t.icerik_hash }));
    expect(e).toMatchObject({ status: 422, kod: "karar_tablosu_gecersiz" });
    expect(e.hatalar?.[0]).toMatch(/^satirlar\[0\]\.kosul: /);
    const yeni = await api.kararTablosuKaydet(t.id, { icerik: { ...t.icerik, aciklama: "Düzenlendi" }, icerik_hash: t.icerik_hash });
    expect(yeni.icerik.aciklama).toBe("Düzenlendi");
    expect(yeni.icerik_hash).not.toBe(t.icerik_hash);
    const onayli = await tablo(/Kampanya/);
    expect((await hata(api.kararTablosuKaydet(onayli.id, { icerik: onayli.icerik, icerik_hash: onayli.icerik_hash }))).status).toBe(409);
  });

  it("durum makinesi: gönder → geri çek → gönder → değişiklik iste → gönder → onayla → yeniden aç; roller ve hash", async () => {
    await t2Taslak();
    const t = await tablo(/Minimum/);
    const g = { icerik_hash: t.icerik_hash };
    expect((await hata(api.kararTablosuGecis(t.id, "approve", g))).status).toBe(403);
    expect(await hata(api.kararTablosuGecis(t.id, "withdraw"))).toMatchObject({ status: 409, kod: "eszamanli_gecis" });
    expect(await hata(api.kararTablosuGecis(t.id, "submit", { icerik_hash: "sha256:eski" }))).toMatchObject({ status: 409, kod: "onay_hash_uyusmuyor" });
    expect((await api.kararTablosuGecis(t.id, "submit", g)).durum).toBe("pending_po");
    expect((await api.kararTablosuGecis(t.id, "withdraw", g)).durum).toBe("draft");
    await api.kararTablosuGecis(t.id, "submit", g);
    await oturumAc("po");
    expect((await hata(api.kararTablosuGecis(t.id, "withdraw", g))).status).toBe(403);
    expect(await hata(api.kararTablosuGecis(t.id, "request-changes", g))).toMatchObject({ status: 422, kod: "gecersiz_karar" });
    const istek = await api.kararTablosuGecis(t.id, "request-changes", { ...g, gerekce: "Sınır dahil olmalı" });
    expect(istek).toMatchObject({ durum: "draft", son_karar: { karar: "request_changes", gerekce: "Sınır dahil olmalı", kullanici: "po" } });
    await oturumAc("analist");
    // Gönderimde hash isteğe bağlı; geri çekme ve yeniden açma gövdesiz.
    expect((await api.kararTablosuGecis(t.id, "submit")).durum).toBe("pending_po");
    await oturumAc("po");
    expect(await hata(api.kararTablosuGecis(t.id, "approve", { icerik_hash: "sha256:eski" }))).toMatchObject({ status: 409, kod: "onay_hash_uyusmuyor" });
    const onayli = await api.kararTablosuGecis(t.id, "approve", g);
    expect(onayli).toMatchObject({ tur: "karar_tablosu", durum: "approved", onaylanan_hash: t.icerik_hash, onaylayan: "po", bayat: false, son_karar: { karar: "approve" } });
    // Yanıt öğesi gerçek çekirdek şeklidir (iç alanlar sızmaz). `ai_icerik` portalın varsayımıdır (çekirdek
    // verirse "analist değiştirdi" işareti); sözleşmede yok.
    expect(Object.keys(onayli).sort()).toEqual(
      ["ai_generated", "ai_icerik", "bayat", "durum", "gecmis", "guncelleme", "icerik", "icerik_hash", "id", "olusturma", "onay_zamani", "onaylanan_hash", "onaylayan", "requirement_id", "sira_no", "son_karar", "tur", "uretim_modu"].sort(),
    );
    await isBitsin();
    expect((await hata(api.kararTablosuGecis(t.id, "reopen", g))).status).toBe(403);
    await oturumAc("analist");
    expect(await api.kararTablosuGecis(t.id, "reopen")).toMatchObject({ durum: "draft", onaylanan_hash: null, onaylayan: null });
    // Taslakta değil iken içerik değişmez: 409 `cakisma`.
    await api.kararTablosuGecis(t.id, "submit");
    expect(await hata(api.kararTablosuKaydet(t.id, { icerik: t.icerik, icerik_hash: t.icerik_hash }))).toMatchObject({ status: 409, kod: "cakisma" });
  });

  it("boş tablo eklenir ama eksik tablo PO'ya gönderilemez; gereksinim değişince onaylı tablo bayat olur", async () => {
    await oturumAc("analist");
    const yeni = await api.kararTablosuEkle(REQ);
    expect(yeni).toMatchObject({ durum: "draft", ai_generated: false, sira_no: 3 });
    const e = await hata(api.kararTablosuGecis(yeni.id, "submit", { icerik_hash: yeni.icerik_hash }));
    expect(e).toMatchObject({ status: 422, kod: "karar_tablosu_gecersiz" });
    expect(e.hatalar).toContain("satirlar: en az bir satır gerekir");
    mockVerisi().gereksinimler.find((g) => g.id === REQ)!.aciklama += " (değişti)";
    expect((await tablo(/Kampanya/)).bayat).toBe(true);
    // Bayat tablo kontrolde kullanılmaz; gereksinimde geçerli tablo kalmadı: çekirdek gibi `oracle: null`.
    expect((await caseBul("case-1-2")).oracle).toBeNull();
  });

  it("örnekle dene: eşleşen satır, eksik girdi, eşleşen satır yok, tür hatası", async () => {
    await oturumAc("testci");
    const t = await tablo(/Kampanya/);
    expect(await api.kararTablosuDene(t.id, { adet: 14, ara_toplam: 350 })).toEqual({
      satir_id: "R1",
      ciktilar: { bedava_adet: "2", indirim: "50", toplam: "300" },
      eksik_girdiler: [],
      hata: null,
    });
    expect(await api.kararTablosuDene(t.id, { adet: 3 })).toMatchObject({ satir_id: null, eksik_girdiler: ["ara_toplam"] });
    expect((await api.kararTablosuDene(t.id, { adet: 0, ara_toplam: 10, x: 1 } as never)).satir_id).toBe("R2");
    expect((await api.kararTablosuDene(t.id, { adet: "yedi", ara_toplam: 1 })).hata).toMatch(/adet/);
  });

  it("AI taslağı: gereksinim PO onaylı değilse 409; TPD-1'de eskileri geçersiz kılar, yeni taslaklar REPLAY; kayıt yoksa tablo uydurulmaz", async () => {
    await oturumAc("po");
    expect((await hata(api.kararTablosuTaslagiUret(REQ))).status).toBe(403);
    await oturumAc("analist");
    expect(await hata(api.kararTablosuTaslagiUret("req-tpd-2"))).toMatchObject({ status: 409, kod: "cakisma" });
    const is1 = await api.kararTablosuTaslagiUret(REQ);
    expect(is1).toMatchObject({ durum: "started", uretim_no: null });
    expect(is1.workflow_id).toBeTruthy();
    // İş sürerken aynı iş döner.
    expect((await api.kararTablosuTaslagiUret(REQ)).job_id).toBe(is1.job_id);
    expect((await api.kararTablolari(REQ)).son_taslak).toMatchObject({ job_id: is1.job_id, durum: "started" });
    await isBitsin();
    // Varsayılan liste yerini yenisi alanları içermez; `tumu` içerir.
    expect((await api.kararTablolari(REQ)).tablolar.map((t) => t.durum)).toEqual(["draft", "draft"]);
    const y = await api.kararTablolari(REQ, true);
    expect(y.son_taslak).toMatchObject({ job_id: is1.job_id, durum: "done", sonuc: { atilan: [] } });
    expect(y.tablolar.map((t) => t.durum)).toEqual(["superseded", "superseded", "draft", "draft"]);
    expect(y.tablolar[2]).toMatchObject({ ai_generated: true, uretim_modu: "replay", sira_no: 3 });
    // Golden'daki tek ilişki yeni T1'e (sıra 3) bağlanır; tablolar golden'la birebir (T2: AI'ın `<= 750` sınır hatası).
    expect(y.iliskiler.filter((r) => r.durum === "draft").map((r) => r.icerik.tablo_ref)).toEqual(["T3"]);
    expect(y.tablolar.slice(2).map((t) => t.icerik)).toEqual([KAMPANYA_TABLOSU, MIN_SIPARIS_TABLOSU]);
    expect(y.iliskiler.filter((r) => r.durum === "draft")[0].karar_tablosu_id).toBe(y.tablolar[2].id);
  });
});

describe("ilişkiler ve ek case türetme (§4.5)", () => {
  /** Elle taslak ilişki (golden'da yok): T1'e bağlı. */
  const elleIliski = async () => api.iliskiEkle(REQ, { icerik: YEDI_ARTIS_ILISKISI, karar_tablosu_id: (await tablo(/Kampanya/)).id });

  it("ilişki kaydı doğrulanır; geçişler tabloyla aynı makine", async () => {
    await oturumAc("analist");
    const r = await elleIliski();
    const e = await hata(api.iliskiKaydet(r.id, { icerik: { ...r.icerik, on_kosul: "adet +", donusum: { yok: "1" } }, icerik_hash: r.icerik_hash }));
    expect(e).toMatchObject({ status: 422, kod: "iliski_gecersiz" });
    expect(e.hatalar?.some((m) => m.startsWith("on_kosul: "))).toBe(true);
    expect(e.hatalar).toContain("donusum.yok: 'yok' bağlı tablonun girdisi değil");
    const k = await api.iliskiKaydet(r.id, { icerik: { ...r.icerik, aciklama: "Güncel" }, icerik_hash: r.icerik_hash });
    const g = { icerik_hash: k.icerik_hash };
    expect((await api.iliskiGecis(r.id, "submit", g)).durum).toBe("pending_po");
    expect((await hata(api.iliskiGecis(r.id, "approve", g))).status).toBe(403);
    await oturumAc("po");
    expect(await api.iliskiGecis(r.id, "approve", g)).toMatchObject({ durum: "approved", onaylayan: "po" });
  });

  it("türet: 7 adet → 14 adet (değerler aynı biçimde), 6 adet ön koşulu sağlamaz, olgusu olmayan atlanır; ikinci kez türetilmez", async () => {
    await oturumAc("analist");
    const y = await api.kararTablolari(REQ);
    const onayli = y.iliskiler.find((r) => r.durum === "approved")!;
    const taslak = await elleIliski();
    expect(await hata(api.ekCaseTuret(REQ, { iliski_id: taslak.id }))).toMatchObject({ status: 422, kod: "iliski_gecersiz" });
    const s = await api.ekCaseTuret(REQ, { iliski_id: onayli.id, case_ids: ["case-1-2", "case-1-3", "case-1-1"] });
    expect(s.turetilen.map((x) => x.kaynak_case_id)).toEqual(["case-1-2"]);
    expect(s.atlanan.map((x) => [x.kaynak_case_id, x.sonuc])).toEqual([
      ["case-1-3", "iliski_gecersiz"],
      ["case-1-1", "olgu_yok"],
    ]);
    expect(s.atlanan[0].neden).toMatch(/Ön koşul sağlanmıyor/);
    expect(s.turetilen[0].baslik).toMatch(/\(ilişki: /);
    await isBitsin();
    const yeni = await caseBul(s.turetilen[0].case_id);
    expect(yeni).toMatchObject({ durum: "draft", ai_generated: false, sira_no: 11 });
    // Başlık core `_baslik` gibi 120 karakterde kısaltılır.
    expect(yeni.icerik.title).toBe(turetilenBaslik("14 adet kampanyalı üründe 2 adet bedava verilir", IKI_KAT_ILISKISI.ad));
    expect(yeni.icerik.title.length).toBeLessThanOrEqual(120);
    // V9: ilişki adet ve ara toplamı dönüştürür, bedava adet / indirim / toplamı iki katına çıkarır — 14 adette tutarlar tutarlı.
    expect(yeni.icerik.steps[3].expected).toBe("P-001 satırında adet 14, bedava adet 2; ara toplam 350,00 TL, indirim 50,00 TL, toplam 300,00 TL");
    expect(yeni.icerik.steps[2].data).toBe("P-001 × 14");
    expect(yeni.icerik.tags).toContain("metamorfik");
    // Türetilen case normal kontrolden geçer: ilişki tabloyla çelişmiyor.
    expect(yeni.oracle?.sonuc).toBe("uyumlu");
    const tekrar = await api.ekCaseTuret(REQ, { iliski_id: onayli.id, case_ids: ["case-1-2"] });
    expect(tekrar).toEqual({ turetilen: [], atlanan: [expect.objectContaining({ kaynak_case_id: "case-1-2", sonuc: "zaten_turetildi", case_id: yeni.id })] });
    expect((await api.caseler(REQ)).length).toBe(11);
    // Varsayılan kaynaklar: ilişkinin kabul kriterine atıf yapan onaylı/yayınlanmış case'ler.
    const v = await api.ekCaseTuret(REQ, { iliski_id: onayli.id });
    expect([...v.turetilen, ...v.atlanan].map((x) => x.kaynak_case_id).sort()).toEqual(["case-1-2", "case-1-3"]);
  });

  it("aynı alıntı bir alanda iki olguya aitse türetilmez (belirsiz alıntı)", async () => {
    await oturumAc("analist");
    const c = mockVerisi().caseler.find((x) => x.id === "case-1-2")!;
    c.icerik = { ...c.icerik, title: "7 adet alımda 7 adet bedava" };
    const onayli = (await api.kararTablolari(REQ)).iliskiler.find((r) => r.durum === "approved")!;
    const s = await api.ekCaseTuret(REQ, { iliski_id: onayli.id, case_ids: ["case-1-2"] });
    expect(s.atlanan[0].sonuc).toBe("olgu_yok"); // bedava adet için çelişen değerler (1 ve 7)
    const d = mockVerisi().caseler.find((x) => x.id === "case-1-10")!;
    d.durum = "approved";
    d.icerik = { ...d.icerik, steps: d.icerik.steps.map((x, i) => (i === 3 ? { ...x, expected: "adet 7, bedava adet 1; ara toplam 7,00 TL, indirim 1,00 TL, toplam 6,00 TL" } : x)), title: "Kampanya", expected_result: "Tamam" };
    const s2 = await api.ekCaseTuret(REQ, { iliski_id: onayli.id, case_ids: ["case-1-10"] });
    expect(s2.turetilen).toHaveLength(1);
    const e = mockVerisi().caseler.find((x) => x.id === "case-1-6")!;
    e.durum = "approved";
    e.icerik = {
      ...e.icerik,
      title: "x",
      expected_result: "y",
      steps: e.icerik.steps.map((x, i) =>
        i === 2 ? { ...x, data: "P-001 × 7", action: "a", expected: "b" } : i === 3 ? { ...x, expected: "adet 7, bedava adet 7, ara toplam 175,00 TL, indirim 25,00 TL, toplam 150,00 TL" } : x,
      ),
    };
    const s3 = await api.ekCaseTuret(REQ, { iliski_id: onayli.id, case_ids: ["case-1-6"] });
    expect(s3.atlanan[0]).toMatchObject({ sonuc: "belirsiz_alinti" });
  });
});

describe("beklenen sonuç kontrolü ve onay kapısı (§4.3)", () => {
  it("TPD-1 başlangıç sonuçları golden case metinlerinden hesaplanır", async () => {
    await oturumAc("analist");
    const cs = await api.caseler(REQ);
    const sonuc = Object.fromEntries(cs.map((c) => [c.id, c.oracle?.sonuc]));
    expect(sonuc).toEqual({
      "case-1-1": "kapsam_disi",
      "case-1-2": "uyumlu",
      "case-1-3": "uyumlu",
      "case-1-6": "uyumlu",
      "case-1-4": "kapsam_disi",
      "case-1-7": "kapsam_disi",
      "case-1-5": "kapsam_disi",
      "case-1-8": "kapsam_disi",
      // AC6: yalnız T2 kapsar; T2 başlangıçta PO onayı bekliyor (kontrolde kullanılmaz).
      "case-1-9": "kapsam_disi",
      "case-1-10": "uyumlu",
    });
    const c2 = cs.find((c) => c.id === "case-1-2")!;
    // V9: 7 adet + ara toplam 175,00 TL → bedava adet, indirim ve toplam karşılaştırılır (birim fiyat gerekmez).
    expect([...new Set(c2.oracle!.karsilastirmalar.map((k) => k.column))].sort()).toEqual(["bedava_adet", "indirim", "toplam"]);
    expect(c2.oracle!.karsilastirmalar.find((k) => k.column === "bedava_adet" && k.alan === "steps[3].expected")).toMatchObject({
      alinti: "1",
      case_degeri: "1",
      tablo_degeri: "1",
      uyumlu: true,
      satir_id: "R1",
    });
    expect(c2.oracle!.karsilastirmalar.find((k) => k.column === "indirim" && k.alan === "steps[3].expected")).toMatchObject({ case_degeri: "25", tablo_degeri: "25", uyumlu: true });
    expect(c2.oracle!.karsilastirilamayan).toEqual([]);
    expect(c2.oracle!.degerler).toEqual({ uyumlu: c2.oracle!.karsilastirmalar.length, uyumsuz: 0, karsilastirilamayan: 0, atilan: 0 });
    expect(c2.oracle!.ozet).toBe(`${c2.oracle!.karsilastirmalar.length} beklenen değer onaylı karar tablosuyla uyumlu.`);
    // Demo triage hikâyesi: C3 "6 adet … bedava ürün verilmez" `adet // 7` tablosuyla uyumlu (R2; indirim de karşılaştırılır).
    const c3 = cs.find((c) => c.id === "case-1-3")!.oracle!;
    expect(c3.karsilastirmalar.every((k) => k.uyumlu && k.satir_id === "R2")).toBe(true);
    expect(new Set(c3.karsilastirmalar.map((k) => k.column))).toEqual(new Set(["bedava_adet", "indirim", "toplam"]));
    expect(cs.find((c) => c.id === "case-1-1")!.oracle!.ozet).toBe("Bu case'i kapsayan onaylı karar tablosu yok.");
    // Kontrol case içeriğini değiştirmez.
    expect(mockVerisi().caseler.find((c) => c.id === "case-1-2")!.icerik.expected_result).toBe(c2.icerik.expected_result);
    const m = await api.caseMetrikleri(REQ);
    // §13.2 + u2 N1: örnek veriden hesaplanır. C10, C2'nin tekrarı (aynı satır, aynı değerler) → tek sayılır ve
    // paydadan düşer; n = oranın paydası (uyumlu + uyumsuz). kapsam_orani = (uyumlu + uyumsuz + kısmen) / (AI case − tekrar).
    expect(m.beklenti_dogrulugu).toEqual({
      oran: 1,
      uyumlu: 3,
      uyumsuz: 0,
      kismen: 0,
      kapsam_disi: 6,
      kontrol_edilemedi: 0,
      istisna: 0,
      kontrolsuz_onay: 0,
      kapsam_orani: 3 / 9,
      n_case: 3,
      n_story: 1,
      tablolu_story: 1,
      toplam_story: 1,
      golden_kaynakli: 3,
      tekrar: 1,
    });
    expect((await api.caseMetrikleri("req-tpd-3")).beklenti_dogrulugu).toMatchObject({ oran: null });
  });

  it("tablo onaylanınca case'ler yeniden kontrol edilir; iş sürerken yüksek riskli onay 409 oracle_bekleniyor", async () => {
    await t2Onayla({ bekle: false });
    const c7 = mockVerisi().caseler.find((c) => c.id === "case-1-7")!;
    expect((await caseBul("case-1-7")).oracle).toMatchObject({ sonuc: null, kontrol_suruyor: true });
    expect(await hata(api.caseKarari("case-1-7", { icerik_hash: c7.icerik_hash, karar: "approve" }))).toMatchObject({ status: 409, kod: "oracle_bekleniyor" });
    await isBitsin();
    expect((await caseBul("case-1-7")).oracle).toMatchObject({ sonuc: "uyumsuz", istisna: null });
    expect((await caseBul("case-1-4")).oracle?.sonuc).toBe("uyumlu");
    expect((await caseBul("case-1-9")).oracle?.sonuc).toBe("uyumlu");
    // u2 N2: AI'ın sınır hatası C6 — "tam 750,00 TL'de uyarı görünür"; düzeltilmiş T2 (R3) uyarı yok der.
    expect((await caseBul("case-1-7")).oracle?.ozet).toBe(
      "2 beklenen değer tabloyla uyuşmuyor; ör. minimum_uyarisi: case “\"Minimum sipariş tutarı 750,00 TL\" uyarısı görünür”, tablo yanlış.",
    );
    expect((await caseBul("case-1-7")).oracle?.karsilastirmalar.every((k) => !k.uyumlu && k.satir_id === "R3")).toBe(true);
    // u2 N1: "5/6" — C10 tekrar; uyuşmazlık AI'ın C6'sı.
    expect((await api.caseMetrikleri(REQ)).beklenti_dogrulugu).toMatchObject({ uyumlu: 5, uyumsuz: 1, oran: 5 / 6, n_case: 6, tekrar: 1 });
  });

  it("yüksek risk + uyuşmazlık: 422 oracle_uyumsuz; kısa gerekçe reddedilir; geçerli istisnayla onay ve denetim kaydı", async () => {
    await minSiparisOnayla();
    const c = await caseBul("case-1-7");
    const g = { icerik_hash: c.icerik_hash, karar: "approve" as const };
    expect(await hata(api.caseKarari(c.id, g))).toMatchObject({ status: 422, kod: "oracle_uyumsuz" });
    expect(await hata(api.caseKarari(c.id, { ...g, oracle_istisna_gerekce: "kısa", oracle_istisna_turu: "uyumsuz" }))).toMatchObject({ status: 422, kod: "oracle_uyumsuz" });
    expect(mockVerisi().caseler.find((x) => x.id === c.id)!.durum).toBe("draft");
    // Y9: gerekçe verilince tür zorunlu; türü sonuca uymazsa 422.
    expect(await hata(api.caseKarari(c.id, { ...g, oracle_istisna_gerekce: "PO ile görüşüldü: sınır dahil kabul edildi." }))).toMatchObject({ status: 422, kod: "gecersiz_karar" });
    expect(await hata(api.caseKarari(c.id, { ...g, oracle_istisna_gerekce: "PO ile görüşüldü: sınır dahil kabul edildi.", oracle_istisna_turu: "kontrolsuz" }))).toMatchObject({
      status: 422,
      kod: "gecersiz_karar",
    });
    const onayli = await api.caseKarari(c.id, { ...g, oracle_istisna_gerekce: "PO ile görüşüldü: sınır dahil kabul edildi.", oracle_istisna_turu: "uyumsuz" });
    expect(onayli).toMatchObject({ durum: "approved", oracle: { sonuc: "uyumsuz", istisna: { veren: "analist", gerekce: "PO ile görüşüldü: sınır dahil kabul edildi." } } });
    expect(mockVerisi().denetim.at(-1)).toMatchObject({ eylem: "oracle.exception", nesne: c.id });
    expect((await api.caseMetrikleri(REQ)).beklenti_dogrulugu?.istisna).toBe(1);
    expect(onayli.oracle?.istisna).toMatchObject({ tur: "uyumsuz", gecerli: true });
    // S1 (tur 2, çekirdekle tek kural): aynı içerik + tür + tablo kümesiyle geçerli saklı istisna kapıyı açar;
    // yeniden kullanım denetime yazılır, yeni istisna satırı açılmaz.
    const acik = await api.caseYenidenAc(onayli);
    expect(acik.oracle?.istisna).toMatchObject({ gecerli: true, tur: "uyumsuz" });
    expect((await api.caseKarari(c.id, { icerik_hash: acik.icerik_hash, karar: "approve" })).durum).toBe("approved");
    expect(mockVerisi().denetim.at(-1)).toMatchObject({ eylem: "oracle.exception_reused", nesne: c.id });
    expect(kaliteVerisi(mockVerisi()).istisnalar?.filter((i) => i.test_case_id === c.id)).toHaveLength(1);
    // Tablo kümesi değişince (T2 yeniden açılıp başka içerikle onaylanınca) istisna geçersizleşir; gerekçe yeniden istenir.
    const acik2 = await api.caseYenidenAc(await caseBul(c.id));
    const t2 = await tablo(/Minimum/);
    await api.kararTablosuGecis(t2.id, "reopen");
    await t2Duzelt({ ...MIN_SIPARIS_DOGRU, aciklama: "Düzeltilmiş: tam 750,00 TL'de uyarı yok." });
    await oturumAc("po");
    const t2c = await tablo(/Minimum/);
    await api.kararTablosuGecis(t2c.id, "approve", { icerik_hash: t2c.icerik_hash });
    await isBitsin();
    await oturumAc("analist");
    expect((await caseBul(c.id)).oracle?.istisna).toMatchObject({ gecerli: false });
    expect(await hata(api.caseKarari(c.id, { icerik_hash: acik2.icerik_hash, karar: "approve" }))).toMatchObject({ status: 422, kod: "oracle_uyumsuz" });
    // §13.2 gerekçe: ≥ 20 karakter ve ≥ 10 harf (dolgu reddedilir).
    expect(
      await hata(api.caseKarari(c.id, { icerik_hash: acik2.icerik_hash, karar: "approve", oracle_istisna_gerekce: "1234567890 1234567890 !!", oracle_istisna_turu: "uyumsuz" })),
    ).toMatchObject({ status: 422 });
    expect(
      (await api.caseKarari(c.id, { icerik_hash: acik2.icerik_hash, karar: "approve", oracle_istisna_gerekce: "İkinci onay: PO kararı değişmedi.", oracle_istisna_turu: "uyumsuz" })).durum,
    ).toBe("approved");
    // İstisnalar append-only; sayaç case başına.
    expect(kaliteVerisi(mockVerisi()).istisnalar?.filter((i) => i.test_case_id === c.id)).toHaveLength(2);
    expect((await api.caseMetrikleri(REQ)).beklenti_dogrulugu?.istisna).toBe(1);
  });

  it("orta/düşük risk + uyuşmazlık: onaylanır, uyarı kaydı düşer; kontrol edilemeyen yüksek riskli case gerekçe ister (K10)", async () => {
    await minSiparisOnayla();
    const c7 = mockVerisi().caseler.find((c) => c.id === "case-1-7")!;
    c7.icerik = { ...c7.icerik, risk: "medium" };
    c7.icerik_hash = (await api.caseOracleKontrol(c7.id, c7.icerik)).icerik_hash!;
    await isBitsin();
    const c = await caseBul("case-1-7");
    expect(c.oracle?.sonuc).toBe("uyumsuz");
    expect((await api.caseKarari(c.id, { icerik_hash: c.icerik_hash, karar: "approve" })).durum).toBe("approved");
    expect(mockVerisi().denetim.at(-1)).toMatchObject({ eylem: "oracle.warning" });
    const c9 = mockVerisi().caseler.find((x) => x.id === "case-1-9")!;
    // Kampanya bilgisi metinden çıkarılınca T2'nin ilk koşulu karar veremez → kontrol edilemedi.
    c9.icerik = { ...c9.icerik, risk: "high", preconditions: ["Sepet boş"], expected_result: "Toplam 150,00 TL olsa da minimum sipariş uyarısı gösterilmez" };
    c9.icerik_hash = (await api.caseOracleKontrol(c9.id, c9.icerik)).icerik_hash!;
    await isBitsin();
    const y = await caseBul("case-1-9");
    expect(y.oracle?.sonuc).toBe("kontrol_edilemedi");
    expect(await hata(api.caseKarari(y.id, { icerik_hash: y.icerik_hash, karar: "approve" }))).toMatchObject({ status: 422, kod: "oracle_kontrolsuz" });
    const o = await api.caseKarari(y.id, { icerik_hash: y.icerik_hash, karar: "approve", oracle_istisna_gerekce: "Uyarının görünmediği elle doğrulandı.", oracle_istisna_turu: "kontrolsuz" });
    expect(o).toMatchObject({ durum: "approved", oracle: { istisna: { tur: "kontrolsuz" } } });
    expect(mockVerisi().denetim.at(-1)).toMatchObject({ eylem: "oracle.exception" });
    expect((await api.caseMetrikleri(REQ)).beklenti_dogrulugu).toMatchObject({ kontrolsuz_onay: 1, istisna: 0 });
  });

  it("uyumlu, kapsam dışı ve tablosuz yüksek riskli case'ler engelsiz onaylanır; ret kapıya takılmaz", async () => {
    await minSiparisOnayla();
    const c7 = await caseBul("case-1-7");
    expect((await api.caseKarari(c7.id, { icerik_hash: c7.icerik_hash, karar: "reject", ret_nedeni: "duplicate" })).durum).toBe("rejected");
    const c5 = await caseBul("case-1-5");
    expect(c5.oracle?.sonuc).toBe("kapsam_disi");
    expect((await api.caseKarari(c5.id, { icerik_hash: c5.icerik_hash, karar: "approve" })).durum).toBe("approved");
    const c4 = await api.caseYenidenAc(await caseBul("case-1-4"));
    expect(c4.icerik.risk).toBe("high");
    expect((await api.caseKarari(c4.id, { icerik_hash: c4.icerik_hash, karar: "approve" })).oracle?.sonuc).toBe("uyumlu");
  });

  it("düzeltme: önerilen içerik kontrol edilmeden yüksek riskli onay 409; kontrol sonrası tabloya getirilen değer onaylanır", async () => {
    await minSiparisOnayla();
    const c = await caseBul("case-1-7");
    // Demo adımı 3'ün düzeltmesi: AI'ın sınır hatası ana yol C6 metnine çevrilir ("uyarı görünmez").
    const duzeltilmis: TestCaseIcerik = JSON.parse(JSON.stringify(TPD1_GOLDEN_CASELER[5])) as TestCaseIcerik;
    const g = { icerik_hash: c.icerik_hash, karar: "edit" as const, icerik: duzeltilmis };
    expect(await hata(api.caseKarari(c.id, g))).toMatchObject({ status: 409, kod: "oracle_bekleniyor" });
    await oturumAc("po");
    expect((await hata(api.caseOracleKontrol(c.id, duzeltilmis))).status).toBe(403);
    await oturumAc("analist");
    const is = await api.caseOracleKontrol(c.id, duzeltilmis);
    expect(is.icerik_hash).toMatch(/^sha256:/);
    expect(await api.caseOracle(c.id, is.icerik_hash!)).toMatchObject({ sonuc: null, kontrol_suruyor: true, icerik_hash: is.icerik_hash });
    await isBitsin();
    expect(await api.caseOracle(c.id, is.icerik_hash!)).toMatchObject({ sonuc: "uyumlu", icerik_hash: is.icerik_hash, kontrol_suruyor: false });
    expect((await api.caseOracle(c.id))?.sonuc).toBe("uyumsuz");
    const onayli = await api.caseKarari(c.id, g);
    expect(onayli).toMatchObject({ durum: "approved", karar: "edit", icerik_hash: is.icerik_hash, oracle: { sonuc: "uyumlu" } });
    // Metrik AI'ın özgün içeriğinin sonucunu saymaya devam eder (insan düzeltmesinden önceki hash).
    expect((await api.caseMetrikleri(REQ)).beklenti_dogrulugu).toMatchObject({ uyumsuz: 1 });
    expect(kaliteVerisi(mockVerisi()).kontroller.filter((r) => r.test_case_id === c.id).length).toBe(2);
  });
});

describe("çekirdek sözleşmesiyle hizalı uçlar", () => {
  it("GET /cases/{id}/oracle gövdesi core `case_oracle` sarmalı; istemci `oracle`'ı içinden okur", async () => {
    await oturumAc("analist");
    const c = await caseBul("case-1-2");
    const ham = (await mockIstek("GET", `/cases/${c.id}/oracle`, new URLSearchParams(), undefined)) as Record<string, unknown>;
    expect(Object.keys(ham).sort()).toEqual(["case_id", "guncel_icerik", "icerik_hash", "kapsayan_tablolar", "oracle"]);
    expect(ham).toMatchObject({ case_id: c.id, icerik_hash: c.icerik_hash, guncel_icerik: true, kapsayan_tablolar: [{ ref: "T1", ad: KAMPANYA_TABLOSU.ad }] });
    expect((ham.oracle as { sonuc: string }).sonuc).toBe("uyumlu");
    expect(await api.caseOracle(c.id)).toMatchObject({ sonuc: "uyumlu", kontrol_suruyor: false, icerik_hash: c.icerik_hash });
    // Kapsayan tablo yok: `oracle` null değil, kapsam dışı kaydı (gereksinimde geçerli tablo var).
    expect(await api.caseOracle("case-1-1")).toMatchObject({ sonuc: "kapsam_disi" });
    // Gereksinimde hiç geçerli tablo yoksa çekirdek kontrol işi açmaz: `oracle: null`.
    // (gereksinim değişti → T1 bayat → TPD-1'de geçerli tablo kalmadı).
    mockVerisi().gereksinimler.find((g) => g.id === REQ)!.aciklama += " (değişti)";
    const y = (await mockIstek("GET", `/cases/${c.id}/oracle`, new URLSearchParams(), undefined)) as Record<string, unknown>;
    expect(y).toMatchObject({ oracle: null, kapsayan_tablolar: [] });
    expect(await api.caseOracle(c.id)).toBeNull();
  });

  it("caseOracleYanitiUyarla: sarmal, null `oracle`, `kontrol_suruyor` ve yalın gövde", () => {
    const istisna = { gerekce: "PO ile görüşüldü: sınır dahil.", veren: "analist", zaman: "2026-11-12T10:00:00+03:00" };
    expect(caseOracleYanitiUyarla({ case_id: "c", icerik_hash: "h", guncel_icerik: true, kapsayan_tablolar: [], oracle: null })).toBeNull();
    expect(
      caseOracleYanitiUyarla({ case_id: "c", icerik_hash: "h2", guncel_icerik: false, kapsayan_tablolar: [], oracle: { sonuc: null, icerik_hash: "h2", ozet: "Tablo kontrolü sürüyor.", karsilastirmalar: [], istisna: null, kontrol_suruyor: true } }),
    ).toEqual({ sonuc: null, ozet: "Tablo kontrolü sürüyor.", karsilastirmalar: [], karsilastirilamayan: [], istisna: null, icerik_hash: "h2", kontrol_suruyor: true });
    const kk = { tablo_id: "t1", tablo_ad: "Kampanya", column: "indirim", alan: "expected_result", alinti: "25,00 TL", case_degeri: "25.00", neden: "case'te bulunamayan girdi: ara_toplam" };
    expect(caseOracleYanitiUyarla({ case_id: "c", oracle: { sonuc: "uyumlu", ozet: "z", karsilastirmalar: [], karsilastirilamayan: [kk, "bozuk"], kontrol_suruyor: false } })?.karsilastirilamayan).toEqual([kk]);
    expect(caseOracleYanitiUyarla({ case_id: "c", oracle: { sonuc: "uyumsuz", ozet: "x", karsilastirmalar: [], istisna, kontrol_suruyor: false } })).toMatchObject({ sonuc: "uyumsuz", istisna });
    expect(caseOracleYanitiUyarla({ sonuc: "uyumlu", ozet: "y", karsilastirmalar: [] })).toMatchObject({ sonuc: "uyumlu" });
  });

  it("evaluate: `icerik` verilirse kaydedilmemiş içerik değerlendirilir; geçersizse 422", async () => {
    await oturumAc("po");
    const t = await tablo(/Kampanya/);
    const icerik = { ...t.icerik, satirlar: [{ id: "R1", kosul: "adet >= 1", cikti: { bedava_adet: "99", indirim: "0", toplam: "ara_toplam" } }] };
    expect(await api.kararTablosuDene(t.id, { adet: "3", ara_toplam: "75" }, icerik)).toMatchObject({ satir_id: "R1", ciktilar: { bedava_adet: "99" } });
    expect(await hata(api.kararTablosuDene(t.id, { adet: "3" }, { ...icerik, satirlar: [{ id: "R1", kosul: "adet >", cikti: {} }] }))).toMatchObject({
      status: 422,
      kod: "karar_tablosu_gecersiz",
    });
  });

  it("elle ilişki: oluşturulur (201 öğe), bağ `karar_tablosu_id` ile; PUT'ta alan yoksa bağ korunur, null kaldırır", async () => {
    await oturumAc("analist");
    const t = await tablo(/Kampanya/);
    const icerik = { ad: "7'nin altında bedava adet değişmez", ac_refs: ["AC2"], on_kosul: "adet < 6", donusum: { adet: "adet + 1" }, iliski: { bedava_adet: "bedava_adet" } };
    const r = await api.iliskiEkle(REQ, { icerik, karar_tablosu_id: t.id });
    expect(r).toMatchObject({ tur: "metamorfik_iliski", durum: "draft", ai_generated: false, karar_tablosu_id: t.id, icerik: { tablo_ref: "T1" } });
    const k = await api.iliskiKaydet(r.id, { icerik: { ...r.icerik, aciklama: "x" }, icerik_hash: r.icerik_hash });
    expect(k.karar_tablosu_id).toBe(t.id);
    const bagsiz = await api.iliskiKaydet(r.id, { icerik: k.icerik, icerik_hash: k.icerik_hash, karar_tablosu_id: null });
    expect(bagsiz).toMatchObject({ karar_tablosu_id: null, icerik: { tablo_ref: null } });
    expect((await hata(api.iliskiEkle(REQ, { icerik: { ...icerik, on_kosul: "adet >" } }))).kod).toBe("iliski_gecersiz");
  });

  it("türetme kayıtları listelenir; gereksinim case review aşamasında değilse 409", async () => {
    await oturumAc("analist");
    const onayli = (await api.kararTablolari(REQ)).iliskiler.find((r) => r.durum === "approved")!;
    await api.ekCaseTuret(REQ, { iliski_id: onayli.id, case_ids: ["case-1-2", "case-1-3"] });
    const kayitlar = await api.metamorfikTuretmeler(REQ);
    expect(kayitlar.map((x) => [x.kaynak_case_id, x.sonuc, !!x.turetilen_case_id])).toEqual([
      ["case-1-2", "turetildi", true],
      ["case-1-3", "iliski_gecersiz", false],
    ]);
    expect(kayitlar[0]).toMatchObject({ iliski_id: onayli.id, olusturan_id: "analist" });
    mockVerisi().gereksinimler.find((g) => g.id === REQ)!.durum = "po_approved";
    expect(await hata(api.ekCaseTuret(REQ, { iliski_id: onayli.id }))).toMatchObject({ status: 409 });
  });
});

describe("review turu 1: kısmen, sınır örnekleri, tutarsız türetme, ilişki tablo engeli", () => {
  it("K11 kısmen: fark yok ama bir beklenen değer karşılaştırılamadı → `kismen`; uyarıyla onaylanır, orana girmez", async () => {
    await oturumAc("analist");
    const c = mockVerisi().caseler.find((x) => x.id === "case-1-10")!;
    c.durum = "draft";
    // Ara toplam metinden çıkınca indirim ve toplam hesaplanamaz; bedava adet karşılaştırılır.
    c.icerik = JSON.parse(JSON.stringify(c.icerik).replaceAll(/ara toplam [0-9.,]+ TL, /g, "")) as TestCaseIcerik;
    c.icerik_hash = (await api.caseOracleKontrol(c.id, c.icerik)).icerik_hash!;
    await isBitsin();
    const y = await caseBul("case-1-10");
    expect(y.oracle).toMatchObject({ sonuc: "kismen", degerler: { uyumsuz: 0 } });
    expect(y.oracle!.degerler!.karsilastirilamayan).toBeGreaterThan(0);
    expect(y.oracle!.ozet).toMatch(/^Kısmen uyumlu: /);
    expect((await api.caseKarari(y.id, { icerik_hash: y.icerik_hash, karar: "approve" })).durum).toBe("approved");
    expect(mockVerisi().denetim.at(-1)).toMatchObject({ eylem: "oracle.warning" });
  });

  it("sınır örnekleri: adet 6/7/8/12/13/14 ve 749,99/750/750,01 tabloyla değerlendirilir", async () => {
    await oturumAc("po");
    const t1 = await tablo(/Kampanya/);
    const o1 = await api.kararTablosuOrnekleri(t1.id);
    expect(o1.ornekler.map((o) => [o.girdiler.adet, o.satir_id, o.ciktilar.bedava_adet])).toEqual([
      [6, "R2", "0"],
      [7, "R1", "1"],
      [8, "R1", "1"],
      [12, "R1", "1"],
      [13, "R1", "1"],
      [14, "R1", "2"],
    ]);
    expect(o1.uyarilar).toEqual([]);
    const t2 = await tablo(/Minimum/);
    const o2 = await api.kararTablosuOrnekleri(t2.id);
    // Taslaktaki `<= 750`: tam 750,00 TL'de uyarı görünür (golden `< 750` görünmez) — PO örnekten görür.
    expect(o2.ornekler.find((o) => o.girdiler.sepet_tutari === 750 && o.girdiler.kampanyali_sepet === false)).toMatchObject({ satir_id: "R2", ciktilar: { minimum_uyarisi: true } });
  });

  it("R2 tutarsiz_kalan_deger: ilişki ara toplamı dönüştürmezse türetilmez", async () => {
    await oturumAc("analist");
    const r = await api.iliskiEkle(REQ, {
      icerik: { ...IKI_KAT_ILISKISI, ad: "Yalnız adet", donusum: { adet: "adet * 2" }, iliski: { bedava_adet: "bedava_adet * 2" } },
      karar_tablosu_id: (await tablo(/Kampanya/)).id,
    });
    await api.iliskiGecis(r.id, "submit", { icerik_hash: r.icerik_hash });
    await oturumAc("po");
    await api.iliskiGecis(r.id, "approve", { icerik_hash: r.icerik_hash });
    await oturumAc("analist");
    const s = await api.ekCaseTuret(REQ, { iliski_id: r.id, case_ids: ["case-1-2"] });
    expect(s.turetilen).toEqual([]);
    expect(s.atlanan[0]).toMatchObject({ sonuc: "tutarsiz_kalan_deger" });
    expect(s.atlanan[0].neden).toMatch(/ara_toplam/);
  });

  it("ilişki: bağlı tablo yoksa gönderilemez (tablo_engeli + 422 iliski_gecersiz); bulunamayan ilişki 404 iliski_bulunamadi", async () => {
    await oturumAc("analist");
    const r = await api.iliskiEkle(REQ, { icerik: { ...YEDI_ARTIS_ILISKISI, tablo_ref: null } });
    expect(r.tablo_engeli).toMatch(/Bağlı karar tablosu yok/);
    expect(await hata(api.iliskiGecis(r.id, "submit", { icerik_hash: r.icerik_hash }))).toMatchObject({ status: 422, kod: "iliski_gecersiz" });
    expect(await hata(api.iliskiGecis("yok", "submit", {}))).toMatchObject({ status: 404, kod: "iliski_bulunamadi" });
  });
});
