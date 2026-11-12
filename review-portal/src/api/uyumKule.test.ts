// 012/Ş8: uyarlayıcılar — eksik anahtar uydurulmaz, geçersiz adım orana girmez.
import { describe, expect, it } from "vitest";
import { ekilmisHataEtiketi } from "../lib/etiketler";
import { kontrolKulesiUyarla, kosuUyarla } from "./uyumDemoB";
import { hataKataloguUyarla, hataKosusuDetayUyarla, hataKosusuKimligi, hataKosusuUyarla, yakalamaOrani } from "./uyumKule";

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
