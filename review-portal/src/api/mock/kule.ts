// 012/Ş8 mock arka ucu: ekilmiş hata koşusu uçları (ANALIZ §4.6) ve Kule'nin iki kalite anahtarı (§4.7).
// Sözleşme gibi davranır: yalnız `fault_run.manage` (engineer, admin) başlatır ve iptal eder, süren koşu varken 409
// `hata_kosusu_suruyor`, platformlar sırayla koşar (temel → her hata → kapanış), her adımda
// `hata_kosusu.ilerleme` olayı. Koşu tek bir zamanlayıcıyla ilerler; `kuleMockSifirla` zamanlayıcıyı
// temizler (testler arasında sızmaz) ve testler `kuleMockIlerlet` ya da sahte saatle adım adım sürer.
import { ApiError } from "../http";
import { PLATFORMLAR, platformUyarla, type Platform } from "../../lib/platform";
import type {
  HataKosusu,
  HataKosusuAdimi,
  HataKosusuDetay,
  HataKosusuOzeti,
  HataYakalamaPlatformu,
  KontrolKulesi,
  KosuDetay,
  Kullanici,
} from "../types";
import { kaynakOrani, yakalamaOrani } from "../uyumKule";
import { mockOlayYayinla } from "./olaylar";
import type { Izin } from "../../lib/yetki";
import { adimiSonuclandir, adimIskeleti, AI_TESTLERI, HATA_KATALOGU, ilkHataKosulari, KULE_KALITE_KAYNAKLARI, PAKET_TESTLERI, TEMELDE_KIRMIZI } from "./kuleVerisi";
import type { MockVeri } from "./fixtures";
import { beklentiDogruluguHesapla, onayliUyumsuzHesapla } from "./kalite";

const testModu = import.meta.env.MODE === "test";
/** Bir adımın süresi (ms). Testler değiştirebilir; `kuleMockSifirla` varsayılana döndürür. */
const VARSAYILAN_ADIM_MS = testModu ? 20 : 1400;
export const kuleAyar = { adimMs: VARSAYILAN_ADIM_MS };

const BASLATMA_IZNI: Izin = "fault_run.manage";
/** core `TP_HATA_KOSUSU_GECERLI_ESIK` varsayılanı (Y10). */
const GECERLI_ESIK = 0.5;
const HATA_KODU_KALIBI = /^[a-z0-9_]{1,40}$/;

let kosular: HataKosusuDetay[] = [];
let sayac = 1;
let zamanlayici: ReturnType<typeof setTimeout> | null = null;

const katalogAdi = (kod: string | null): string | null => (kod ? (HATA_KATALOGU.find((h) => h.kod === kod)?.ad ?? kod) : null);

/**
 * K12 (§13.2): `oran`, `yakalanan`, `kacan` yalnız AI (üretilmiş) testlerle; el yazısı suite `el_yazisi`'nde.
 * Üretilmiş test yokken AI oranı null (ölçülmedi), sayılar 0.
 */
function ayrik(adimlar: HataKosusuAdimi[]) {
  const ai = kaynakOrani(adimlar, "ai");
  const el = kaynakOrani(adimlar, "el");
  const tum = yakalamaOrani(adimlar);
  return {
    oran: ai.oran,
    yakalanan: ai.olculdu ? ai.yakalanan : 0,
    kacan: ai.olculdu ? ai.kacan : 0,
    el_yazisi: { oran: el.oran, yakalanan: el.yakalanan, kacan: el.kacan },
    tum_testler: { oran: tum.oran, yakalanan: tum.yakalanan, kacan: tum.kacan },
  };
}

/** core `ozet_hesapla`: platform başına sayılar + `bekleyen`, `temel`, `kapanis`; toplamda `bekleyen`, `kapsam`. */
function ozetHesapla(k: HataKosusuDetay): HataKosusuOzeti {
  const platformlar: HataYakalamaPlatformu[] = k.platformlar.map((platform) => {
    const pa = k.adimlar.filter((a) => a.platform === platform);
    const { gecersiz, bekleyen } = yakalamaOrani(pa);
    return {
      platform,
      ...ayrik(pa),
      gecersiz,
      bekleyen,
      // Q2: yalnız temelde yeşil testler sayılır (temelde kırmızı C3 hariç); temel koşulamadıysa envanter yok.
      ...(pa.find((a) => a.asama === "temel")?.sonuc === "yesil"
        ? { uretilen_test: AI_TESTLERI.filter((t) => !TEMELDE_KIRMIZI.includes(t)).length, el_test: PAKET_TESTLERI.length - AI_TESTLERI.length }
        : {}),
      temel: pa.find((a) => a.asama === "temel")?.sonuc ?? null,
      kapanis: pa.find((a) => a.asama === "kapanis")?.sonuc ?? null,
      gecerli_adim: pa.filter((a) => a.asama === "hata" && (a.sonuc === "yakalandi" || a.sonuc === "kacti")).length,
    };
  });
  // Y10 (Q2): her platformda geçerli hata adımı ≥ eşik × katalog; değilse Kule oranları null ve not nedeni söyler.
  const yetersiz = platformlar.filter((p) => (p.gecerli_adim ?? 0) === 0 || (p.gecerli_adim ?? 0) < GECERLI_ESIK * HATA_KATALOGU.length);
  const { gecersiz, bekleyen } = yakalamaOrani(k.adimlar);
  return {
    ...ayrik(k.adimlar),
    gecersiz,
    bekleyen,
    kapsam: {
      kosulan_hata: k.hatalar.length,
      katalog: HATA_KATALOGU.length,
      platformlar: [...k.platformlar],
      tam_katalog: HATA_KATALOGU.every((h) => k.hatalar.includes(h.kod)),
      gecerli_adim: k.adimlar.filter((a) => a.asama === "hata" && (a.sonuc === "yakalandi" || a.sonuc === "kacti")).length,
      esik: GECERLI_ESIK,
      yeterli: yetersiz.length === 0,
      not: yetersiz.length
        ? `Geçerli hata adımı kataloğun %${Math.round(GECERLI_ESIK * 100)}'inin altında (${yetersiz.map((p) => `${p.platform} ${p.gecerli_adim}/${HATA_KATALOGU.length}`).join("; ")}); oran ölçü sayılmaz.`
        : null,
    },
    platformlar,
    // Q2: `kacanlar` = hiçbir testin yakalamadığı; `ai_kacanlar` = üretilen testlerin kaçırdığı (el yazısı yakalamış olabilir).
    kacanlar: k.adimlar
      .filter((a) => a.asama === "hata" && a.sonuc === "kacti" && a.hata_kodu)
      .map((a) => ({ hata_kodu: a.hata_kodu as string, ad: katalogAdi(a.hata_kodu) as string, platform: a.platform })),
    ai_kacanlar: k.adimlar
      .filter((a) => a.asama === "hata" && (a.sonuc === "kacti" || a.sonuc === "yakalandi") && a.hata_kodu && !a.kiran_testler.some((t) => t.kaynak === "ai"))
      .map((a) => ({ hata_kodu: a.hata_kodu as string, ad: katalogAdi(a.hata_kodu) as string, platform: a.platform })),
  };
}

function ilkDurum(): HataKosusuDetay[] {
  return ilkHataKosulari().map((k) => ({ ...k, ozet: ozetHesapla(k) }));
}
kosular = ilkDurum();

function zamanlayiciyiTemizle(): void {
  if (zamanlayici !== null) clearTimeout(zamanlayici);
  zamanlayici = null;
}

/** Testler ve "Demoyu sıfırla" için: koşuları ilk haline getirir, bekleyen zamanlayıcıyı temizler. */
export function kuleMockSifirla(): void {
  zamanlayiciyiTemizle();
  kosular = ilkDurum();
  sayac = 1;
  kuleAyar.adimMs = VARSAYILAN_ADIM_MS;
}

/** Bekleyen ilerleme zamanlayıcısı var mı (testler sızıntıyı bununla doğrular). */
export function kuleMockZamanlayiciVar(): boolean {
  return zamanlayici !== null;
}

/** Testler için: örnek koşuları boşaltır ("henüz koşu yok" hali). */
export function kuleMockKosulariBosalt(): void {
  zamanlayiciyiTemizle();
  kosular = [];
}

const suren = (): HataKosusuDetay | undefined => kosular.find((k) => k.durum === "queued" || k.durum === "running");

function olay(k: HataKosusuDetay, a: HataKosusuAdimi | null): void {
  mockOlayYayinla({
    type: "hata_kosusu.ilerleme",
    id: k.id,
    data: { id: k.id, durum: k.durum, platform: a?.platform ?? null, hata_kodu: a?.hata_kodu ?? null, asama: a?.asama ?? null, sonuc: a?.sonuc ?? null },
  });
}

function planla(): void {
  zamanlayiciyiTemizle();
  if (!suren()) return;
  zamanlayici = setTimeout(() => {
    zamanlayici = null;
    kuleMockIlerlet();
  }, kuleAyar.adimMs);
}

/**
 * Süren koşuyu bir adım ilerletir (zamanlayıcının yaptığı iş). İlk çağrı `queued → running`; sonra her
 * çağrı sıradaki adımı sonuçlandırır (temel koşu yeşil değilse platformun kalan adımları aynı adımda
 * geçersiz olur); adım kalmayınca koşu `done`. Dönüş: koşu hâlâ sürüyor mu.
 */
export function kuleMockIlerlet(): boolean {
  const k = suren();
  if (!k) return false;
  // R4: iptal istendiyse süren adım biter (bu çağrı), sonra koşu `cancelled` olur; kalan adımlar koşulmaz.
  if (k.iptal_istendi) {
    const a = k.durum === "running" ? k.adimlar.find((x) => x.sonuc === "bekliyor") : undefined;
    if (a) {
      const temel = k.adimlar.find((x) => x.platform === a.platform && x.asama === "temel");
      adimiSonuclandir(k.id, a, a.asama === "temel" || temel?.sonuc === "yesil");
    }
    k.durum = "cancelled";
    k.bitis = new Date().toISOString();
    k.ozet = ozetHesapla(k);
    olay(k, a ?? null);
    zamanlayiciyiTemizle();
    return false;
  }
  if (k.durum === "queued") {
    k.durum = "running";
    k.baslama = new Date().toISOString();
    olay(k, null);
    planla();
    return true;
  }
  const a = k.adimlar.find((x) => x.sonuc === "bekliyor");
  if (a) {
    const temel = k.adimlar.find((x) => x.platform === a.platform && x.asama === "temel");
    adimiSonuclandir(k.id, a, a.asama === "temel" || temel?.sonuc === "yesil");
    if (a.asama === "temel" && a.sonuc !== "yesil") {
      // §4.6: temel koşu yeşil değilse platformun tüm adımları geçersiz.
      for (const x of k.adimlar.filter((y) => y.platform === a.platform && y.sonuc === "bekliyor")) adimiSonuclandir(k.id, x, false);
      k.uyarilar.push(`${a.platform}: temel koşu yeşil değil; bu platformun adımları geçersiz sayıldı.`);
    }
  }
  if (!k.adimlar.some((x) => x.sonuc === "bekliyor")) {
    k.durum = "done";
    k.bitis = new Date().toISOString();
    k.ozet = ozetHesapla(k);
    olay(k, a ?? null);
    zamanlayiciyiTemizle();
    return false;
  }
  olay(k, a ?? null);
  planla();
  return true;
}

function baslat(kullanici: Kullanici, govde: unknown): Pick<HataKosusu, "id" | "durum"> {
  const g = (govde && typeof govde === "object" ? govde : {}) as { platformlar?: unknown; hatalar?: unknown };
  if (suren()) throw new ApiError(409, "Süren bir ekilmiş hata koşusu var; bitmeden yenisi başlatılamaz.", { kod: "hata_kosusu_suruyor" });
  const ham = Array.isArray(g.platformlar) ? g.platformlar : [];
  const secilen = ham.map(platformUyarla);
  if (secilen.length === 0 || secilen.some((p) => p === null)) throw new ApiError(422, "En az bir geçerli platform seçin (web, android, ios, windows).", { kod: "gecersiz_istek" });
  // Platformlar sabit sırayla koşar (web → android → ios → windows), yinelenen değer bir kez.
  const platformlar = PLATFORMLAR.filter((p) => secilen.includes(p)) as Platform[];
  const katalog = HATA_KATALOGU.map((h) => h.kod);
  let hatalar = katalog;
  if (g.hatalar !== undefined && g.hatalar !== null) {
    if (!Array.isArray(g.hatalar) || g.hatalar.length === 0) throw new ApiError(422, "En az bir hata seçin.", { kod: "gecersiz_istek" });
    const bilinmeyen = g.hatalar.filter((h) => typeof h !== "string" || !HATA_KODU_KALIBI.test(h) || !katalog.includes(h));
    if (bilinmeyen.length) throw new ApiError(422, `Katalogda olmayan hata kodu: ${bilinmeyen.join(", ")}`, { kod: "gecersiz_istek" });
    hatalar = katalog.filter((h) => (g.hatalar as string[]).includes(h));
  }
  sayac += 1;
  const id = `hk-${sayac}`;
  const k: HataKosusuDetay = {
    id,
    durum: "queued",
    platformlar,
    hatalar,
    commit: "9c41e2b07a11",
    baslatan_id: kullanici.id,
    baslatan: kullanici.kullanici_adi,
    ozet: null,
    uyarilar: [],
    baslama: null,
    bitis: null,
    olusturma: new Date().toISOString(),
    adimlar: adimIskeleti(id, platformlar, hatalar),
  };
  kosular.unshift(k);
  olay(k, null);
  planla();
  // core 202 gövdesi: yalnız `{id, durum}`.
  return { id: k.id, durum: k.durum };
}

/**
 * core `iptal` (R4): `{id, durum, iptal_istendi}`. Koşu hemen durmaz — süren adım bitince `cancelled` olur
 * (zamanlayıcının bir sonraki adımı). Bitmiş koşu (done | failed | cancelled) → 409 (kod `cakisma`).
 */
function iptal(id: string, kullanici: Kullanici): Pick<HataKosusu, "id" | "durum" | "iptal_istendi"> {
  const k = bul(id);
  if (k.durum !== "queued" && k.durum !== "running") throw new ApiError(409, `Koşu iptal edilemez (durum: ${k.durum}).`, { kod: "cakisma" });
  if (!k.iptal_istendi) {
    k.iptal_istendi = true;
    k.uyarilar.push(`${kullanici.kullanici_adi} tarafından iptal edildi.`);
    olay(k, null);
  }
  return { id: k.id, durum: k.durum, iptal_istendi: true };
}

function bul(id: string): HataKosusuDetay {
  const k = kosular.find((x) => x.id === id);
  if (!k) throw new ApiError(404, `Ekilmiş hata koşusu bulunamadı: ${id}`);
  return k;
}

function ozet(k: HataKosusuDetay): HataKosusu {
  const { adimlar: _a, ...o } = k;
  void _a;
  return o;
}

/** Adımın `run` kaydı (`GET /runs/{id}`): core V6 gibi `tetik='break_verify'` + `ortam.hata_kodu`. */
function adimKosusu(runId: string): KosuDetay & { ortam: Record<string, unknown> } {
  for (const k of kosular) {
    const a = k.adimlar.find((x) => x.run_id === runId);
    if (!a) continue;
    // Temelde kırmızı testler (K12) her adım koşusunda kırmızıdır; yakalama sayılmaz.
    const kiran = new Set([...a.kiran_testler.map((t) => t.test), ...TEMELDE_KIRMIZI]);
    const sonuclar: KosuDetay["sonuclar"] = PAKET_TESTLERI.map((test_adi, i) => ({
      id: `${runId}-${i + 1}`,
      test_adi,
      durum: kiran.has(test_adi) ? "failed" : "passed",
      sure_ms: 2900 + i * 350,
      retry: 0,
      hata_mesaji: TEMELDE_KIRMIZI.includes(test_adi) ? "Assertion: temel koşuda da kırmızı (açık defect adayı; yakalama sayılmaz)." : kiran.has(test_adi) ? `Assertion: beklenen değer ekilmiş hata (${a.hata_kodu}) yüzünden tutmadı.` : null,
      failure_id: null,
      case_id: null,
    }));
    const basarisiz = sonuclar.filter((s) => s.durum === "failed").length;
    return {
      id: runId,
      tetik: "break_verify",
      kaynak: "local",
      commit: k.commit ?? "",
      pr_no: null,
      durum: basarisiz ? "failed" : "passed",
      baslangic: k.baslama ?? k.olusturma,
      sure_ms: a.sure_ms,
      toplam: sonuclar.length,
      gecen: sonuclar.length - basarisiz,
      basarisiz,
      flaky: 0,
      atlanan: 0,
      allure_url: null,
      rapor_url: null,
      sauce_url: null,
      ci_url: null,
      break_campaign: false,
      script_id: null,
      saglik_hatasi: null,
      log_url: null,
      hata: null,
      uyarilar: a.hata_kodu ? [`Ekilmiş hata koşusu: uygulama bu koşuda bilerek bozuldu (${a.hata_kodu}); kırmızı beklenir, bug taslağı açılmaz.`] : [],
      sonuclar,
      platform: a.platform,
      ortam: { platform: a.platform, hata_kosusu_id: k.id, ...(a.hata_kodu ? { hata_kodu: a.hata_kodu } : {}) },
    };
  }
  throw new ApiError(404, `Koşu bulunamadı: ${runId}`);
}

/**
 * Kule ölçüsüne giren koşu (§13.2): bitmiş (done), tüm kataloğu koşmuş ve en az bir geçerli (yakalandı |
 * kaçtı) adımı olan en son koşu. Kısmi seçimle başlatılan koşu kartta görünür ama Kule oranını değiştirmez.
 */
function olcuKosusu(): HataKosusuDetay | undefined {
  return kosular.find(
    (k) =>
      k.durum === "done" &&
      HATA_KATALOGU.every((h) => k.hatalar.includes(h.kod)) &&
      k.adimlar.some((a) => a.asama === "hata" && (a.sonuc === "yakalandi" || a.sonuc === "kacti")),
  );
}

/**
 * §13.2 `onayli_uyumsuz` (kalite.ts `onayliUyumsuzHesapla`): onaylı/yayınlı case'in güncel içeriği güncel onaylı
 * tablolarla uyuşmuyor ve aynı tablo kümesiyle verilmiş geçerli istisnası yok (u2 N10). Örnek veriden hesaplanır.
 */
export function onayliUyumsuz(v: MockVeri): NonNullable<KontrolKulesi["onayli_uyumsuz"]> {
  return onayliUyumsuzHesapla(v);
}

/** Kule yanıtına eklenen kalite anahtarları (§4.7, §13.2); ölçüye giren koşu yoksa `hata_yakalama: null`. */
/** Y10 (Q2): kapsam yetersizse sayılar kalır, tüm oran alanları null. */
function oranlariSil(o: HataKosusuOzeti): HataKosusuOzeti {
  if (o.kapsam?.yeterli !== false) return o;
  const sil = <T extends { oran: number | null }>(x: T | undefined) => (x ? { ...x, oran: null } : x);
  return {
    ...o,
    oran: null,
    el_yazisi: sil(o.el_yazisi),
    tum_testler: sil(o.tum_testler),
    platformlar: o.platformlar.map((p) => ({ ...p, oran: null, el_yazisi: sil(p.el_yazisi) })),
  };
}

export function kuleKaliteOlcumu(v: MockVeri): Required<Pick<KontrolKulesi, "beklenti_dogrulugu" | "hata_yakalama" | "onayli_uyumsuz">> {
  const son = olcuKosusu();
  const o = son ? oranlariSil(ozetHesapla(son)) : null;
  return {
    // u2 N1: sabit sayı yok — case kartlarıyla aynı hesap (kalite.ts `beklentiDogruluguHesapla`).
    beklenti_dogrulugu: beklentiDogruluguHesapla(v, null),
    onayli_uyumsuz: onayliUyumsuz(v),
    // core `hata_yakalama_ozeti`: platformlar yalnız sayılar (bekleyen/temel/kapanış koşu özetinde kalır).
    hata_yakalama:
      son && o
        ? {
            son_kosu: { id: son.id, bitis: son.bitis, durum: son.durum },
            oran: o.oran,
            yakalanan: o.yakalanan,
            kacan: o.kacan,
            gecersiz: o.gecersiz,
            platformlar: o.platformlar.map(({ platform, oran, yakalanan, kacan, gecersiz, el_yazisi }) => ({ platform, oran, yakalanan, kacan, gecersiz, el_yazisi })),
            kacanlar: o.kacanlar,
            ai_kacanlar: o.ai_kacanlar,
            el_yazisi: o.el_yazisi,
            tum_testler: o.tum_testler,
            kapsam: o.kapsam,
          }
        : null,
  };
}

/** core `hata_yakalama_ozeti` kaynak metni (İstanbul saatiyle bitiş, platformlar, sayılar, oran). */
export function kuleKaliteKaynaklariMock(): { beklenti_dogrulugu: string; hata_yakalama: string } {
  const son = olcuKosusu();
  if (!son) return { ...KULE_KALITE_KAYNAKLARI };
  const o = ozetHesapla(son);
  const p = son.bitis
    ? Object.fromEntries(
        new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Istanbul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
          .formatToParts(new Date(son.bitis))
          .map((x) => [x.type, x.value]),
      )
    : null;
  const tarih = p ? `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}` : "?";
  const oranMetni = o.oran !== null ? `AI oranı %${Math.round(o.oran * 100)}` : "AI oranı ölçülmedi (üretilmiş test yok)";
  const el = o.el_yazisi;
  const elMetni = el ? `el yazısı ${el.yakalanan}/${el.yakalanan + el.kacan}${el.oran !== null ? ` (%${Math.round(el.oran * 100)})` : ""}` : "";
  return {
    beklenti_dogrulugu: KULE_KALITE_KAYNAKLARI.beklenti_dogrulugu,
    hata_yakalama:
      `Son tamamlanan tam katalog ekilmiş hata koşusu (${tarih}; ${son.platformlar.join(", ")}): ` +
      `${oranMetni}; ${elMetni}; geçersiz ${o.gecersiz}. ` +
      "Oran = yakalanan / (yakalanan + kaçan), yalnız onaylı case'lerden üretilen testlerle; el yazısı suite ayrı sayılır. " +
      "Bir hata yalnız hatasız temelde yeşil olan bir testin kırmızıya dönmesiyle yakalanmış sayılır; geçersiz adımlar paydaya girmez (hata_kosusu, hata_kosusu_adim).",
  };
}

type Rota = [string, RegExp, (m: RegExpMatchArray, q: URLSearchParams, govde: unknown) => unknown];

/** handlers.ts ROTALAR'ına eklenen uçlar. `/fault-runs/catalog`, `/fault-runs/{id}`'den önce eşleşmeli. */
export function kuleRotalari(girisGerekli: () => Kullanici, izinGerekli: (...izinler: [Izin, ...Izin[]]) => Kullanici): Rota[] {
  return [
    [
      "GET",
      /^\/fault-runs\/catalog$/,
      () => {
        girisGerekli();
        return HATA_KATALOGU;
      },
    ],
    [
      "GET",
      /^\/fault-runs$/,
      (_m, q) => {
        girisGerekli();
        const limit = Math.max(1, Math.min(50, Number(q.get("limit")) || 20));
        return kosular.slice(0, limit).map(ozet);
      },
    ],
    ["POST", /^\/fault-runs$/, (_m, _q, g) => baslat(izinGerekli(BASLATMA_IZNI), g)],
    [
      "GET",
      /^\/fault-runs\/([^/]+)$/,
      (m) => {
        girisGerekli();
        // core `_adim_sozluk`: adımda katalog adı (`hata_adi`).
        const k = bul(decodeURIComponent(m[1]));
        return { ...k, adimlar: k.adimlar.map((a) => ({ ...a, hata_adi: katalogAdi(a.hata_kodu) })) };
      },
    ],
    [
      "POST",
      /^\/fault-runs\/([^/]+)\/cancel$/,
      (m) => {
        return iptal(decodeURIComponent(m[1]), izinGerekli(BASLATMA_IZNI));
      },
    ],
    // Ekilmiş hata adımlarının koşu kayıtları (kimlik `hk-<n>-r<sıra>`); diğer koşular handlers.ts'te.
    [
      "GET",
      /^\/runs\/(hk-\d+-r\d+)$/,
      (m) => {
        girisGerekli();
        return adimKosusu(m[1]);
      },
    ],
  ];
}
