// Case kalite (011 P8 review, P9 Agent Probe denetimi) ve yayın engeli metinlerinin saf kuralları:
// ham istisna sınıfı ayıklama, "Yayınlanamaz: " öneki (K22) ve karar sonrası yönlendirme.
import type { CaseDenetimKaydi } from "../api/types";

/** Core yayın engeli öneki (K22). Core metinleri bu önekle gönderir; portal ikinci kez eklemez. */
export const YAYINLANAMAZ = "Yayınlanamaz: ";
const YAYINLANAMAZ_RE = /^\s*Yayınlanamaz\s*:\s*/i;

/** Engel metnini "Yayınlanamaz: …" biçimine getirir (önek zaten varsa dokunmaz). */
export function yayinlanamaz(metin: string): string {
  const t = metin.trim();
  return YAYINLANAMAZ_RE.test(t) ? t : `${YAYINLANAMAZ}${t}`;
}

/** Öneki atar (ör. "Yayınlanamaz: hazır değil" çipinin yanındaki neden metni öneki tekrarlamaz). */
export function yayinlanamazOnekiz(metin: string): string {
  return metin.replace(YAYINLANAMAZ_RE, "");
}

// Ham sınıf adı: en az iki büyük harfli parça (ReplayNoOutput, ReplayMiss, ReadTimeout) ya da
// Error/Exception ile biten ad (TimeoutError, HTTPError), isteğe bağlı modül önekiyle (httpx.ReadTimeout).
// Tek parçalı Türkçe sözcük ("Denetim:", "Yayınlanamaz:") eşleşmez.
const MODUL = String.raw`(?:[A-Za-z_]\w*\.)*`;
const SINIF = String.raw`${MODUL}(?:(?:[A-Z][a-z0-9]+){2,}|[A-Z][A-Za-z0-9]*(?:Error|Exception)|Error|Exception)`;
const SINIF_ONEKI = new RegExp(String.raw`(^|[\s(\[])${SINIF}\s*:\s*`, "g");
const SINIF_PARANTEZ = new RegExp(String.raw`\s*[(\[]\s*${SINIF}\s*[)\]]`, "g");
const SINIF_TEK = new RegExp(String.raw`(^|\s)${MODUL}(?:[A-Z][A-Za-z0-9]*(?:Error|Exception)|Replay(?:NoOutput|Miss))(?=$|[\s.,;])`, "g");

/**
 * Core/worker hata metninden ham istisna sınıf adını ayıklar ("ReplayNoOutput: …", "… (ReplayMiss)",
 * "TimeoutError: …"); anlamlı Türkçe metin kalır, ilk harf büyütülür. Boş kalırsa `bos` döner.
 */
export function hataMetniniAyikla(ham: string | null | undefined, bos = "Ayrıntı bildirilmedi."): string {
  let t = (ham ?? "").trim();
  for (let i = 0; i < 3; i++) {
    const once = t;
    t = t.replace(SINIF_ONEKI, "$1").replace(SINIF_PARANTEZ, "").replace(SINIF_TEK, "$1");
    if (t === once) break;
  }
  t = t
    .replace(/\(\s*\)|\[\s*\]/g, "")
    .replace(/\s{2,}/g, " ")
    .replace(/\s+([.,;:)])/g, "$1")
    .replace(/^[\s:;,.—–-]+/, "")
    .replace(/[\s:;,—–-]+$/, "")
    .trim();
  if (!t) return bos;
  return t.charAt(0).toLocaleUpperCase("tr-TR") + t.slice(1);
}

export type Yonlendirme = { tur: "yayin" | "duzelt" | "engelle" | "bayat"; metin: string };

/**
 * Agent Probe kararından sonra kullanıcıya sıradaki adım (UX-7). Yalnız tamamlanmış karar için;
 * karar setin güncel hâline ait değilse (bayat) önce yeniden gönderme söylenir.
 */
export function denetimYonlendirmesi(d: Pick<CaseDenetimKaydi, "durum" | "karar" | "guncel"> | null | undefined): Yonlendirme | null {
  if (!d || d.durum !== "tamamlandi" || !d.karar) return null;
  if (!d.guncel) return { tur: "bayat", metin: "Case'ler denetimden sonra değişti; yeniden gönderin." };
  if (d.karar === "KABUL") return { tur: "yayin", metin: "Yayına hazır:" };
  if (d.karar === "DÜZELTME_GEREKLİ") return { tur: "duzelt", metin: "Bulgulardaki case'leri düzeltin, sonra yeniden gönderin." };
  return { tur: "engelle", metin: "Set yayınlanamaz; bulgulardaki engelleri giderip yeniden üretin ya da gönderin." };
}

/** Denetim kapısı kapalıyken gösterilen metin (ortam değişkeni adı kullanıcıya gösterilmez). */
export const KAPI_KAPALI_METNI = "Denetim kapısı yönetici tarafından kapatıldı; yayın için denetim kararı aranmıyor.";
