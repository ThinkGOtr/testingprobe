// 012/Ş8: ekilmiş hata koşusu mock arka ucu sözleşme gibi davranır (ANALIZ §4.6, §4.7).
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, HATA_KOSUSU_SURUYOR, hataKosusuApi } from "../client";
import { ApiError } from "../http";
import type { PortalOlayi } from "../types";
import { oturumAc } from "../../test/yardimci";
import { bekleyenMockIs, mockIstek, mockSifirla } from "./handlers";
import { kuleAyar, kuleMockIlerlet, kuleMockKosulariBosalt, kuleMockZamanlayiciVar } from "./kule";
import { HATA_KATALOGU } from "./kuleVerisi";
import { mockOlaylaraAbone } from "./olaylar";

afterEach(() => {
  vi.useRealTimers();
});

async function hataBekle(p: Promise<unknown>): Promise<ApiError> {
  try {
    await p;
  } catch (e) {
    if (e instanceof ApiError) return e;
    throw e;
  }
  throw new Error("hata bekleniyordu");
}

describe("katalog ve örnek koşu", () => {
  it("katalog dokuz hata taşır (K9: kampanya_esik_7 yerine kampanya_tek_bedava): beş kod, dört veri; kural ve ayırt edici örnek", async () => {
    await oturumAc("analist");
    const k = await hataKosusuApi.katalog();
    expect(k.map((h) => h.kod)).toEqual([
      "kampanya_bedava_yok",
      "kampanya_tek_bedava",
      "kampanya_cift_indirim",
      "min_siparis_haric",
      "min_siparis_muafiyet_yok",
      "min_siparis_500",
      "min_siparis_1000",
      "fiyat_p004_31",
      "kampanya_urunu_p002",
    ]);
    expect(k.filter((h) => h.tur === "kod")).toHaveLength(5);
    expect(k.filter((h) => h.tur === "veri")).toHaveLength(4);
    for (const h of k) {
      expect(h.kod).toMatch(/^[a-z0-9_]{1,40}$/);
      expect(h.ad).not.toBe(h.kod);
      expect(h.aciklama.length).toBeGreaterThan(10);
      expect(h.yakalayan_kural).toBeTruthy();
      // K9: her kayıt kuralını (AC, tablo) ve ayırt edici örneğini taşır.
      expect(h.ac_refs?.length).toBeGreaterThan(0);
      expect(h.ayirt_edici?.girdi).toBeTruthy();
    }
    expect(k.find((h) => h.kod === "kampanya_tek_bedava")).toMatchObject({
      ac_refs: ["AC2"],
      tablo: "T1",
      ayirt_edici: { girdi: "adet = 14", dogru: "bedava_adet = 2", hatali: "bedava_adet = 1" },
    });
    // core rules/hata-katalogu.yaml ile birebir.
    expect(k.find((h) => h.kod === "fiyat_p004_31")).toEqual({
      kod: "fiyat_p004_31",
      ad: "P-004 fiyatı 31",
      tur: "veri",
      aciklama: "P-004 ürününün birim fiyatı 30 yerine 31 okunur.",
      yakalayan_kural: "Satır ve sepet toplamı",
      ac_refs: ["AC1"],
      tablo: null,
      ayirt_edici: { girdi: "1 adet P-004", dogru: "satır tutarı = 30,00", hatali: "satır tutarı = 31,00" },
      requirement_id: "req-tpd-1",
    });
  });

  it("bitmiş örnek koşu: web + android; yakalanan, kaçan ve android'de bir geçersiz; oran geçersizi saymaz", async () => {
    await oturumAc("analist");
    const [k] = await hataKosusuApi.liste();
    expect(k).toMatchObject({ id: "hk-1", durum: "done", platformlar: ["web", "android"], baslatan: "muhendis" });
    // K12: ana oran yalnız AI (üretilmiş) testleri — demo deposunda yok → ölçülmedi; el yazısı suite ayrı
    // (web 8/9, yalnız kampanya_tek_bedava kaçar; android 7/8 + 1 geçersiz).
    expect(k.ozet).toMatchObject({ oran: null, yakalanan: 0, kacan: 0, gecersiz: 1, bekleyen: 0 });
    expect(k.ozet?.el_yazisi).toEqual({ oran: 15 / 17, yakalanan: 15, kacan: 2 });
    // R4: tam_katalog + geçerli adım sayısı (web 9 + android 8).
    expect(k.ozet?.kapsam).toEqual({ kosulan_hata: 9, katalog: 9, platformlar: ["web", "android"], tam_katalog: true, gecerli_adim: 17 });
    expect(k.ozet?.tum_testler).toEqual({ oran: 15 / 17, yakalanan: 15, kacan: 2 });
    // R4: platform başına suite sayıları (üretilmiş test yok; 29 el yazısı) ve tüm testler.
    const ortak = { oran: null, yakalanan: 0, kacan: 0, bekleyen: 0, temel: "yesil", kapanis: "yesil", uretilen_test: 0, el_test: 29 };
    expect(k.ozet?.platformlar).toEqual([
      { platform: "web", ...ortak, gecersiz: 0, el_yazisi: { oran: 8 / 9, yakalanan: 8, kacan: 1 }, tum_testler: { oran: 8 / 9, yakalanan: 8, kacan: 1 } },
      { platform: "android", ...ortak, gecersiz: 1, el_yazisi: { oran: 7 / 8, yakalanan: 7, kacan: 1 }, tum_testler: { oran: 7 / 8, yakalanan: 7, kacan: 1 } },
    ]);
    expect(k.ozet?.kacanlar).toEqual([
      { hata_kodu: "kampanya_tek_bedava", ad: "Kampanyada en çok 1 bedava", platform: "web" },
      { hata_kodu: "kampanya_tek_bedava", ad: "Kampanyada en çok 1 bedava", platform: "android" },
    ]);
    const d = await hataKosusuApi.detay("hk-1");
    // Platform başına temel + 9 hata + kapanış.
    expect(d.adimlar).toHaveLength(22);
    expect(d.adimlar.map((a) => a.sira)).toEqual(Array.from({ length: 22 }, (_, i) => i + 1));
    expect(d.adimlar.filter((a) => a.asama === "temel").map((a) => a.sonuc)).toEqual(["yesil", "yesil"]);
    const gecersiz = d.adimlar.filter((a) => a.sonuc === "gecersiz");
    expect(gecersiz).toHaveLength(1);
    expect(gecersiz[0]).toMatchObject({ platform: "android", hata_kodu: "min_siparis_1000", run_id: null });
    expect(gecersiz[0].neden).toMatch(/Appium/);
    const yakalanan = d.adimlar.find((a) => a.platform === "web" && a.hata_kodu === "kampanya_bedava_yok");
    expect(yakalanan?.sonuc).toBe("yakalandi");
    // §13.2: kıran testler kaynaklarıyla; demo deposunda hepsi el yazısı.
    expect(yakalanan?.kiran_testler).toEqual([
      { test: "kampanya: 7 adet P-001 → 1 bedava, toplam 150,00 TL", kaynak: "el" },
      { test: "onaylanan sipariş numarasıyla gösterilir ve geçmişte listelenir", kaynak: "el" },
      { test: "7 adet Portakal Gazozu sepette 1 bedava adet ve sayaç 7 gösterir", kaynak: "el" },
    ]);
    expect(d.adimlar.every((a) => a.kiran_testler.every((t) => t.kaynak === "el"))).toBe(true);
    // Temel koşuda kırmızı test yok (alan var, boş).
    expect(d.adimlar.every((a) => Array.isArray(a.temelde_kirmizi) && a.temelde_kirmizi.length === 0)).toBe(true);
    // Ölçülen gerçek matris (R4): assertion kırmızısı sayıları 3, 2, 1, 1, 4, 5, 5, 7; locator / zaman aşımıyla
    // düşenler sayılmaz ve adım notunda yazılır (haric 1, 1000 2, p002 1).
    const sayilar = Object.fromEntries(d.adimlar.filter((a) => a.platform === "web" && a.asama === "hata").map((a) => [a.hata_kodu, a.kiran_testler.length]));
    expect(sayilar).toEqual({
      kampanya_bedava_yok: 3,
      kampanya_tek_bedava: 0,
      kampanya_cift_indirim: 2,
      min_siparis_haric: 1,
      min_siparis_muafiyet_yok: 1,
      min_siparis_500: 4,
      min_siparis_1000: 5,
      fiyat_p004_31: 5,
      kampanya_urunu_p002: 7,
    });
    const notlar = Object.fromEntries(
      d.adimlar.filter((a) => a.platform === "web" && a.asama === "hata" && a.neden).map((a) => [a.hata_kodu, Number(/^(\d+) test/.exec(a.neden ?? "")?.[1])]),
    );
    expect(notlar).toEqual({ min_siparis_haric: 1, min_siparis_1000: 2, kampanya_urunu_p002: 1 });
    // core `_adim_sozluk`: adımda katalog adı.
    expect(d.adimlar.find((a) => a.hata_kodu === "fiyat_p004_31")?.hata_adi).toBe("P-004 fiyatı 31");
    expect(d.adimlar[0].hata_adi).toBeNull();
  });

  it("adımın koşu kaydı: tetik break_verify, ortam.hata_kodu → Kosu.hata_kodu; kıran testler kırmızı", async () => {
    await oturumAc("analist");
    const d = await hataKosusuApi.detay("hk-1");
    const a = d.adimlar.find((x) => x.platform === "web" && x.hata_kodu === "kampanya_bedava_yok");
    const k = await api.kosu(a?.run_id ?? "");
    expect(k).toMatchObject({ tetik: "break_verify", platform: "web", hata_kodu: "kampanya_bedava_yok", hata_kosusu_id: "hk-1", durum: "failed" });
    expect(k.sonuclar.filter((s) => s.durum === "failed").map((s) => s.test_adi)).toEqual(a?.kiran_testler.map((t) => t.test));
    // Temel koşu: hata kodu yok, yeşil.
    const temel = await api.kosu(d.adimlar[0].run_id ?? "");
    expect(temel.durum).toBe("passed");
    expect(temel.hata_kodu).toBeUndefined();
    // Ekilmiş hata adımları genel koşu listesine ve Kule'nin son koşularına karışmaz.
    expect((await api.kosular()).some((x) => x.id.startsWith("hk-"))).toBe(false);
    expect((await hataBekle(api.kosu("hk-1-r999"))).status).toBe(404);
  });

  it("Kule: beklenti_dogrulugu ve hata_yakalama anahtarları + kaynakları; koşu yokken hata_yakalama null", async () => {
    await oturumAc("analist");
    const k = await api.kontrolKulesi();
    expect(k.beklenti_dogrulugu).toMatchObject({ uyumlu: 5, uyumsuz: 1, kismen: 1, istisna: 1, kontrolsuz_onay: 0, n_case: 10, n_story: 1, tablolu_story: 1, toplam_story: 4, golden_kaynakli: 10 });
    expect(k.beklenti_dogrulugu?.oran).toBeCloseTo(5 / 6);
    // Örnek veride ilk durumda onaylı ve tabloyla uyuşmayan case yok (liste örnek veriden hesaplanır).
    expect(k.onayli_uyumsuz).toEqual([]);
    expect(k.hata_yakalama).toMatchObject({
      son_kosu: { id: "hk-1", durum: "done" },
      oran: null,
      yakalanan: 0,
      kacan: 0,
      gecersiz: 1,
      el_yazisi: { yakalanan: 15, kacan: 2 },
      kapsam: { kosulan_hata: 9, katalog: 9, platformlar: ["web", "android"] },
    });
    // core `hata_yakalama_ozeti`: platform satırında yalnız sayılar (+ el yazısı).
    expect(k.hata_yakalama?.platformlar[0]).toEqual({ platform: "web", oran: null, yakalanan: 0, kacan: 0, gecersiz: 0, el_yazisi: { oran: 8 / 9, yakalanan: 8, kacan: 1 } });
    expect(k.kaynaklar.beklenti_dogrulugu).toMatch(/^AI'ın ürettiği case içeriklerinin .*case_oracle_kontrol/);
    expect(k.kaynaklar.hata_yakalama).toMatch(
      /^Son tamamlanan tam katalog ekilmiş hata koşusu \(2026-11-10 14:46; web, android\): AI oranı ölçülmedi \(üretilmiş test yok\); el yazısı 15\/17 \(%88\); geçersiz 1\. /,
    );
    kuleMockKosulariBosalt();
    const bos = await api.kontrolKulesi();
    expect(bos.hata_yakalama).toBeNull();
    expect(bos.kaynaklar.hata_yakalama).toMatch(/henüz yok \(ölçülmedi\)/);
    expect(await hataKosusuApi.liste()).toEqual([]);
  });
});

describe("Kule onayli_uyumsuz (§13.2)", () => {
  it("örnek veriden hesaplanır: tablo onayından sonra istisnayla onaylanan uyuşmaz case listeye girer", async () => {
    await oturumAc("analist");
    const t = (await api.kararTablolari("req-tpd-1")).tablolar.find((x) => /Minimum/.test(x.icerik.ad) && x.durum !== "superseded")!;
    await api.kararTablosuGecis(t.id, "submit", { icerik_hash: t.icerik_hash });
    await oturumAc("po");
    await api.kararTablosuGecis(t.id, "approve", { icerik_hash: t.icerik_hash });
    for (let i = 0; i < 200 && bekleyenMockIs() > 0; i++) await new Promise((r) => setTimeout(r, 5));
    await oturumAc("analist");
    const c = (await api.caseler("req-tpd-1")).find((x) => x.id === "case-1-7")!;
    expect(c.oracle?.sonuc).toBe("uyumsuz");
    expect((await api.kontrolKulesi()).onayli_uyumsuz).toEqual([]);
    await api.caseKarari(c.id, { icerik_hash: c.icerik_hash, karar: "approve", oracle_istisna_gerekce: "PO ile görüşüldü: sınır dahil kabul edildi." });
    expect((await api.kontrolKulesi()).onayli_uyumsuz).toEqual([{ case_id: "case-1-7", requirement_id: "req-tpd-1", baslik: c.icerik.title }]);
  });
});

describe("başlatma, ilerleme, iptal", () => {
  it("yalnız engineer ve presenter başlatır ve iptal eder (V4); diğer roller 403; oturumsuz 401", async () => {
    expect((await hataBekle(hataKosusuApi.liste())).status).toBe(401);
    for (const rol of ["analist", "po", "testci"]) {
      await oturumAc(rol);
      expect((await hataBekle(hataKosusuApi.baslat({ platformlar: ["web"] }))).status).toBe(403);
      expect((await hataBekle(hataKosusuApi.iptal("hk-1"))).status).toBe(403);
    }
    for (const rol of ["muhendis", "sunucu"]) {
      mockSifirla();
      await oturumAc(rol);
      kuleAyar.adimMs = 3_600_000;
      expect((await hataKosusuApi.baslat({ platformlar: ["web"] })).id).toBe("hk-2");
    }
  });

  it("gövde doğrulaması: platform ve hata kodu katalogdan; hatalar verilmezse kataloğun tamamı", async () => {
    await oturumAc("muhendis");
    kuleAyar.adimMs = 3_600_000;
    expect((await hataBekle(hataKosusuApi.baslat({ platformlar: [] }))).status).toBe(422);
    expect((await hataBekle(hataKosusuApi.baslat({ platformlar: ["web"], hatalar: ["yok_boyle_hata"] }))).status).toBe(422);
    expect((await hataBekle(hataKosusuApi.baslat({ platformlar: ["web"], hatalar: [] }))).status).toBe(422);
    const { id } = await hataKosusuApi.baslat({ platformlar: ["android", "web"] });
    const d = await hataKosusuApi.detay(id ?? "");
    // Platformlar sabit sırayla koşar (web önce).
    expect(d.platformlar).toEqual(["web", "android"]);
    expect(d.hatalar).toEqual(HATA_KATALOGU.map((h) => h.kod));
    expect(d).toMatchObject({ durum: "queued", baslatan: "muhendis", ozet: null, baslama: null });
  });

  it("sahte saatle adım adım: queued → running → her adım bir olay → done; süren koşu varken 409 hata_kosusu_suruyor", async () => {
    vi.useFakeTimers();
    await oturumAc("sunucu");
    kuleAyar.adimMs = 1000;
    const olaylar: PortalOlayi[] = [];
    const birak = mockOlaylaraAbone((o) => {
      if (o.type === "hata_kosusu.ilerleme") olaylar.push(o);
    });
    try {
      const { id } = await hataKosusuApi.baslat({ platformlar: ["web"], hatalar: ["kampanya_bedava_yok", "kampanya_tek_bedava"] });
      expect(id).toBe("hk-2");
      expect((await hataKosusuApi.detay("hk-2")).durum).toBe("queued");

      const cakisma = await hataBekle(hataKosusuApi.baslat({ platformlar: ["web"] }));
      expect(cakisma.status).toBe(409);
      expect(cakisma.kod).toBe(HATA_KOSUSU_SURUYOR);

      await vi.advanceTimersByTimeAsync(999);
      expect((await hataKosusuApi.detay("hk-2")).durum).toBe("queued");
      await vi.advanceTimersByTimeAsync(1);
      let d = await hataKosusuApi.detay("hk-2");
      expect(d.durum).toBe("running");
      expect(d.baslama).not.toBeNull();
      expect(d.adimlar.map((a) => a.sonuc)).toEqual(["bekliyor", "bekliyor", "bekliyor", "bekliyor"]);

      await vi.advanceTimersByTimeAsync(1000); // temel
      d = await hataKosusuApi.detay("hk-2");
      expect(d.adimlar.map((a) => a.sonuc)).toEqual(["yesil", "bekliyor", "bekliyor", "bekliyor"]);
      expect(d.adimlar[0].run_id).toBe("hk-2-r1");

      await vi.advanceTimersByTimeAsync(2000); // iki hata
      d = await hataKosusuApi.detay("hk-2");
      expect(d.adimlar.map((a) => a.sonuc)).toEqual(["yesil", "yakalandi", "kacti", "bekliyor"]);
      expect(d.durum).toBe("running");
      expect(d.ozet).toBeNull();

      await vi.advanceTimersByTimeAsync(1000); // kapanış
      d = await hataKosusuApi.detay("hk-2");
      expect(d.durum).toBe("done");
      expect(d.bitis).not.toBeNull();
      expect(d.ozet).toMatchObject({ oran: null, el_yazisi: { oran: 0.5, yakalanan: 1, kacan: 1 }, gecersiz: 0, kapsam: { kosulan_hata: 2, katalog: 9 } });
      expect(kuleMockZamanlayiciVar()).toBe(false);
      expect(vi.getTimerCount()).toBe(0);

      // Olay yükü: {id, durum, platform, hata_kodu, asama, sonuc}.
      expect(olaylar.map((o) => o.data.durum)).toEqual(["queued", "running", "running", "running", "running", "done"]);
      expect(olaylar[3]).toMatchObject({ id: "hk-2", data: { id: "hk-2", platform: "web", hata_kodu: "kampanya_bedava_yok", asama: "hata", sonuc: "yakalandi" } });
      expect(olaylar[2].data).toMatchObject({ platform: "web", hata_kodu: null, asama: "temel", sonuc: "yesil" });
      expect(olaylar[0].data).toEqual({ id: "hk-2", durum: "queued", platform: null, hata_kodu: null, asama: null, sonuc: null });
      expect(olaylar[4].data).toMatchObject({ hata_kodu: "kampanya_tek_bedava", sonuc: "kacti" });

      // §13.2: kısmi katalog koşusu Kule ölçüsüne girmez (son tam katalog koşusu hk-1); yeni koşu başlatılabilir.
      expect((await api.kontrolKulesi()).hata_yakalama).toMatchObject({ son_kosu: { id: "hk-1" } });
      expect((await hataKosusuApi.baslat({ platformlar: ["web"] })).id).toBe("hk-3");
    } finally {
      birak();
    }
  });

  it("tam katalog ve geçerli adımı olan bitmiş koşu Kule ölçüsü olur; yalnız geçersiz adımlı koşu olmaz", async () => {
    await oturumAc("muhendis");
    kuleAyar.adimMs = 3_600_000;
    await hataKosusuApi.baslat({ platformlar: ["ios"] }); // tümü geçersiz (cihaz kapalı)
    while (kuleMockIlerlet());
    expect((await api.kontrolKulesi()).hata_yakalama?.son_kosu.id).toBe("hk-1");
    await hataKosusuApi.baslat({ platformlar: ["web"] });
    while (kuleMockIlerlet());
    const h = (await api.kontrolKulesi()).hata_yakalama;
    expect(h).toMatchObject({ son_kosu: { id: "hk-3" }, oran: null, el_yazisi: { yakalanan: 8, kacan: 1 }, kapsam: { kosulan_hata: 9, katalog: 9, platformlar: ["web"] } });
  });

  it("cihaz kapalı platform (iOS): temel koşu koşulamaz → tüm adımlar geçersiz, neden yazılı; oran etkilenmez", async () => {
    await oturumAc("muhendis");
    kuleAyar.adimMs = 3_600_000;
    await hataKosusuApi.baslat({ platformlar: ["web", "ios"], hatalar: ["kampanya_bedava_yok"] });
    while (kuleMockIlerlet());
    const d = await hataKosusuApi.detay("hk-2");
    expect(d.durum).toBe("done");
    const ios = d.adimlar.filter((a) => a.platform === "ios");
    expect(ios.map((a) => a.sonuc)).toEqual(["gecersiz", "gecersiz", "gecersiz"]);
    expect(ios[0].neden).toMatch(/iOS simülatörüne ulaşılamadı/);
    expect(ios[1].neden).toMatch(/Temel koşu yeşil değil/);
    expect(ios.every((a) => a.run_id === null)).toBe(true);
    expect(d.ozet).toMatchObject({ oran: null, el_yazisi: { oran: 1, yakalanan: 1, kacan: 0 }, gecersiz: 1 });
    expect(d.ozet?.platformlar[1]).toEqual({
      platform: "ios",
      oran: null,
      yakalanan: 0,
      kacan: 0,
      el_yazisi: { oran: null, yakalanan: 0, kacan: 0 },
      tum_testler: { oran: null, yakalanan: 0, kacan: 0 },
      gecersiz: 1,
      bekleyen: 0,
      uretilen_test: 0,
      el_test: 29,
      temel: "gecersiz",
      kapanis: "gecersiz",
    });
    expect(d.uyarilar.join(" ")).toMatch(/temel koşu yeşil değil/);
  });

  it("iptal (R4): iptal_istendi, süren adım bitince cancelled; kalan adımlar bekliyor, zamanlayıcı temizlenir; biten koşu iptal edilemez (409)", async () => {
    vi.useFakeTimers();
    await oturumAc("muhendis");
    kuleAyar.adimMs = 1000;
    await hataKosusuApi.baslat({ platformlar: ["web"] });
    await vi.advanceTimersByTimeAsync(3000); // running + temel + ilk hata
    expect(kuleMockZamanlayiciVar()).toBe(true);
    await hataKosusuApi.iptal("hk-2");
    // Koşu hemen durmaz: durum running, iptal_istendi; süren adım bitince durur.
    const ara = await hataKosusuApi.detay("hk-2");
    expect(ara).toMatchObject({ durum: "running", iptal_istendi: true });
    // İkinci iptal isteği aynı yanıtı verir (yeni uyarı eklenmez).
    await hataKosusuApi.iptal("hk-2");
    await vi.advanceTimersByTimeAsync(60_000);
    expect(kuleMockZamanlayiciVar()).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
    const d = await hataKosusuApi.detay("hk-2");
    expect(d.durum).toBe("cancelled");
    expect(d.adimlar.filter((a) => a.sonuc !== "bekliyor")).toHaveLength(3);
    expect(d.uyarilar.filter((u) => u.includes("iptal"))).toHaveLength(1);
    // İptal edilen koşu Kule ölçüsüne girmez (son bitmiş koşu hâlâ hk-1).
    expect((await api.kontrolKulesi()).hata_yakalama?.son_kosu.id).toBe("hk-1");
    // core: bitmiş koşu → 409 `cakisma`, "Koşu iptal edilemez (durum: …)".
    expect(await hataBekle(hataKosusuApi.iptal("hk-2"))).toMatchObject({ status: 409, kod: "cakisma", message: "Koşu iptal edilemez (durum: cancelled)." });
    expect((await hataBekle(hataKosusuApi.iptal("hk-1"))).status).toBe(409);
    expect(d.uyarilar).toContain("muhendis tarafından iptal edildi.");
    expect((await hataBekle(hataKosusuApi.iptal("yok"))).status).toBe(404);
  });

  it("core gövdeleri: POST /fault-runs `{id, durum}`, /cancel `{id, durum, iptal_istendi}`; geçersiz gövde 422 gecersiz_istek", async () => {
    await oturumAc("muhendis");
    kuleAyar.adimMs = 3_600_000;
    expect(await mockIstek("POST", "/fault-runs", new URLSearchParams(), { platformlar: ["web"] })).toEqual({ id: "hk-2", durum: "queued" });
    expect(await mockIstek("POST", "/fault-runs/hk-2/cancel", new URLSearchParams(), undefined)).toEqual({ id: "hk-2", durum: "queued", iptal_istendi: true });
    // Sırada bekleyen koşu da bir sonraki adımda durur.
    kuleMockIlerlet();
    expect((await hataKosusuApi.detay("hk-2")).durum).toBe("cancelled");
    expect(await hataBekle(hataKosusuApi.baslat({ platformlar: [] }))).toMatchObject({ status: 422, kod: "gecersiz_istek" });
    expect(await hataBekle(hataKosusuApi.baslat({ platformlar: ["web"], hatalar: ["yok_boyle"] }))).toMatchObject({ status: 422, kod: "gecersiz_istek" });
  });

  it("mockSifirla süren koşunun zamanlayıcısını temizler (testler arasında sızmaz)", async () => {
    vi.useFakeTimers();
    await oturumAc("muhendis");
    await hataKosusuApi.baslat({ platformlar: ["web"] });
    expect(kuleMockZamanlayiciVar()).toBe(true);
    expect(vi.getTimerCount()).toBe(1);
    mockSifirla();
    expect(kuleMockZamanlayiciVar()).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
    await oturumAc("muhendis");
    expect((await hataKosusuApi.liste()).map((k) => k.id)).toEqual(["hk-1"]);
  });
});
