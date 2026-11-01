// Faz 5 uyarlayıcıları: story başına manuel baz değer, Kontrol Kulesi hazırlık satırları ve
// `/demo/status` ekleri (model kipi, değerlendirme, kırma ön koşulu).
//
// Sözleşme (portalın varsaydığı; çekirdek şekli kesinleşince yalnızca burası değişir):
// - `GET /requirements/{id}` → `manuel_baz {deger_s, kaynak: olcum|varsayilan|olculmedi, giren, zaman, not}`
// - `PUT /requirements/{id}/baseline {deger_s, not}` (analyst | po) → `manuel_baz` (ya da gereksinim detayı)
// - `DELETE /requirements/{id}/baseline` (analyst | po) → kalan `manuel_baz` (varsayılan / ölçülmedi)
// - `GET /control-tower` → `hazirlik[{…, manuel_baz_ms, baz_kaynagi, kazanc_orani}]`
// Alan adları için kolon adları da kabul edilir (deger_ms, saniye, kaynak=measured|default …).
// Değer bilinmiyorsa `null` / `olculmedi` kalır: baz değer ve kazanç asla uydurulmaz.

import type {
  BazKaynagi,
  DemoDurumu,
  HazirlikSatiri,
  KontrolKulesi,
  ManuelBaz,
  ModelDurumu,
  PaketDegerlendirmesi,
} from "./types";
import { ilk, kimlik, metin, metinYaDaNull, nesneMi, sayiYaDaNull, type Ham } from "./uyum";

/** Baz değer üst sınırı (40 saat; core `BAZ_UST_SINIR_S`): portal formu ve mock arka uç aynı kuralı uygular. */
export const BAZ_UST_SINIR_S = 40 * 60 * 60;
export const BAZ_NOT_EN_AZ = 3;
export const BAZ_NOT_EN_COK = 500;

const OLCUM = new Set(["olcum", "ölçüm", "olculen", "measured", "manual", "manuel", "story", "elle"]);
const VARSAYILAN = new Set(["varsayilan", "varsayılan", "default", "env", "ortam", "global"]);

export function bazKaynagiUyarla(x: unknown): BazKaynagi {
  const k = metin(x).trim().toLowerCase();
  if (OLCUM.has(k)) return "olcum";
  if (VARSAYILAN.has(k)) return "varsayilan";
  return "olculmedi";
}

function saniye(o: Ham): number | null {
  const s = sayiYaDaNull(ilk(o, "deger_s", "saniye", "sure_s", "baseline_s"));
  if (s !== null) return s > 0 ? s : null;
  const ms = sayiYaDaNull(ilk(o, "deger_ms", "manuel_baz_ms", "sure_ms"));
  return ms !== null && ms > 0 ? ms / 1000 : null;
}

/** Gereksinim detayındaki baz değer nesnesi; alan hiç yoksa `undefined` (çekirdek sunmuyor). */
export function manuelBazUyarla(x: unknown): ManuelBaz | undefined {
  if (x === undefined) return undefined;
  if (!nesneMi(x)) return { deger_s: null, kaynak: "olculmedi", giren: null, zaman: null, not: null };
  const deger = saniye(x);
  // Değeri olmayan "ölçüm" ölçüm değildir.
  const kaynak = deger === null ? "olculmedi" : bazKaynagiUyarla(ilk(x, "kaynak", "source", "tur"));
  return {
    deger_s: kaynak === "olculmedi" ? null : deger,
    kaynak,
    giren: metinYaDaNull(ilk(x, "giren", "kaydeden", "kullanici", "kullanici_adi", "by")),
    zaman: metinYaDaNull(ilk(x, "zaman", "olcum_zamani", "guncelleme", "at")),
    not: metinYaDaNull(ilk(x, "not", "aciklama", "note")),
  };
}

/** Gereksinim gövdesinden baz değeri bulur (alan adları: manuel_baz | baseline | baz_deger). */
export function gereksinimBazi(g: Ham): ManuelBaz | undefined {
  return manuelBazUyarla(ilk(g, "manuel_baz", "baseline", "baz_deger", "manuel_baz_degeri"));
}

/** PUT/DELETE yanıtı: baz değer nesnesi ya da (içinde baz değer taşıyan) gereksinim detayı. */
export function bazYanitiUyarla(x: unknown): ManuelBaz | undefined {
  if (!nesneMi(x)) return undefined;
  const ic = gereksinimBazi(x);
  if (ic !== undefined) return ic;
  if ("kaynak" in x || "deger_s" in x || "deger_ms" in x) return manuelBazUyarla(x);
  return undefined;
}

export function hazirlikUyarla(x: unknown): HazirlikSatiri[] {
  if (!Array.isArray(x)) return [];
  return x.filter(nesneMi).map((h) => {
    const baz = sayiYaDaNull(ilk(h, "manuel_baz_ms", "baz_ms"));
    const kaynakHam = ilk(h, "baz_kaynagi", "manuel_baz_kaynagi");
    // Kaynak bildirilmeyen eski core'da baz değer ortam değişkenidir (TP_MANUAL_BASELINE_S):
    // story için ölçülmemiştir, kazanç hesaplanmaz.
    // Güncel core varsayılanda `manuel_baz_ms=null` gönderir (değer yalnız ikincil alanda): kaynak
    // yine "varsayilan" gösterilir, sayı gösterilmez ("ölçülmedi").
    const kaynak: BazKaynagi =
      kaynakHam === "varsayilan"
        ? "varsayilan"
        : baz === null || baz <= 0
          ? "olculmedi"
          : kaynakHam === undefined
            ? "varsayilan"
            : bazKaynagiUyarla(kaynakHam);
    return {
      requirement_id: kimlik(h.requirement_id),
      story_key: metinYaDaNull(ilk(h, "story_key", "jira_key")),
      ai_sure_ms: sayiYaDaNull(h.ai_sure_ms),
      review_sure_ms: sayiYaDaNull(h.review_sure_ms),
      toplam_ms: sayiYaDaNull(h.toplam_ms),
      ai_olculmedi: h.ai_olculmedi === true,
      review_olculmedi: h.review_olculmedi === true,
      manuel_baz_ms: kaynak === "olculmedi" || baz === null || baz <= 0 ? null : baz,
      baz_kaynagi: kaynak,
      kazanc_orani: sayiYaDaNull(h.kazanc_orani),
      ...(typeof h.kazanca_girer === "boolean" ? { kazanca_girer: h.kazanca_girer } : {}),
    };
  });
}

export interface StoryKazanci {
  satir: HazirlikSatiri;
  /** Kazançta kullanılan süre (AI + review; REPLAY'de yalnız review). */
  sure_ms: number | null;
  /** REPLAY: AI süresi ölçülmediği için süre yalnız review süresidir. */
  yalniz_review: boolean;
  kazanc: number | null;
}

export interface KazancOzeti {
  /** 1 − Σ süre / Σ ölçülmüş baz (yalnızca ölçülmüş baz değerli ve süresi ölçülmüş story'ler); yoksa null. */
  oran: number | null;
  /** Başlık kazancına giren story sayısı (ölçülmüş baz + AI + review; REPLAY yalnız-review hariç). */
  hesaplanan: number;
  /** Story oranı olan ama REPLAY'de yalnız review süresi bilinen (başlığa girmeyen) story sayısı. */
  replay_haric: number;
  /** Baz değeri ölçülmüş (olcum) story sayısı. */
  olculmus_baz: number;
  varsayilan_baz: number;
  baz_yok: number;
  toplam: number;
  storyler: StoryKazanci[];
  /** Kapsam metni (Kontrol Kulesi'nde kazancın altında). */
  kapsam: string;
}

/** Story süresi: core toplamı; yoksa REPLAY'de (AI ölçülmedi) yalnız review süresi (DEMO-VERISI). */
export function storySuresi(h: HazirlikSatiri): { ms: number | null; yalnizReview: boolean } {
  if (h.toplam_ms !== null) return { ms: h.toplam_ms, yalnizReview: h.ai_olculmedi };
  if (h.ai_olculmedi && h.review_sure_ms !== null && !h.review_olculmedi) return { ms: h.review_sure_ms, yalnizReview: true };
  return { ms: null, yalnizReview: false };
}

/**
 * Kazanç yalnızca baz değeri story için ölçülmüş satırlarda hesaplanır (varsayılan baz değer ya da
 * ölçülmemiş story kazanca girmez); kapsam metni kaç story'nin hesaba girdiğini söyler.
 */
export function kazancOzeti(hazirlik: HazirlikSatiri[]): KazancOzeti {
  const storyler: StoryKazanci[] = hazirlik.map((h) => {
    const s = storySuresi(h);
    const baz = h.baz_kaynagi === "olcum" ? h.manuel_baz_ms : null;
    // 0 ms hazırlık ölçüm değildir (core ile aynı kural).
    const kazanc = baz && baz > 0 && s.ms ? 1 - s.ms / baz : null;
    return { satir: h, sure_ms: s.ms, yalniz_review: s.yalnizReview, kazanc };
  });
  // Core `hazirlik[].kazanca_girer` ile aynı kural: REPLAY'de yalnız review süresi bilinen story'nin
  // oranı tabloda etiketli kalır ama başlık kazancına girmez (yüzde verimlilik iddiası değildir).
  const oranli = storyler.filter((s) => s.kazanc !== null);
  const hesaplanan = oranli.filter((s) => !s.yalniz_review && s.satir.kazanca_girer !== false);
  const replayHaric = oranli.length - hesaplanan.length;
  const olculmus = hazirlik.filter((h) => h.baz_kaynagi === "olcum").length;
  const varsayilan = hazirlik.filter((h) => h.baz_kaynagi === "varsayilan").length;
  const yok = hazirlik.length - olculmus - varsayilan;
  // Core `ai_katkisi.kazanc_orani` ile aynı formül: 1 − Σ(hazırlık süresi) / Σ(ölçülmüş baz).
  const bazToplam = hesaplanan.reduce((a, s) => a + (s.satir.manuel_baz_ms ?? 0), 0);
  const oran = hesaplanan.length && bazToplam > 0 ? 1 - hesaplanan.reduce((a, s) => a + (s.sure_ms ?? 0), 0) / bazToplam : null;
  const adlar = hesaplanan.map((s) => s.satir.story_key ?? "serbest metin").join(", ");
  const disarida: string[] = [];
  if (varsayilan) disarida.push(`${varsayilan} story varsayılan baz değerli (story için ölçülmedi)`);
  if (yok) disarida.push(`${yok} story'de baz değer yok`);
  const sureYok = olculmus - oranli.length;
  if (sureYok > 0) disarida.push(`${sureYok} story'de hazırlık süresi ölçülmedi`);
  if (replayHaric > 0) disarida.push(`${replayHaric} story REPLAY'de yalnız review süresiyle (AI süresi ölçülmedi; yüzde verimlilik iddiası değildir)`);
  const kapsam =
    hazirlik.length === 0
      ? "Henüz case üretilmiş story yok; kazanç hesaplanmaz."
      : hesaplanan.length === 0 && replayHaric > 0
        ? `Kazanç hesaplanmaz (REPLAY): ölçülmüş baz değerli story'lerde AI süresi ölçülmedi, süre yalnız review süresidir; story oranı tabloda etiketli, sunumda yüzde verimlilik iddiası değildir (${disarida.join("; ")}).`
        : hesaplanan.length === 0
        ? `Kazanç hesaplanmaz: ${hazirlik.length} story'den hiçbirinde ölçülmüş baz değer ve süre birlikte yok${disarida.length ? ` (${disarida.join("; ")})` : ""}.`
        : `Kazanç yalnızca ölçülmüş baz değerli ${hesaplanan.length}/${hazirlik.length} story'den (${adlar})${disarida.length ? `; hesaba katılmayan: ${disarida.join("; ")}` : ""}.`;
  return { oran, hesaplanan: hesaplanan.length, replay_haric: replayHaric, olculmus_baz: olculmus, varsayilan_baz: varsayilan, baz_yok: yok, toplam: hazirlik.length, storyler, kapsam };
}

// ------------------------------------------------------------------ /demo/status ekleri

const DEGERLENDIRME_DURUMLARI = new Set(["pending", "evaluated", "waived", "stale", "missing"]);

function modelUyarla(x: unknown): ModelDurumu | null {
  if (!nesneMi(x)) return null;
  const strict = ilk(x, "replay_strict", "strict", "kati");
  return {
    mod: metinYaDaNull(ilk(x, "mod", "mode", "etkin_mod")),
    replay_strict: typeof strict === "boolean" ? strict : strict === 1 || strict === "1" ? true : strict === 0 || strict === "0" ? false : null,
    anahtar_var: typeof x.anahtar_var === "boolean" ? x.anahtar_var : null,
    aciklama: metinYaDaNull(ilk(x, "aciklama", "neden")),
  };
}

function degerlendirmeListesi(x: unknown): PaketDegerlendirmesi[] | null {
  const liste = Array.isArray(x) ? x : nesneMi(x) && Array.isArray(x.paketler) ? x.paketler : null;
  if (!liste) return null;
  return liste.filter(nesneMi).map((p) => {
    const d = metin(ilk(p, "durum", "status"));
    return {
      paket: metin(ilk(p, "paket", "bundle_id", "ad")),
      surum: sayiYaDaNull(ilk(p, "surum", "version", "prompt_version")),
      durum: (DEGERLENDIRME_DURUMLARI.has(d) ? d : "missing") as PaketDegerlendirmesi["durum"],
      etiket: metinYaDaNull(ilk(p, "etiket", "label")),
    };
  });
}

/** `/demo/status`: bilinen alanlar aynen, Faz 5 ekleri (model, değerlendirme) normalize edilir. */
export function demoDurumuUyarla(x: unknown): DemoDurumu {
  const d: Ham = nesneMi(x) ? x : {};
  const on = nesneMi(d.onarim_on_kosulu) ? d.onarim_on_kosulu : null;
  const sy = on && nesneMi(on.son_yesil_kosu) ? on.son_yesil_kosu : null;
  const ld = nesneMi(d.locator_demo) ? d.locator_demo : null;
  return {
    ...(d as unknown as DemoDurumu),
    forge: nesneMi(d.forge) ? (d.forge as DemoDurumu["forge"]) : {},
    uygulama: nesneMi(d.uygulama) ? (d.uygulama as DemoDurumu["uygulama"]) : {},
    web_yenileme_istegi: d.web_yenileme_istegi ?? null,
    locator_demo: ld ? { destekleniyor: ld.destekleniyor !== false, neden: metinYaDaNull(ld.neden) } : null,
    onarim_on_kosulu: on
      ? {
          hazir: typeof on.hazir === "boolean" ? on.hazir : null,
          son_yesil_kosu: sy
            ? { run_id: kimlik(sy.run_id), commit: metinYaDaNull(sy.commit), tetik: metinYaDaNull(sy.tetik), zaman: metinYaDaNull(sy.zaman) }
            : null,
          yonerge: metinYaDaNull(on.yonerge),
          hata: metinYaDaNull(on.hata),
        }
      : null,
    model: modelUyarla(ilk(d, "model", "model_kipi")),
    degerlendirme: degerlendirmeListesi(ilk(d, "degerlendirme", "degerlendirmeler")),
  };
}

/** Kontrol Kulesi gövdesinden hazırlık satırları (adaptör dışından da kullanılır). */
export function kuleHazirlik(govde: unknown): KontrolKulesi["hazirlik"] {
  return nesneMi(govde) ? hazirlikUyarla(govde.hazirlik) : [];
}
