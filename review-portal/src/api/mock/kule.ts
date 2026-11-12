// 012/Ş8 mock arka ucu: ekilmiş hata koşusu uçları (ANALIZ §4.6) ve Kule'nin iki kalite anahtarı (§4.7).
// Sözleşme gibi davranır: yalnız engineer/presenter başlatır ve iptal eder, süren koşu varken 409
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
  Rol,
} from "../types";
import { yakalamaOrani } from "../uyumKule";
import { mockOlayYayinla } from "./olaylar";
import { adimiSonuclandir, adimIskeleti, HATA_KATALOGU, ilkHataKosulari, KULE_KALITE_KAYNAKLARI, MOCK_BEKLENTI, PAKET_TESTLERI } from "./kuleVerisi";

const testModu = import.meta.env.MODE === "test";
/** Bir adımın süresi (ms). Testler değiştirebilir; `kuleMockSifirla` varsayılana döndürür. */
const VARSAYILAN_ADIM_MS = testModu ? 20 : 1400;
export const kuleAyar = { adimMs: VARSAYILAN_ADIM_MS };

const BASLATAN_ROLLER: Rol[] = ["engineer", "presenter"];
const HATA_KODU_KALIBI = /^[a-z0-9_]{1,40}$/;

let kosular: HataKosusuDetay[] = [];
let sayac = 1;
let zamanlayici: ReturnType<typeof setTimeout> | null = null;

const katalogAdi = (kod: string | null): string | null => (kod ? (HATA_KATALOGU.find((h) => h.kod === kod)?.ad ?? kod) : null);

/** core `ozet_hesapla`: platform başına sayılar + `bekleyen`, `temel`, `kapanis`; toplamda `bekleyen`. */
function ozetHesapla(k: HataKosusuDetay): HataKosusuOzeti {
  const platformlar: HataYakalamaPlatformu[] = k.platformlar.map((platform) => {
    const pa = k.adimlar.filter((a) => a.platform === platform);
    const { oran, yakalanan, kacan, gecersiz, bekleyen } = yakalamaOrani(pa);
    return {
      platform,
      oran,
      yakalanan,
      kacan,
      gecersiz,
      bekleyen,
      temel: pa.find((a) => a.asama === "temel")?.sonuc ?? null,
      kapanis: pa.find((a) => a.asama === "kapanis")?.sonuc ?? null,
    };
  });
  const { oran, yakalanan, kacan, gecersiz, bekleyen } = yakalamaOrani(k.adimlar);
  return {
    oran,
    yakalanan,
    kacan,
    gecersiz,
    bekleyen,
    platformlar,
    kacanlar: k.adimlar
      .filter((a) => a.asama === "hata" && a.sonuc === "kacti" && a.hata_kodu)
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
  if (secilen.length === 0 || secilen.some((p) => p === null)) throw new ApiError(422, "En az bir geçerli platform seçin (web, android, ios, windows).");
  // Platformlar sabit sırayla koşar (web → android → ios → windows), yinelenen değer bir kez.
  const platformlar = PLATFORMLAR.filter((p) => secilen.includes(p)) as Platform[];
  const katalog = HATA_KATALOGU.map((h) => h.kod);
  let hatalar = katalog;
  if (g.hatalar !== undefined && g.hatalar !== null) {
    if (!Array.isArray(g.hatalar) || g.hatalar.length === 0) throw new ApiError(422, "En az bir hata seçin.");
    const bilinmeyen = g.hatalar.filter((h) => typeof h !== "string" || !HATA_KODU_KALIBI.test(h) || !katalog.includes(h));
    if (bilinmeyen.length) throw new ApiError(422, `Katalogda olmayan hata kodu: ${bilinmeyen.join(", ")}`);
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

function iptal(id: string, kullanici: Kullanici): Pick<HataKosusu, "id" | "durum"> {
  const k = bul(id);
  // core `iptal`: bitmiş koşu (done | failed | cancelled) → 409 (WorkflowError, kod `cakisma`).
  if (k.durum !== "queued" && k.durum !== "running") throw new ApiError(409, `Koşu iptal edilemez (durum: ${k.durum}).`, { kod: "cakisma" });
  zamanlayiciyiTemizle();
  k.durum = "cancelled";
  k.bitis = new Date().toISOString();
  k.ozet = ozetHesapla(k);
  k.uyarilar.push(`${kullanici.kullanici_adi} tarafından iptal edildi.`);
  olay(k, null);
  return { id: k.id, durum: k.durum };
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
    const kiran = new Set(a.kiran_testler);
    const sonuclar: KosuDetay["sonuclar"] = PAKET_TESTLERI.map((test_adi, i) => ({
      id: `${runId}-${i + 1}`,
      test_adi,
      durum: kiran.has(test_adi) ? "failed" : "passed",
      sure_ms: 2900 + i * 350,
      retry: 0,
      hata_mesaji: kiran.has(test_adi) ? `Assertion: beklenen değer ekilmiş hata (${a.hata_kodu}) yüzünden tutmadı.` : null,
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

/** Kule yanıtına eklenen iki anahtar (§4.7): son BİTMİŞ koşudan; hiç bitmiş koşu yoksa `hata_yakalama: null`. */
export function kuleKaliteOlcumu(): Required<Pick<KontrolKulesi, "beklenti_dogrulugu" | "hata_yakalama">> {
  const son = kosular.find((k) => k.durum === "done");
  const o = son ? ozetHesapla(son) : null;
  return {
    beklenti_dogrulugu: { ...MOCK_BEKLENTI },
    // core `hata_yakalama_ozeti`: platformlar yalnız sayılar (bekleyen/temel/kapanış koşu özetinde kalır).
    hata_yakalama:
      son && o
        ? {
            son_kosu: { id: son.id, bitis: son.bitis, durum: son.durum },
            oran: o.oran,
            yakalanan: o.yakalanan,
            kacan: o.kacan,
            gecersiz: o.gecersiz,
            platformlar: o.platformlar.map(({ platform, oran, yakalanan, kacan, gecersiz }) => ({ platform, oran, yakalanan, kacan, gecersiz })),
            kacanlar: o.kacanlar,
          }
        : null,
  };
}

/** core `hata_yakalama_ozeti` kaynak metni (İstanbul saatiyle bitiş, platformlar, sayılar, oran). */
export function kuleKaliteKaynaklariMock(): { beklenti_dogrulugu: string; hata_yakalama: string } {
  const son = kosular.find((k) => k.durum === "done");
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
  const oranMetni = o.oran !== null ? `oran %${Math.round(o.oran * 100)}` : "oran ölçülmedi";
  return {
    beklenti_dogrulugu: KULE_KALITE_KAYNAKLARI.beklenti_dogrulugu,
    hata_yakalama:
      `Son tamamlanan ekilmiş hata koşusu (${tarih}; ${son.platformlar.join(", ")}): ` +
      `yakalanan ${o.yakalanan}, kaçan ${o.kacan}, geçersiz ${o.gecersiz}; ${oranMetni}. ` +
      "Oran = yakalanan / (yakalanan + kaçan); geçersiz adımlar paydaya girmez (hata_kosusu, hata_kosusu_adim).",
  };
}

type Rota = [string, RegExp, (m: RegExpMatchArray, q: URLSearchParams, govde: unknown) => unknown];

/** handlers.ts ROTALAR'ına eklenen uçlar. `/fault-runs/catalog`, `/fault-runs/{id}`'den önce eşleşmeli. */
export function kuleRotalari(girisGerekli: () => Kullanici, rolGerekli: (...roller: Rol[]) => Kullanici): Rota[] {
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
    ["POST", /^\/fault-runs$/, (_m, _q, g) => baslat(rolGerekli(...BASLATAN_ROLLER), g)],
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
        return iptal(decodeURIComponent(m[1]), rolGerekli(...BASLATAN_ROLLER));
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
