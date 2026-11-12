// 012 Ş7 — mock arka ucun sözleşme davranışı: ifade dili, durum makinesi, roller, hash çakışması,
// kontrol sonuçları, §4.3 kapı tablosu, istisna, önerilen içerik kontrolü, ilişkiden türetme.
import { describe, expect, it } from "vitest";
import { api } from "../client";
import { ApiError } from "../http";
import type { KararTablosu, TestCase, TestCaseIcerik } from "../types";
import { oturumAc } from "../../test/yardimci";
import { bekleyenMockIs, mockVerisi } from "./handlers";
import { kaliteVerisi, tabloDegerlendir, tabloDogrula } from "./kalite";
import { ayristir, hesapla, IfadeHatasi, sayiAyristir, sayiBicimle, turCikar } from "./kaliteIfade";
import { KAMPANYA_TABLOSU, MIN_SIPARIS_TABLOSU } from "./kaliteVerisi";

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
/** Minimum sipariş taslağını (sınır hatasıyla) PO'ya onaylatır: C6 (case-1-7) yüksek riskli uyuşmazlık olur. */
async function minSiparisOnayla() {
  await oturumAc("analist");
  const t = await tablo(/Minimum/);
  await api.kararTablosuGecis(t.id, "submit", { icerik_hash: t.icerik_hash });
  await oturumAc("po");
  await api.kararTablosuGecis(t.id, "approve", { icerik_hash: t.icerik_hash });
  await isBitsin();
  await oturumAc("analist");
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
    expect(tabloDegerlendir(KAMPANYA_TABLOSU, { adet: 7, ara_toplam: 175 })).toMatchObject({ satir_id: "R1", ciktilar: { bedava_adet: 1, indirim: 25, toplam: 150 } });
    expect(tabloDegerlendir(KAMPANYA_TABLOSU, { adet: 7 })).toMatchObject({ satir_id: null, eksik_girdiler: ["ara_toplam"] });
    expect(tabloDegerlendir({ ...MIN_SIPARIS_TABLOSU, satirlar: MIN_SIPARIS_TABLOSU.satirlar.slice(0, 2) }, { toplam: 100, kampanyali: false })).toMatchObject({ satir_id: null, eksik_girdiler: [], hata: null });
  });
});

describe("karar tablosu uçları", () => {
  it("liste: TPD-1'de onaylı kampanya tablosu, AI taslağı minimum sipariş, bir onaylı ve bir taslak ilişki", async () => {
    await oturumAc("testci");
    const y = await api.kararTablolari(REQ);
    expect(y.tablolar.map((t) => [t.sira_no, t.durum, t.ai_generated, t.bayat])).toEqual([
      [1, "approved", true, false],
      [2, "draft", true, false],
    ]);
    expect(y.tablolar[0]).toMatchObject({ onaylayan: "po", onaylanan_hash: y.tablolar[0].icerik_hash });
    expect(y.iliskiler.map((r) => [r.durum, r.karar_tablosu_id])).toEqual([
      ["approved", y.tablolar[0].id],
      ["draft", y.tablolar[0].id],
    ]);
    expect((await api.kararTablolari("req-tpd-3")).tablolar).toEqual([]);
  });

  it("kaydet: yalnız analist, yalnız taslak; hash eskiyse 409; geçersiz içerik 422 + mesaj listesi", async () => {
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
    await oturumAc("analist");
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
    // Yanıt öğesi gerçek çekirdek şeklidir (iç alanlar sızmaz).
    expect(Object.keys(onayli).sort()).toEqual(
      ["ai_generated", "bayat", "durum", "guncelleme", "icerik", "icerik_hash", "id", "olusturma", "onay_zamani", "onaylanan_hash", "onaylayan", "requirement_id", "sira_no", "son_karar", "tur", "uretim_modu"].sort(),
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
    // Bayat tablo kontrolde kullanılmaz: kampanya case'i artık kapsam dışı.
    expect((await caseBul("case-1-2")).oracle?.sonuc).toBe("kapsam_disi");
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
    expect(y.iliskiler.filter((r) => r.durum === "draft").map((r) => r.icerik.tablo_ref)).toEqual(["T3", "T3"]);
    expect(y.iliskiler.filter((r) => r.durum === "draft")[0].karar_tablosu_id).toBe(y.tablolar[2].id);
  });
});

describe("ilişkiler ve ek case türetme (§4.5)", () => {
  it("ilişki kaydı doğrulanır; geçişler tabloyla aynı makine", async () => {
    await oturumAc("analist");
    const r = (await api.kararTablolari(REQ)).iliskiler.find((x) => x.durum === "draft")!;
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
    const taslak = y.iliskiler.find((r) => r.durum === "draft")!;
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
    expect(yeni.icerik.title).toBe("14 adet kampanyalı üründe 2 adet bedava verilir (ilişki: Adet iki katına çıkınca bedava adet iki katına çıkar)");
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
    e.icerik = { ...e.icerik, title: "x", expected_result: "y", steps: e.icerik.steps.map((x, i) => (i === 2 ? { ...x, data: "P-001 × 7", action: "a", expected: "b" } : i === 3 ? { ...x, expected: "ara toplam 7,00 TL, indirim 7,00 TL, toplam 0,00 TL, bedava adet 1" } : x)) };
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
      "case-1-9": "kontrol_edilemedi",
      "case-1-10": "uyumlu",
    });
    const c2 = cs.find((c) => c.id === "case-1-2")!;
    expect(c2.oracle!.karsilastirmalar.find((k) => k.column === "indirim")).toMatchObject({
      alan: "steps[3].expected",
      alinti: "25,00 TL",
      case_degeri: "25",
      tablo_degeri: "25",
      uyumlu: true,
      satir_id: "R1",
    });
    expect(cs.find((c) => c.id === "case-1-9")!.oracle!.ozet).toMatch(/ara_toplam/);
    // Kontrol case içeriğini değiştirmez.
    expect(mockVerisi().caseler.find((c) => c.id === "case-1-2")!.icerik.expected_result).toBe(c2.icerik.expected_result);
    const m = await api.caseMetrikleri(REQ);
    expect(m.beklenti_dogrulugu).toEqual({ oran: 1, uyumlu: 4, uyumsuz: 0, kapsam_disi: 5, kontrol_edilemedi: 1, istisna: 0, kapsam_orani: 0.5 });
    expect((await api.caseMetrikleri("req-tpd-3")).beklenti_dogrulugu).toMatchObject({ oran: null });
  });

  it("tablo onaylanınca case'ler yeniden kontrol edilir; iş sürerken yüksek riskli onay 409 oracle_bekleniyor", async () => {
    await oturumAc("analist");
    const t = await tablo(/Minimum/);
    await api.kararTablosuGecis(t.id, "submit", { icerik_hash: t.icerik_hash });
    await oturumAc("po");
    await api.kararTablosuGecis(t.id, "approve", { icerik_hash: t.icerik_hash });
    await oturumAc("analist");
    const c7 = mockVerisi().caseler.find((c) => c.id === "case-1-7")!;
    expect((await caseBul("case-1-7")).oracle).toMatchObject({ sonuc: null, kontrol_suruyor: true });
    expect(await hata(api.caseKarari("case-1-7", { icerik_hash: c7.icerik_hash, karar: "approve" }))).toMatchObject({ status: 409, kod: "oracle_bekleniyor" });
    await isBitsin();
    expect((await caseBul("case-1-7")).oracle).toMatchObject({ sonuc: "uyumsuz", istisna: null });
    expect((await caseBul("case-1-4")).oracle?.sonuc).toBe("uyumlu");
    expect((await api.caseMetrikleri(REQ)).beklenti_dogrulugu).toMatchObject({ uyumlu: 5, uyumsuz: 1, oran: 5 / 6 });
  });

  it("yüksek risk + uyuşmazlık: 422 oracle_uyumsuz; kısa gerekçe reddedilir; geçerli istisnayla onay ve denetim kaydı", async () => {
    await minSiparisOnayla();
    const c = await caseBul("case-1-7");
    const g = { icerik_hash: c.icerik_hash, karar: "approve" as const };
    expect(await hata(api.caseKarari(c.id, g))).toMatchObject({ status: 422, kod: "oracle_uyumsuz" });
    expect(await hata(api.caseKarari(c.id, { ...g, oracle_istisna_gerekce: "kısa" }))).toMatchObject({ status: 422, kod: "oracle_uyumsuz" });
    expect(mockVerisi().caseler.find((x) => x.id === c.id)!.durum).toBe("draft");
    const onayli = await api.caseKarari(c.id, { ...g, oracle_istisna_gerekce: "PO ile görüşüldü: sınır dahil kabul edildi." });
    expect(onayli).toMatchObject({ durum: "approved", oracle: { sonuc: "uyumsuz", istisna: { veren: "analist", gerekce: "PO ile görüşüldü: sınır dahil kabul edildi." } } });
    expect(mockVerisi().denetim.at(-1)).toMatchObject({ eylem: "oracle.exception", nesne: c.id });
    expect((await api.caseMetrikleri(REQ)).beklenti_dogrulugu?.istisna).toBe(1);
    // Geçerli istisna kayıtlıyken yeniden açılan case gerekçe istemeden onaylanır.
    const acik = await api.caseYenidenAc(onayli);
    expect((await api.caseKarari(c.id, { icerik_hash: acik.icerik_hash, karar: "approve" })).durum).toBe("approved");
  });

  it("orta/düşük risk + uyuşmazlık: onaylanır, uyarı kaydı düşer; kontrol edilemeyen yüksek riskli case uyarıyla onaylanır (V2)", async () => {
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
    c9.icerik = { ...c9.icerik, risk: "high" };
    c9.icerik_hash = (await api.caseOracleKontrol(c9.id, c9.icerik)).icerik_hash!;
    await isBitsin();
    const y = await caseBul("case-1-9");
    expect(y.oracle?.sonuc).toBe("kontrol_edilemedi");
    expect((await api.caseKarari(y.id, { icerik_hash: y.icerik_hash, karar: "approve" })).durum).toBe("approved");
    expect(mockVerisi().denetim.at(-1)).toMatchObject({ eylem: "oracle.warning" });
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
    const duzeltilmis: TestCaseIcerik = JSON.parse(JSON.stringify(c.icerik).replaceAll("750,00 TL", "760,00 TL")) as TestCaseIcerik;
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
    const icerik = { ad: "Ara toplam ile toplam", ac_refs: ["AC2"], on_kosul: "adet < 7", donusum: { adet: "adet + 1" }, iliski: { toplam: "toplam" } };
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
