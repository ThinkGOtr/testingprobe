// Tek tutarlı durum modeli (UX denetimi IA-03, IA-04, IA-06, IA-07). Saf işlevler; sayfalar ve testler ortak kullanır.
//
// Kök neden (IA-03/IA-04): gereksinim içeriği değişip `new`'e dönünce PO onay hash'i silinir; önceki içerik için
// üretilmiş (çoğu yayınlanmış) case'ler core'da `onceki_icerik: true` olur. Liste, case review sayaçları ve kapsam
// uyarıları bu ayrımı bilmediği için "Yeni · 1/14" ile "Onaylı 15", "Hazır değil 15" ile "✓ Hazır" aynı anda görünüyordu.
// Buradaki kural: sayaçlar yalnız GÜNCEL sürümü sayar; önceki sürüm ayrı bir kategori olarak üstte söylenir.
import type { Gereksinim, GereksinimDurumu, OncekiTur, Rol, SiradakiAdim, TestCase } from "../api/types";
import type { TasarimModeliKaydi } from "../api/tasarimModeliTipleri";
import { rolEtiketi } from "./yetki";

/** Core `requirements.serialize.SIRADAKI` aynası (core alan göndermezse; ör. eski core ya da örnek veri). */
const SIRADAKI: Record<GereksinimDurumu, [number, string, Rol | null]> = {
  new: [2, "Ön inceleme", "analyst"],
  in_review: [2, "Ön inceleme sürüyor", null],
  findings_open: [2, "Bulgu kararları", "analyst"],
  doc_final: [3, "PO onayına gönder", "analyst"],
  pending_po: [3, "PO teyidi", "po"],
  po_approved: [4, "Case üretimi", "tester"],
  modeling: [4, "Tasarım modeli üretiliyor", null],
  model_ready: [4, "Tasarım modeli kararı", "tester"],
  generating: [4, "Case üretimi sürüyor", null],
  cases_ready: [4, "Case kararı ve yayın", "tester"],
  done: [5, "Kod üretimi", "engineer"],
  failed: [2, "Başarısız işi yeniden dene", "analyst"],
};

/** Gereksinimin sıradaki adımı ve kimi beklediği (core alanı öncelikli). */
export function siradakiAdim(g: Pick<Gereksinim, "durum" | "ac_missing" | "siradaki">): SiradakiAdim {
  if (g.siradaki && g.siradaki.ad) return g.siradaki;
  const [adim_no, ad, rol] = SIRADAKI[g.durum] ?? [1, "Ön inceleme", "analyst"];
  return {
    adim_no,
    ad: g.durum === "new" && g.ac_missing ? "Kabul kriteri eksik · PO'ya sor" : ad,
    rol,
    rol_etiketi: rol ? rolEtiketi(rol) : "Sistem (otomatik)",
  };
}

/** "Ön inceleme · Analist" (sistem işinde yalnız adım adı). */
export function siradakiMetni(s: SiradakiAdim): string {
  return s.rol ? `${s.ad} · ${s.rol_etiketi}` : s.ad;
}

/** Güncel + önceki sürüm case sayısı (case review bağlantısı ve case okuma için; `sayaclar` yalnız güncel). */
export const tumCaseSayisi = (g: Pick<Gereksinim, "sayaclar" | "onceki_tur">): number => g.sayaclar.case_toplam + (g.onceki_tur?.case_toplam ?? 0);

/** Tur numarası (core yoksa 1). */
export const turNo = (g: Pick<Gereksinim, "tur">): number => (typeof g.tur === "number" && g.tur >= 1 ? g.tur : 1);

/** "Önceki tur: 15 case yayında, 8 PR birleşti" (ürün yoksa null). */
export function oncekiTurMetni(o: OncekiTur | null | undefined): string | null {
  if (!o || o.case_toplam === 0) return null;
  const parcalar = [o.case_yayinda > 0 ? `${o.case_yayinda} case yayında` : `${o.case_toplam} case`];
  if (o.case_yayinda > 0 && o.case_toplam > o.case_yayinda) parcalar.push(`${o.case_toplam - o.case_yayinda} case yayında değil`);
  if (o.pr_birlesen > 0) parcalar.push(`${o.pr_birlesen} PR birleşti`);
  return `Önceki tur: ${parcalar.join(", ")}`;
}

// ------------------------------------------------------------------ case review (IA-04)

export type CaseSurumu = "guncel" | "onceki";

/** Case gereksinimin önceki (PO onayı yenilenmemiş/değişmiş) içeriğine mi ait? */
export const oncekiSurumMu = (c: Pick<TestCase, "onceki_icerik">): boolean => c.onceki_icerik === true;

/** Geçersiz (`superseded`) case'ler hiçbir sürüm kümesinde sayılmaz. */
export function surumKumeleri<T extends Pick<TestCase, "onceki_icerik" | "durum">>(liste: readonly T[]): { guncel: T[]; onceki: T[] } {
  const etkin = liste.filter((c) => c.durum !== "superseded");
  return { guncel: etkin.filter((c) => !oncekiSurumMu(c)), onceki: etkin.filter(oncekiSurumMu) };
}

/** Varsayılan sürüm sekmesi: güncel case varsa güncel, yoksa (yalnız önceki varsa) önceki sürüm. */
export function varsayilanSurum(k: { guncel: readonly unknown[]; onceki: readonly unknown[] }): CaseSurumu {
  return k.guncel.length === 0 && k.onceki.length > 0 ? "onceki" : "guncel";
}

/**
 * Case review tepesindeki tek durum cümlesi: önceki sürüm case'i yoksa null. Sıradaki adım gereksinimin GERÇEK
 * durumundan söylenir (ör. `new` → ön inceleme, `pending_po` → PO teyidi, `po_approved` → yeni case üretimi).
 */
export function surumDurumCumlesi(
  _g: Pick<Gereksinim, "durum" | "ac_missing" | "siradaki"> | null | undefined,
  k: { guncel: readonly unknown[]; onceki: readonly unknown[] },
): string | null {
  const n = k.onceki.length;
  if (n === 0) return null;
  // YD-03: sıradaki adım burada tekrarlanmaz; özet kartının "Sıradaki adım" satırı aynı adımı (`siradakiAdim`) söyler.
  if (k.guncel.length === 0) {
    return `Bu ${n} case gereksinimin önceki sürümüne ait; içerik değişti ve PO teyidi yenilenmedi. Yeni sürüm için case'ler, ön inceleme ve PO teyidinden sonra üretilir.`;
  }
  return `${n} case gereksinimin önceki sürümüne ait ("Önceki sürüm" sekmesinde); sayaçlar ve kapsam yalnız güncel sürümün ${k.guncel.length} case'ini sayar.`;
}

// ------------------------------------------------------------- gereksinim detayı (IA-06, IA-07)

export interface ModelBayatligi {
  bayat: boolean;
  /** Tek satırlık durum özeti (bayatken); güncelken null. */
  ozet: string | null;
}

/**
 * Tasarım modeli bayat mı: eski içeriğe ait (`guncel: false`), geçersiz (`superseded`) ya da reddedilmiş ve gereksinim
 * model aşamasında değil. Bayat model sayfanın ana alanını kaplamaz; tek satırlık durum bilgisi olarak özetlenir.
 */
export function tasarimModeliBayat(
  g: Pick<Gereksinim, "durum">,
  m: Pick<TasarimModeliKaydi, "guncel" | "durum" | "surum"> | null | undefined,
): ModelBayatligi {
  if (!m) return { bayat: false, ozet: null };
  const asamada = g.durum === "modeling" || g.durum === "model_ready";
  const eski = m.guncel === false;
  const gecersiz = m.durum === "superseded";
  if (!eski && !gecersiz) return { bayat: false, ozet: null };
  if (asamada && !eski) return { bayat: false, ozet: null };
  const neden = eski ? "eski içeriğe ait" : "yenisi var (geçersiz)";
  const sonra = g.durum === "po_approved" || asamada ? "yeniden üretilmeli" : "PO teyidinden sonra yeniden üretilecek";
  return { bayat: true, ozet: `Tasarım modeli v${m.surum} · ${neden} · ${sonra}` };
}

/** dk/detay `lib/gereksinimSekmeleri.ts` ile aynı sekme anahtarları. */
export type GereksinimSekmeAnahtari = "dokuman" | "tasarim-modeli" | "caseler" | "po-teyidi" | "tutarlilik";

/**
 * Rolün işine göre varsayılan sekme. Adımın sahibi olan rol o adımın sekmesine düşer (Analist bulgu kararında
 * Tutarlılık, PO teyitte PO teyidi, Test Uzmanı case aşamasında Case'ler); adımın sahibi olmayan rol okuma
 * sekmesine (Doküman) düşer. Bayat tasarım modeli hiçbir zaman varsayılan değildir.
 */
export function varsayilanSekme(
  g: Pick<Gereksinim, "durum">,
  rol: Rol | string | null | undefined,
  bayat: boolean,
): GereksinimSekmeAnahtari {
  const d = g.durum;
  const adim: GereksinimSekmeAnahtari =
    d === "in_review" || d === "findings_open"
      ? "tutarlilik"
      : d === "doc_final" || d === "pending_po"
        ? "po-teyidi"
        : d === "modeling" || d === "model_ready"
          ? "tasarim-modeli"
          : d === "po_approved" || d === "generating" || d === "cases_ready" || d === "done"
            ? "caseler"
            : "dokuman";
  const sahip = SIRADAKI[d]?.[2] ?? null;
  // Sistem işinde (in_review, modeling, generating) sekme adımı izler; insan adımında sahibi olmayan rol okur.
  // PO teyidi ve case aşaması bilgi olarak herkesin işine yarar; yalnız bulgu kararı analistin kendi ekranıdır.
  const sonuc = sahip && rol && sahip !== rol && adim === "tutarlilik" ? "dokuman" : adim;
  return bayat && sonuc === "tasarim-modeli" ? "dokuman" : sonuc;
}

/** Bölüm/sekme sırası: karar verilecek olan üstte, sonra okuma, en sonda bayat model (IA-07). */
export function bolumSirasi(g: Pick<Gereksinim, "durum">, bayat: boolean): GereksinimSekmeAnahtari[] {
  const ilk = varsayilanSekme(g, null, bayat);
  const temel: GereksinimSekmeAnahtari[] = ["tutarlilik", "po-teyidi", "dokuman", "caseler", "tasarim-modeli"];
  const sira = [ilk, ...temel.filter((s) => s !== ilk)];
  return bayat ? [...sira.filter((s) => s !== "tasarim-modeli"), "tasarim-modeli"] : sira;
}
