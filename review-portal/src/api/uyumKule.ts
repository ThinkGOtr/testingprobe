// 012/Ş8: ekilmiş hata koşusu ve Kule kalite KPI'ları için uyarlayıcılar (ANALIZ §4.6, §4.7, §5).
// Kural: core'un vermediği değer uydurulmaz — eksik anahtar `undefined` (çekirdek sunmuyor), `null`
// "ölçülmedi"dir; sayı olmayan oran null kalır (0 yazılmaz).
import { platformUyarla, type Platform } from "../lib/platform";
import type {
  AyirtEdiciOrnek,
  ElYazisiYakalama,
  HataAdimAsamasi,
  HataAdimSonucu,
  HataKatalogOgesi,
  HataKosusu,
  HataKosusuAdimi,
  HataKosusuDetay,
  HataKosusuDurumu,
  HataKosusuKapsami,
  HataKosusuOzeti,
  HataYakalamaPlatformu,
  KacanHata,
  KiranTest,
  KontrolKulesi,
  Kosu,
  KuleBeklentiDogrulugu,
  KuleHataYakalama,
  OnayliUyumsuzCase,
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

/** §13.2 `el_yazisi`; nesne değilse alan eklenmez (eski çekirdek). */
function elYazisiUyarla(x: unknown): { el_yazisi?: ElYazisiYakalama } {
  if (!nesneMi(x)) return {};
  return { el_yazisi: { oran: oran(x.oran), yakalanan: sayi(x.yakalanan), kacan: sayi(x.kacan) } };
}

/** R4 `tum_testler` (AI + el yazısı); nesne değilse alan eklenmez. */
function tumTestlerUyarla(x: unknown): { tum_testler?: ElYazisiYakalama } {
  const e = elYazisiUyarla(x).el_yazisi;
  return e ? { tum_testler: e } : {};
}

function kapsamUyarla(x: unknown): { kapsam?: HataKosusuKapsami } {
  if (!nesneMi(x)) return {};
  return {
    kapsam: {
      kosulan_hata: sayi(x.kosulan_hata),
      katalog: sayi(x.katalog),
      platformlar: platformlar(x.platformlar),
      ...(typeof x.tam_katalog === "boolean" ? { tam_katalog: x.tam_katalog } : {}),
      ...(typeof x.gecerli_adim === "number" ? { gecerli_adim: sayi(x.gecerli_adim) } : {}),
    },
  };
}

const adimSonucu = (x: unknown): HataAdimSonucu | null => (typeof x === "string" && SONUCLAR.has(x) ? (x as HataAdimSonucu) : null);

function platformOzetiUyarla(x: Ham): HataYakalamaPlatformu | null {
  const p = platformUyarla(x.platform);
  if (!p) return null;
  return {
    platform: p,
    oran: oran(x.oran),
    yakalanan: sayi(x.yakalanan),
    kacan: sayi(x.kacan),
    gecersiz: sayi(x.gecersiz),
    ...elYazisiUyarla(x.el_yazisi),
    ...tumTestlerUyarla(x.tum_testler),
    ...(typeof x.uretilen_test === "number" ? { uretilen_test: sayi(x.uretilen_test) } : {}),
    ...(typeof x.el_test === "number" ? { el_test: sayi(x.el_test) } : {}),
    // Koşu özetinin ek alanları (core `ozet_hesapla`); Kule ölçüsü bunları vermez → alan eklenmez.
    ...("bekleyen" in x ? { bekleyen: sayi(x.bekleyen) } : {}),
    ...("temel" in x ? { temel: adimSonucu(x.temel) } : {}),
    ...("kapanis" in x ? { kapanis: adimSonucu(x.kapanis) } : {}),
  };
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
    ...("bekleyen" in x ? { bekleyen: sayi(x.bekleyen) } : {}),
    platformlar: dizi(x.platformlar).map(platformOzetiUyarla).filter(dolu),
    kacanlar: dizi(x.kacanlar).map(kacanUyarla).filter(dolu),
    ...elYazisiUyarla(x.el_yazisi),
    ...tumTestlerUyarla(x.tum_testler),
    ...kapsamUyarla(x.kapsam),
  };
}

/** "adet = 14" biçimi: nesne → "ad = değer" listesi; metin/sayı aynen; boşsa "". */
function ornekMetni(x: unknown): string {
  if (typeof x === "string") return x;
  if (typeof x === "number" || typeof x === "boolean") return String(x);
  if (nesneMi(x))
    return Object.entries(x)
      .map(([k, v]) => `${k} = ${typeof v === "boolean" ? (v ? "doğru" : "yanlış") : typeof v === "object" ? JSON.stringify(v) : String(v)}`)
      .join(", ");
  return "";
}

function ayirtEdiciUyarla(x: unknown): AyirtEdiciOrnek | null {
  if (!nesneMi(x)) return null;
  const o = { girdi: ornekMetni(x.girdi), dogru: ornekMetni(x.dogru), hatali: ornekMetni(x.hatali) };
  return o.girdi ? o : null;
}

export function hataKatalogOgesiUyarla(x: Ham): HataKatalogOgesi {
  const kod = metin(ilk(x, "kod", "hata_kodu"));
  return {
    kod,
    ad: metin(x.ad, kod),
    tur: x.tur === "veri" ? "veri" : "kod",
    aciklama: metin(ilk(x, "aciklama", "etki")),
    yakalayan_kural: metinYaDaNull(ilk(x, "yakalayan_kural", "beklenen_kural")),
    // K9 ekleri: anahtar yoksa alan eklenmez.
    ...("ac_refs" in x ? { ac_refs: dizgeler(x.ac_refs) } : {}),
    ...("tablo" in x ? { tablo: metinYaDaNull(x.tablo) } : {}),
    ...("ayirt_edici" in x ? { ayirt_edici: ayirtEdiciUyarla(x.ayirt_edici) } : {}),
    ...("requirement_id" in x ? { requirement_id: metinYaDaNull(kimlik(x.requirement_id)) } : {}),
  };
}

/** `kiran_testler`: `[{test, kaynak}]` (§13.2) ya da eski `[ad]` (kaynak bilinmiyor → null). */
export function kiranTestlerUyarla(x: unknown): KiranTest[] {
  return (Array.isArray(x) ? x : []).flatMap((t): KiranTest[] => {
    if (typeof t === "string") return t ? [{ test: t, kaynak: null }] : [];
    if (!nesneMi(t)) return [];
    const test = metin(ilk(t, "test", "ad", "test_adi"));
    const k = t.kaynak;
    return test ? [{ test, kaynak: k === "ai" || k === "el" ? k : null }] : [];
  });
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
    kiran_testler: kiranTestlerUyarla(x.kiran_testler),
    ...("temelde_kirmizi" in x ? { temelde_kirmizi: dizgeler(x.temelde_kirmizi) } : {}),
    neden: metinYaDaNull(x.neden),
    sure_ms: sayiYaDaNull(x.sure_ms),
    sira: sayi(x.sira, i),
    hata_adi: metinYaDaNull(x.hata_adi),
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
    ...(typeof x.iptal_istendi === "boolean" ? { iptal_istendi: x.iptal_istendi } : {}),
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
    // §13.2 ekleri: anahtar yoksa alan eklenmez (sayı uydurulmaz).
    ...Object.fromEntries(
      (["kismen", "kontrolsuz_onay", "n_case", "n_story", "tablolu_story", "toplam_story", "golden_kaynakli", "tekrar"] as const)
        .filter((a) => typeof x[a] === "number" && Number.isFinite(x[a]))
        .map((a) => [a, x[a] as number]),
    ),
  };
}

function onayliUyumsuzUyarla(x: unknown): OnayliUyumsuzCase[] {
  return dizi(x).flatMap((c) => {
    const case_id = kimlik(ilk(c, "case_id", "id"));
    return case_id ? [{ case_id, requirement_id: kimlik(c.requirement_id), baslik: metin(ilk(c, "baslik", "title"), case_id) }] : [];
  });
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
    ...elYazisiUyarla(x.el_yazisi),
    ...tumTestlerUyarla(x.tum_testler),
    ...kapsamUyarla(x.kapsam),
  };
}

/**
 * İki kalite ölçüsünün kaynak metni: core bunu `kaynaklar[<anahtar>]`'a yazar; değerin içinde `kaynak`
 * alanı gelirse (ör. `/requirements/{id}/case-metrics` biçimi) yalnız `kaynaklar`'da yoksa o kullanılır.
 */
export function kuleKaliteKaynaklari<T extends Partial<Record<"beklenti_dogrulugu" | "hata_yakalama", string>>>(g: Ham, kaynaklar: T): T {
  const sonuc: T = { ...kaynaklar };
  for (const a of ["beklenti_dogrulugu", "hata_yakalama"] as const) {
    const ic = nesneMi(g[a]) ? metinYaDaNull(g[a].kaynak) : null;
    if (!sonuc[a] && ic) sonuc[a] = ic;
  }
  return sonuc;
}

/**
 * Kule yanıtının iki kalite anahtarı (§4.7). Anahtar yanıtta yoksa (eski core) sonuçta da yoktur
 * (`undefined` → karo "ölçülmedi", sıfır yazılmaz); `null` aynen null kalır.
 */
export function kuleKaliteUyarla(g: Ham): Pick<KontrolKulesi, "beklenti_dogrulugu" | "hata_yakalama" | "onayli_uyumsuz"> {
  const sonuc: Pick<KontrolKulesi, "beklenti_dogrulugu" | "hata_yakalama" | "onayli_uyumsuz"> = {};
  if (Array.isArray(g.onayli_uyumsuz)) sonuc.onayli_uyumsuz = onayliUyumsuzUyarla(g.onayli_uyumsuz);
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

/**
 * K12 (§13.1): bir kaynağın (AI ya da el yazısı) testleriyle yakalama. Adım, o kaynaktan en az bir test
 * kırmızıya döndüyse "yakalandı" sayılır; geçerli (yakalandı | kaçtı) diğer adımlar o kaynak için "kaçtı".
 * `olculdu: false`: adımlarda bu kaynağın hiçbir testi görünmüyor (ör. üretilmiş test yok) — oran null.
 */
export function kaynakOrani(
  adimlar: readonly Pick<HataKosusuAdimi, "asama" | "sonuc" | "kiran_testler">[],
  kaynak: "ai" | "el",
): { oran: number | null; yakalanan: number; kacan: number; olculdu: boolean } {
  const gecerli = adimlar.filter((a) => a.asama === "hata" && (a.sonuc === "yakalandi" || a.sonuc === "kacti"));
  const yakalanan = gecerli.filter((a) => a.sonuc === "yakalandi" && a.kiran_testler.some((t) => t.kaynak === kaynak)).length;
  const kacan = gecerli.length - yakalanan;
  const olculdu = adimlar.some((a) => a.kiran_testler.some((t) => t.kaynak === kaynak));
  return { oran: olculdu && gecerli.length > 0 ? yakalanan / gecerli.length : null, yakalanan, kacan, olculdu };
}

/** Adımların kıran testlerinde kaynak bilgisi var mı (§13.2 biçimi); yoksa eski çekirdek → ayrım çizilmez. */
export function kaynakBilgisiVar(adimlar: readonly Pick<HataKosusuAdimi, "kiran_testler">[]): boolean {
  return adimlar.some((a) => a.kiran_testler.some((t) => t.kaynak !== null));
}
