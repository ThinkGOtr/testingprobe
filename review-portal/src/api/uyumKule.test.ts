// 012/Ş8: uyarlayıcılar — eksik anahtar uydurulmaz, geçersiz adım orana girmez.
import { describe, expect, it } from "vitest";
import { ekilmisHataEtiketi } from "../lib/etiketler";
import { kontrolKulesiUyarla, kosuUyarla } from "./uyumDemoB";
import { hataKataloguUyarla, hataKosusuDetayUyarla, hataKosusuKimligi, hataKosusuUyarla, kaynakBilgisiVar, kaynakOrani, kiranTestlerUyarla, yakalamaOrani } from "./uyumKule";

describe("kontrolKulesiUyarla: kalite anahtarları (§4.7)", () => {
  it("anahtarlar yoksa (eski core) alan da yok; sıfır uydurulmaz", () => {
    const k = kontrolKulesiUyarla({ gecme_orani: 0.8, ai_katkisi: {} });
    expect("beklenti_dogrulugu" in k).toBe(false);
    expect("hata_yakalama" in k).toBe(false);
    expect(k.beklenti_dogrulugu).toBeUndefined();
    expect(k.hata_yakalama).toBeUndefined();
  });

  it("null aynen null; payda 0 → oran null; kaynak anahtarları okunur", () => {
    const k = kontrolKulesiUyarla({
      beklenti_dogrulugu: { oran: null, uyumlu: 0, uyumsuz: 0, kapsam_disi: 4, kontrol_edilemedi: 1, istisna: 0, kapsam_orani: 0.2 },
      hata_yakalama: null,
      kaynaklar: { beklenti_dogrulugu: "case_oracle_kontrol", hata_yakalama: { kaynak: "hata_kosusu_adim" } },
    });
    expect(k.beklenti_dogrulugu).toEqual({ oran: null, uyumlu: 0, uyumsuz: 0, kapsam_disi: 4, kontrol_edilemedi: 1, istisna: 0, kapsam_orani: 0.2 });
    expect(k.hata_yakalama).toBeNull();
    expect(k.kaynaklar).toMatchObject({ beklenti_dogrulugu: "case_oracle_kontrol", hata_yakalama: "hata_kosusu_adim" });
  });

  it("hata_yakalama: son koşu, platformlar ve kaçanlar; son koşusuz nesne ölçüm sayılmaz; tanınmayan platform atılır", () => {
    const k = kontrolKulesiUyarla({
      hata_yakalama: {
        son_kosu: { id: "f1", bitis: "2026-11-10T10:00:00Z", durum: "done" },
        oran: 0.75,
        yakalanan: 3,
        kacan: 1,
        gecersiz: 2,
        platformlar: [{ platform: "web", oran: 0.75, yakalanan: 3, kacan: 1, gecersiz: 0 }, { platform: "tv", oran: 1 }],
        kacanlar: [{ hata_kodu: "fiyat_p004_31", ad: "P-004", platform: "web" }, { hata_kodu: "x" }],
      },
    });
    expect(k.hata_yakalama).toEqual({
      son_kosu: { id: "f1", bitis: "2026-11-10T10:00:00Z", durum: "done" },
      oran: 0.75,
      yakalanan: 3,
      kacan: 1,
      gecersiz: 2,
      platformlar: [{ platform: "web", oran: 0.75, yakalanan: 3, kacan: 1, gecersiz: 0 }],
      kacanlar: [{ hata_kodu: "fiyat_p004_31", ad: "P-004", platform: "web" }],
    });
    expect(kontrolKulesiUyarla({ hata_yakalama: { oran: 1 } }).hata_yakalama).toBeNull();
    // Oran sayı değilse null kalır (0 yazılmaz).
    expect(kontrolKulesiUyarla({ beklenti_dogrulugu: { uyumlu: 2 } }).beklenti_dogrulugu).toMatchObject({ oran: null, uyumlu: 2, kapsam_orani: null });
  });
});

describe("ekilmiş hata koşusu uyarlayıcıları", () => {
  it("katalog: dizi ya da {hatalar: []}; kodu olmayan öğe atılır; tanınmayan tür 'kod'", () => {
    expect(hataKataloguUyarla([{ kod: "a_1", ad: "A", tur: "veri", aciklama: "x", yakalayan_kural: "toplam" }, { ad: "kodsuz" }])).toEqual([
      { kod: "a_1", ad: "A", tur: "veri", aciklama: "x", yakalayan_kural: "toplam" },
    ]);
    // `yakalayan_kural` yoksa null (uydurulmaz).
    expect(hataKataloguUyarla({ hatalar: [{ kod: "b" }] })).toEqual([{ kod: "b", ad: "b", tur: "kod", aciklama: "", yakalayan_kural: null }]);
    expect(() => hataKataloguUyarla({})).toThrow();
  });

  it("koşu ve adımlar: tablo kolonları (§5) aynen; adımlar sıraya dizilir; bilinmeyen sonuç 'bekliyor', durum 'failed'", () => {
    const d = hataKosusuDetayUyarla({
      id: "f-1",
      durum: "running",
      platformlar: ["web", "ANDROID", "tv"],
      hatalar: ["a", "b"],
      commit: "abc1234",
      baslatan_id: "u-1",
      ozet: null,
      uyarilar: ["u"],
      baslama: "2026-11-10T10:00:00Z",
      bitis: null,
      olusturma: "2026-11-10T09:59:00Z",
      adimlar: [
        { id: "s2", kosu_id: "f-1", platform: "web", hata_kodu: "a", asama: "hata", run_id: "r-2", sonuc: "yakalandi", kiran_testler: ["T1"], neden: null, sure_ms: 100, sira: 2 },
        { id: "s1", kosu_id: "f-1", platform: "web", hata_kodu: null, asama: "temel", run_id: "r-1", sonuc: "yesil", kiran_testler: null, neden: null, sure_ms: 90, sira: 1 },
        { id: "s3", platform: "web", hata_kodu: "b", asama: "hata", sonuc: "tuhaf", sira: 3 },
        { id: "s4", platform: "tv", sira: 4 },
      ],
    });
    expect(d).toMatchObject({ id: "f-1", durum: "running", platformlar: ["web", "android"], baslatan_id: "u-1", baslatan: null, ozet: null });
    expect(d.adimlar.map((a) => a.id)).toEqual(["s1", "s2", "s3"]);
    expect(d.adimlar[0]).toMatchObject({ asama: "temel", sonuc: "yesil", kiran_testler: [], run_id: "r-1" });
    expect(d.adimlar[2]).toMatchObject({ sonuc: "bekliyor", run_id: null });
    expect(hataKosusuUyarla({ id: "x", durum: "garip" }).durum).toBe("failed");
  });

  it("başlatma yanıtından kimlik: koşu, {kosu: {id}} ya da {hata_kosusu_id}; yoksa null", () => {
    expect(hataKosusuKimligi({ id: "a" })).toBe("a");
    expect(hataKosusuKimligi({ kosu: { id: "b" } })).toBe("b");
    expect(hataKosusuKimligi({ job_id: "j", hata_kosusu_id: "c" })).toBe("c");
    expect(hataKosusuKimligi({ job_id: "j" })).toBeNull();
  });

  it("oran = yakalanan / (yakalanan + kaçan); geçersiz paydaya girmez; temel/kapanış sayılmaz; payda 0 → null", () => {
    const a = (asama: "temel" | "hata" | "kapanis", sonuc: "yakalandi" | "kacti" | "gecersiz" | "yesil" | "bekliyor") => ({ asama, sonuc });
    expect(yakalamaOrani([a("temel", "yesil"), a("hata", "yakalandi"), a("hata", "yakalandi"), a("hata", "kacti"), a("hata", "gecersiz"), a("kapanis", "yesil")])).toEqual({
      oran: 2 / 3,
      yakalanan: 2,
      kacan: 1,
      gecersiz: 1,
      bekleyen: 0,
    });
    expect(yakalamaOrani([a("temel", "gecersiz"), a("hata", "gecersiz"), a("hata", "bekliyor")])).toEqual({ oran: null, yakalanan: 0, kacan: 0, gecersiz: 1, bekleyen: 1 });
  });

  it("kosuUyarla: ortam.hata_kodu → 'Ekilmiş hata: <ad>'; başka koşuda alan eklenmez, etiket yok", () => {
    const k = kosuUyarla({ id: "r1", tetik: "break_verify", ortam: { hata_kodu: "kampanya_esik_7", hata_kosusu_id: "f-1", platform: "web" } });
    expect(k).toMatchObject({ hata_kodu: "kampanya_esik_7", hata_kosusu_id: "f-1" });
    expect(ekilmisHataEtiketi(k)).toBe("Ekilmiş hata: Kampanya eşiği 6 yerine 7");
    expect(ekilmisHataEtiketi({ hata_kodu: "bilinmeyen_kod" })).toBe("Ekilmiş hata: bilinmeyen_kod");
    const diger = kosuUyarla({ id: "r2", tetik: "break_verify", ortam: { BREAK_CAMPAIGN: "1" } });
    expect("hata_kodu" in diger).toBe(false);
    expect("hata_kosusu_id" in diger).toBe(false);
    expect(ekilmisHataEtiketi(diger)).toBeNull();
  });
});

describe("012 hizalama: gerçek core şekilleri", () => {
  it("kaynak metni değerin içinde gelirse (case-metrics biçimi) `kaynaklar`'da yoksa okunur; `kaynaklar` önceliklidir", () => {
    const k = kontrolKulesiUyarla({
      beklenti_dogrulugu: { oran: 1, uyumlu: 1, uyumsuz: 0, kapsam_disi: 0, kontrol_edilemedi: 0, istisna: 0, kapsam_orani: 1, kaynak: "değerdeki kaynak" },
      hata_yakalama: null,
      kaynaklar: { hata_yakalama: "hata_kosusu + hata_kosusu_adim: henüz yok (ölçülmedi)" },
    });
    expect(k.kaynaklar.beklenti_dogrulugu).toBe("değerdeki kaynak");
    expect(k.kaynaklar.hata_yakalama).toMatch(/henüz yok/);
    // Değer nesnesine `kaynak` sızmaz.
    expect(k.beklenti_dogrulugu).not.toHaveProperty("kaynak");
    const iki = kontrolKulesiUyarla({ beklenti_dogrulugu: { oran: null, kaynak: "iç" }, kaynaklar: { beklenti_dogrulugu: "dış" } });
    expect(iki.kaynaklar.beklenti_dogrulugu).toBe("dış");
  });

  it("koşu detayı: adımın `hata_adi`; özet `bekleyen`, platform `temel`/`kapanis`/`bekleyen` (core ozet_hesapla)", () => {
    const d = hataKosusuDetayUyarla({
      id: "k1",
      durum: "cancelled",
      platformlar: ["web"],
      hatalar: ["fiyat_p004_31"],
      ozet: {
        oran: null,
        yakalanan: 0,
        kacan: 0,
        gecersiz: 0,
        bekleyen: 1,
        platformlar: [{ platform: "web", oran: null, yakalanan: 0, kacan: 0, gecersiz: 0, bekleyen: 1, temel: "yesil", kapanis: "bekliyor" }],
        kacanlar: [],
      },
      adimlar: [
        { id: "a1", platform: "web", hata_kodu: null, hata_adi: null, asama: "temel", sonuc: "yesil", sira: 1 },
        { id: "a2", platform: "web", hata_kodu: "fiyat_p004_31", hata_adi: "P-004 fiyatı 31", asama: "hata", sonuc: "bekliyor", sira: 2 },
      ],
    });
    expect(d.adimlar.map((a) => a.hata_adi)).toEqual([null, "P-004 fiyatı 31"]);
    expect(d.ozet).toMatchObject({ bekleyen: 1, platformlar: [{ platform: "web", bekleyen: 1, temel: "yesil", kapanis: "bekliyor" }] });
    // Kule ölçüsünün platform satırı ek alan taşımaz (alan uydurulmaz).
    const k = kontrolKulesiUyarla({
      hata_yakalama: { son_kosu: { id: "k1", durum: "done" }, oran: 1, yakalanan: 1, kacan: 0, gecersiz: 0, platformlar: [{ platform: "web", oran: 1, yakalanan: 1, kacan: 0, gecersiz: 0 }], kacanlar: [] },
    });
    expect(k.hata_yakalama!.platformlar[0]).toEqual({ platform: "web", oran: 1, yakalanan: 1, kacan: 0, gecersiz: 0 });
  });

  it("POST /fault-runs 202 gövdesi `{id, durum}` → kimlik", () => {
    expect(hataKosusuKimligi({ id: "6f1c", durum: "queued" })).toBe("6f1c");
  });
});

describe("review turu 1 sözleşmesi (§13.2)", () => {
  it("katalog K9 alanları: ac_refs, tablo, ayirt_edici (nesne → 'ad = değer'); anahtar yoksa alan yok", () => {
    const [a, b] = hataKataloguUyarla([
      { kod: "kampanya_tek_bedava", ac_refs: ["AC2"], tablo: "T1", ayirt_edici: { girdi: { adet: 14 }, dogru: { bedava_adet: 2 }, hatali: { bedava_adet: 1 } } },
      { kod: "eski" },
    ]);
    expect(a).toMatchObject({ ac_refs: ["AC2"], tablo: "T1", ayirt_edici: { girdi: "adet = 14", dogru: "bedava_adet = 2", hatali: "bedava_adet = 1" } });
    expect(b).not.toHaveProperty("ac_refs");
    expect(b).not.toHaveProperty("tablo");
    expect(b).not.toHaveProperty("ayirt_edici");
    expect(hataKataloguUyarla([{ kod: "x", ayirt_edici: { girdi: "" } }])[0].ayirt_edici).toBeNull();
  });

  it("kiran_testler: [{test, kaynak}] ya da eski [ad] (kaynak null); temelde_kirmizi yalnız varsa", () => {
    expect(kiranTestlerUyarla([{ test: "A", kaynak: "ai" }, { test: "B", kaynak: "el" }, { test: "C", kaynak: "?" }, "D", 3, { kaynak: "ai" }])).toEqual([
      { test: "A", kaynak: "ai" },
      { test: "B", kaynak: "el" },
      { test: "C", kaynak: null },
      { test: "D", kaynak: null },
    ]);
    const d = hataKosusuDetayUyarla({
      id: "k",
      adimlar: [
        { id: "a", platform: "web", asama: "temel", sonuc: "yesil", temelde_kirmizi: ["C3"], sira: 1 },
        { id: "b", platform: "web", asama: "hata", hata_kodu: "x", sonuc: "yakalandi", kiran_testler: ["eski"], sira: 2 },
      ],
    });
    expect(d.adimlar[0].temelde_kirmizi).toEqual(["C3"]);
    expect(d.adimlar[1]).not.toHaveProperty("temelde_kirmizi");
    expect(kaynakBilgisiVar(d.adimlar)).toBe(false);
  });

  it("kaynakOrani: AI ve el ayrı; kaynağın testi hiç yoksa ölçülmedi (oran null)", () => {
    const a = (sonuc: "yakalandi" | "kacti" | "gecersiz", ...k: ("ai" | "el")[]) => ({ asama: "hata" as const, sonuc, kiran_testler: k.map((kaynak, i) => ({ test: `t${i}`, kaynak })) });
    const adimlar = [a("yakalandi", "el"), a("yakalandi", "el", "ai"), a("kacti"), a("gecersiz")];
    expect(kaynakOrani(adimlar, "el")).toEqual({ oran: 2 / 3, yakalanan: 2, kacan: 1, olculdu: true });
    expect(kaynakOrani(adimlar, "ai")).toEqual({ oran: 1 / 3, yakalanan: 1, kacan: 2, olculdu: true });
    expect(kaynakOrani([a("yakalandi", "el")], "ai")).toEqual({ oran: null, yakalanan: 0, kacan: 1, olculdu: false });
  });

  it("Kule: beklenti ekleri yalnız varsa; el_yazisi, kapsam; onayli_uyumsuz (dizi değilse alan yok)", () => {
    const k = kontrolKulesiUyarla({
      beklenti_dogrulugu: { oran: 0.8, uyumlu: 4, uyumsuz: 1, kismen: 2, kontrolsuz_onay: 1, n_case: 7, n_story: 1, tablolu_story: 1, toplam_story: 4, golden_kaynakli: 7, kapsam_disi: 0, kontrol_edilemedi: 0, istisna: 0, kapsam_orani: 1 },
      hata_yakalama: {
        son_kosu: { id: "f", durum: "done" },
        oran: null,
        yakalanan: 0,
        kacan: 0,
        gecersiz: 0,
        el_yazisi: { oran: 0.5, yakalanan: 1, kacan: 1 },
        kapsam: { kosulan_hata: 9, katalog: 9, platformlar: ["web", "tv"] },
        platformlar: [{ platform: "web", oran: null, yakalanan: 0, kacan: 0, gecersiz: 0, el_yazisi: { oran: 0.5, yakalanan: 1, kacan: 1 } }],
        kacanlar: [],
      },
      onayli_uyumsuz: [{ case_id: "c1", requirement_id: "r1", baslik: "B" }, { baslik: "kimliksiz" }],
    });
    expect(k.beklenti_dogrulugu).toMatchObject({ kismen: 2, kontrolsuz_onay: 1, n_case: 7, n_story: 1, tablolu_story: 1, toplam_story: 4, golden_kaynakli: 7 });
    expect(k.hata_yakalama).toMatchObject({ oran: null, el_yazisi: { oran: 0.5, yakalanan: 1, kacan: 1 }, kapsam: { kosulan_hata: 9, katalog: 9, platformlar: ["web"] } });
    expect(k.hata_yakalama!.platformlar[0].el_yazisi).toEqual({ oran: 0.5, yakalanan: 1, kacan: 1 });
    expect(k.onayli_uyumsuz).toEqual([{ case_id: "c1", requirement_id: "r1", baslik: "B" }]);
    const eski = kontrolKulesiUyarla({ beklenti_dogrulugu: { oran: 1, uyumlu: 1 }, hata_yakalama: { son_kosu: { id: "f" }, oran: 1 } });
    expect(eski.beklenti_dogrulugu).not.toHaveProperty("kismen");
    expect(eski.beklenti_dogrulugu).not.toHaveProperty("n_case");
    expect(eski.hata_yakalama).not.toHaveProperty("el_yazisi");
    expect(eski.hata_yakalama).not.toHaveProperty("kapsam");
    expect("onayli_uyumsuz" in eski).toBe(false);
  });

  it("R4 gerçek şekiller: iptal_istendi, tum_testler, kapsam tam_katalog/gecerli_adim, platform test sayıları; yoksa alan yok", () => {
    const k = hataKosusuUyarla({
      id: "hk-9",
      durum: "running",
      iptal_istendi: true,
      ozet: {
        oran: null,
        yakalanan: 0,
        kacan: 0,
        gecersiz: 0,
        tum_testler: { oran: 0.5, yakalanan: 1, kacan: 1 },
        kapsam: { kosulan_hata: 2, katalog: 9, platformlar: ["web"], tam_katalog: false, gecerli_adim: 2 },
        platformlar: [{ platform: "web", oran: null, yakalanan: 0, kacan: 0, gecersiz: 0, tum_testler: { oran: 0.5, yakalanan: 1, kacan: 1 }, uretilen_test: 0, el_test: 29 }],
        kacanlar: [],
      },
    });
    expect(k.iptal_istendi).toBe(true);
    expect(k.ozet?.tum_testler).toEqual({ oran: 0.5, yakalanan: 1, kacan: 1 });
    expect(k.ozet?.kapsam).toEqual({ kosulan_hata: 2, katalog: 9, platformlar: ["web"], tam_katalog: false, gecerli_adim: 2 });
    expect(k.ozet?.platformlar[0]).toMatchObject({ uretilen_test: 0, el_test: 29, tum_testler: { oran: 0.5, yakalanan: 1, kacan: 1 } });
    // Eski gövde: alanlar eklenmez (değer uydurulmaz).
    const eski = hataKosusuUyarla({ id: "hk-1", durum: "done", ozet: { oran: 1, yakalanan: 1, kacan: 0, gecersiz: 0, kapsam: { kosulan_hata: 1, katalog: 9, platformlar: ["web"] }, platformlar: [{ platform: "web", oran: 1, yakalanan: 1, kacan: 0, gecersiz: 0 }], kacanlar: [] } });
    expect("iptal_istendi" in eski).toBe(false);
    expect(eski.ozet && "tum_testler" in eski.ozet).toBe(false);
    expect(eski.ozet?.kapsam).toEqual({ kosulan_hata: 1, katalog: 9, platformlar: ["web"] });
    expect(eski.ozet && Object.keys(eski.ozet.platformlar[0])).not.toContain("uretilen_test");
  });
});
