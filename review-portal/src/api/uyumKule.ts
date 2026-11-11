// 012/Ş8: ekilmiş hata koşusu ve Kule kalite KPI'ları için uyarlayıcılar (ANALIZ §4.6, §4.7, §5).
// Kural: core'un vermediği değer uydurulmaz — eksik anahtar `undefined` (çekirdek sunmuyor), `null`
// "ölçülmedi"dir; sayı olmayan oran null kalır (0 yazılmaz).
import { platformUyarla, type Platform } from "../lib/platform";
import type {
  HataAdimAsamasi,
  HataAdimSonucu,
  HataKatalogOgesi,
  HataKosusu,
  HataKosusuAdimi,
  HataKosusuDetay,
  HataKosusuDurumu,
  HataKosusuOzeti,
  HataYakalamaPlatformu,
  KacanHata,
  KontrolKulesi,
  Kosu,
  KuleBeklentiDogrulugu,
  KuleHataYakalama,
} from "./types";
import { dizgeler, ilk, kimlik, metin, metinYaDaNull, nesneMi, sayi, sayiYaDaNull, type Ham } from "./uyum";

const nesne = (x: unknown): Ham => (nesneMi(x) ? x : {});
const dizi = (x: unknown): Ham[] => (Array.isArray(x) ? x.filter(nesneMi) : []);

const DURUMLAR = new Set<string>(["queued", "running", "done", "failed", "cancelled"]);
const ASAMALAR = new Set<string>(["temel", "hata", "kapanis"]);
const SONUCLAR = new Set<string>(["bekliyor", "yakalandi", "kacti", "gecersiz", "yesil", "kirmizi"]);

export const HATA_KOSUSU_SUREN: readonly HataKosusuDurumu[] = ["queued", "running"];

export function hataKosusuSuruyorMu(k: Pick<HataKosusu, "durum"> | null | undefined): boolean {
  return !!k && HATA_KOSUSU_SUREN.includes(k.durum);
}

function platformlar(x: unknown): Platform[] {
  return (Array.isArray(x) ? x : []).map(platformUyarla).filter((p): p is Platform => p !== null);
}

/** Oran: sayı değilse null. Sayaçlar verilmişse oran onlardan doğrulanmaz; core'un değeri aynen. */
function oran(x: unknown): number | null {
  const o = sayiYaDaNull(x);
  return o !== null && Number.isFinite(o) ? o : null;
}

function platformOzetiUyarla(x: Ham): HataYakalamaPlatformu | null {
  const p = platformUyarla(x.platform);
  if (!p) return null;
  return { platform: p, oran: oran(x.oran), yakalanan: sayi(x.yakalanan), kacan: sayi(x.kacan), gecersiz: sayi(x.gecersiz) };
}

function kacanUyarla(x: Ham): KacanHata | null {
  const p = platformUyarla(x.platform);
  const kod = metin(ilk(x, "hata_kodu", "kod"));
  if (!p || !kod) return null;
  return { hata_kodu: kod, ad: metin(x.ad, kod), platform: p };
}

const dolu = <T,>(x: T | null): x is T => x !== null;

function ozetUyarla(x: unknown): HataKosusuOzeti | null {
  if (!nesneMi(x)) return null;
  return {
    oran: oran(x.oran),
    yakalanan: sayi(x.yakalanan),
    kacan: sayi(x.kacan),
    gecersiz: sayi(x.gecersiz),
    platformlar: dizi(x.platformlar).map(platformOzetiUyarla).filter(dolu),
    kacanlar: dizi(x.kacanlar).map(kacanUyarla).filter(dolu),
  };
}

export function hataKatalogOgesiUyarla(x: Ham): HataKatalogOgesi {
  const kod = metin(ilk(x, "kod", "hata_kodu"));
  return {
    kod,
    ad: metin(x.ad, kod),
    tur: x.tur === "veri" ? "veri" : "kod",
    aciklama: metin(ilk(x, "aciklama", "etki")),
    yakalayan_kural: metinYaDaNull(ilk(x, "yakalayan_kural", "beklenen_kural")),
  };
}

/** Katalog yanıtı: dizi ya da `{hatalar | items: [...]}`. */
export function hataKataloguUyarla(govde: unknown): HataKatalogOgesi[] {
  const liste = Array.isArray(govde) ? govde : nesneMi(govde) ? [govde.hatalar, govde.items, govde.katalog].find(Array.isArray) : null;
  if (!Array.isArray(liste)) throw new Error("Beklenmeyen katalog yanıtı");
  return liste.filter(nesneMi).map(hataKatalogOgesiUyarla).filter((h) => h.kod);
}

export function hataKosusuAdimiUyarla(x: Ham, i = 0): HataKosusuAdimi | null {
  const p = platformUyarla(x.platform);
  if (!p) return null;
  const asama = metin(x.asama);
  const sonuc = metin(x.sonuc, "bekliyor");
  return {
    id: kimlik(x.id) || `${p}-${i}`,
    platform: p,
    hata_kodu: metinYaDaNull(x.hata_kodu),
    asama: (ASAMALAR.has(asama) ? asama : x.hata_kodu ? "hata" : "temel") as HataAdimAsamasi,
    run_id: metinYaDaNull(kimlik(x.run_id)),
    sonuc: (SONUCLAR.has(sonuc) ? sonuc : "bekliyor") as HataAdimSonucu,
    kiran_testler: dizgeler(x.kiran_testler),
    neden: metinYaDaNull(x.neden),
    sure_ms: sayiYaDaNull(x.sure_ms),
    sira: sayi(x.sira, i),
  };
}

export function hataKosusuUyarla(x: Ham): HataKosusu {
  const durum = metin(x.durum, "queued");
  return {
    id: kimlik(x.id),
    // Tanınmayan durum "tamamlanamadı" sayılır (süren ya da bitmiş diye uydurulmaz).
    durum: (DURUMLAR.has(durum) ? durum : "failed") as HataKosusuDurumu,
    platformlar: platformlar(x.platformlar),
    hatalar: dizgeler(x.hatalar),
    commit: metinYaDaNull(x.commit),
    baslatan_id: metinYaDaNull(kimlik(x.baslatan_id)),
    baslatan: metinYaDaNull(ilk(x, "baslatan", "baslatan_adi", "baslatan_kullanici")),
    ozet: ozetUyarla(x.ozet),
    uyarilar: dizgeler(x.uyarilar),
    baslama: metinYaDaNull(x.baslama),
    bitis: metinYaDaNull(x.bitis),
    olusturma: metin(ilk(x, "olusturma", "baslama")),
  };
}

export function hataKosusuDetayUyarla(x: Ham): HataKosusuDetay {
  return {
    ...hataKosusuUyarla(x),
    adimlar: dizi(x.adimlar)
      .map((a, i) => hataKosusuAdimiUyarla(a, i))
      .filter(dolu)
      .sort((a, b) => a.sira - b.sira),
  };
}

/** `POST /fault-runs` (202) yanıtından koşu kimliği: koşunun kendisi, `{kosu: {...}}` ya da `{hata_kosusu_id}`. */
export function hataKosusuKimligi(govde: unknown): string | null {
  const g = nesne(govde);
  return metinYaDaNull(kimlik(ilk(g, "id", "hata_kosusu_id", "kosu_id") ?? nesne(g.kosu).id));
}

function beklentiUyarla(x: Ham): KuleBeklentiDogrulugu {
  return {
    oran: oran(x.oran),
    uyumlu: sayi(x.uyumlu),
    uyumsuz: sayi(x.uyumsuz),
    kapsam_disi: sayi(x.kapsam_disi),
    kontrol_edilemedi: sayi(x.kontrol_edilemedi),
    istisna: sayi(x.istisna),
    kapsam_orani: oran(x.kapsam_orani),
  };
}

function hataYakalamaUyarla(x: Ham): KuleHataYakalama | null {
  const sk = nesne(x.son_kosu);
  const id = kimlik(sk.id);
  // Son koşusu olmayan ölçüm yoktur (§4.7 "koşu yoksa null").
  if (!id) return null;
  const durum = metin(sk.durum, "done");
  return {
    son_kosu: { id, bitis: metinYaDaNull(sk.bitis), durum: (DURUMLAR.has(durum) ? durum : "failed") as HataKosusuDurumu },
    oran: oran(x.oran),
    yakalanan: sayi(x.yakalanan),
    kacan: sayi(x.kacan),
    gecersiz: sayi(x.gecersiz),
    platformlar: dizi(x.platformlar).map(platformOzetiUyarla).filter(dolu),
    kacanlar: dizi(x.kacanlar).map(kacanUyarla).filter(dolu),
  };
}

/**
 * Kule yanıtının iki kalite anahtarı (§4.7). Anahtar yanıtta yoksa (eski core) sonuçta da yoktur
 * (`undefined` → karo "ölçülmedi", sıfır yazılmaz); `null` aynen null kalır.
 */
export function kuleKaliteUyarla(g: Ham): Pick<KontrolKulesi, "beklenti_dogrulugu" | "hata_yakalama"> {
  const sonuc: Pick<KontrolKulesi, "beklenti_dogrulugu" | "hata_yakalama"> = {};
  if ("beklenti_dogrulugu" in g) sonuc.beklenti_dogrulugu = nesneMi(g.beklenti_dogrulugu) ? beklentiUyarla(g.beklenti_dogrulugu) : null;
  if ("hata_yakalama" in g) sonuc.hata_yakalama = nesneMi(g.hata_yakalama) ? hataYakalamaUyarla(g.hata_yakalama) : null;
  return sonuc;
}

/** Koşunun ekilmiş hata alanları (core `run.ortam.hata_kodu` / `ortam.hata_kosusu_id`, V6); yoksa alan eklenmez. */
export function kosuHataAlanlari(k: Ham, ortam: Ham): Pick<Kosu, "hata_kodu" | "hata_kosusu_id"> {
  const kod = metinYaDaNull(ilk(k, "hata_kodu") ?? ortam.hata_kodu);
  const kosu = metinYaDaNull(kimlik(ilk(k, "hata_kosusu_id") ?? ortam.hata_kosusu_id));
  return { ...(kod ? { hata_kodu: kod } : {}), ...(kosu ? { hata_kosusu_id: kosu } : {}) };
}

/**
 * Oran `yakalanan / (yakalanan + kacan)`; `gecersiz` paydaya girmez (§4.6). Portal adımlardan aynı
 * formülle hesaplar (özet yokken, süren koşuda); payda 0 ise null.
 */
export function yakalamaOrani(adimlar: readonly Pick<HataKosusuAdimi, "asama" | "sonuc">[]): {
  oran: number | null;
  yakalanan: number;
  kacan: number;
  gecersiz: number;
  bekleyen: number;
} {
  const h = adimlar.filter((a) => a.asama === "hata");
  const yakalanan = h.filter((a) => a.sonuc === "yakalandi").length;
  const kacan = h.filter((a) => a.sonuc === "kacti").length;
  return {
    oran: yakalanan + kacan > 0 ? yakalanan / (yakalanan + kacan) : null,
    yakalanan,
    kacan,
    gecersiz: h.filter((a) => a.sonuc === "gecersiz").length,
    bekleyen: h.filter((a) => a.sonuc === "bekliyor").length,
  };
}
