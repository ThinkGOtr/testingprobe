// IA-13 (UX denetimi, iş akışı): Kod üretimi listesinde dikkat gereken script'lerin tek satırlık nedeni
// ve nedene uygun eylem. Neden core liste yanıtında zaten var (`engel: {tur, neden}`, `yerel_sinif`,
// `mode`, `failure_id`); burada yalnız kullanıcı diline çevrilir ve gruplanır.
import type { Script } from "../api/types";
import { ENGEL_TURU } from "./kapi";

export type ScriptGrubu = "dikkat" | "suren" | "birlesen";

export interface DikkatNedeni {
  /** Kısa başlık: "İnsana düştü: Page object'te eksik metot". */
  metin: string;
  /** Çekirdeğin ayrıntılı nedeninin ilk cümlesi (yoksa null). */
  ayrinti: string | null;
  /** Önerilen eylem: bağlantı (rota) ya da satırdaki "Yeniden üret" düğmesi. */
  eylem: { tur: "baglanti"; etiket: string; yol: string } | { tur: "yeniden_uret"; etiket: string } | null;
}

const defectMi = (s: Pick<Script, "yerel_sinif" | "engel">) => s.yerel_sinif === "defect_adayi" || s.engel?.tur === "defect_candidate";

/** Ayrıntılı nedenin ilk cümlesi (en çok 140 karakter). */
export function ilkCumle(metin: string | null | undefined): string | null {
  const m = (metin ?? "").trim();
  if (!m) return null;
  const nokta = m.search(/[.!?](\s|$)/);
  const ilk = nokta > 0 ? m.slice(0, nokta + 1) : m;
  return ilk.length > 140 ? `${ilk.slice(0, 139)}…` : ilk;
}

/** Script dikkat ister mi: insana düştü, başarısız, defect adayı, REPLAY-MISS, doğrulanmamış ya da veri değişti. */
export function dikkatNedeni(s: Script, veriDegisti = false): DikkatNedeni | null {
  const scriptYolu = `/kod/${encodeURIComponent(s.id)}`;
  if (defectMi(s)) {
    return {
      metin: "Defect adayı: test, onaylı case'in beklenen değerinde kırmızı (hata büyük olasılıkla üründe)",
      ayrinti: ilkCumle(s.engel?.neden),
      eylem: s.failure_id
        ? { tur: "baglanti", etiket: "Triage sonucunu aç", yol: `/hatalar/${encodeURIComponent(s.failure_id)}` }
        : { tur: "baglanti", etiket: "Script'i aç", yol: scriptYolu },
    };
  }
  if (s.durum === "blocked" || s.durum === "failed") {
    const tur = s.engel?.tur ?? (s.mode === "replay_miss" ? "replay_miss" : null);
    const ad = tur ? (ENGEL_TURU[tur] ?? "Neden sınıflandırılmadı") : "Neden kaydedilmedi";
    const onEk = s.durum === "blocked" ? "İnsana düştü" : "Üretim başarısız";
    // Ortam ve REPLAY-MISS: kod tarafında düzeltilecek bir şey yok, yeniden üretim doğru eylemdir.
    const yenidenUret = tur === "environment" || tur === "replay_miss" || tur === "agent_error" || tur === "flaky";
    return {
      metin: `${onEk}: ${tur === "replay_miss" ? "kayıtlı model çıktısı yok, canlı model gerekir" : ad.charAt(0).toLocaleLowerCase("tr-TR") + ad.slice(1)}`,
      ayrinti: ilkCumle(s.engel?.neden ?? s.hata),
      eylem: yenidenUret
        ? { tur: "yeniden_uret", etiket: "Yeniden üret" }
        : tur === "missing_method" || tur === "unknown_method"
          ? { tur: "baglanti", etiket: "Page object'e metot ekle (script'i aç)", yol: scriptYolu }
          : { tur: "baglanti", etiket: "Nedeni incele (script'i aç)", yol: scriptYolu },
    };
  }
  if (s.mode === "replay_miss" && s.durum !== "merged" && s.durum !== "closed") {
    return { metin: "REPLAY-MISS: kayıtlı model çıktısı yok, canlı model gerekir", ayrinti: null, eylem: { tur: "yeniden_uret", etiket: "Yeniden üret" } };
  }
  if (s.durum === "unverified") {
    return { metin: "Doğrulanmamış dil: kod derlenmedi ve koşulmadı, PR açılmaz", ayrinti: null, eylem: { tur: "baglanti", etiket: "Kodu indir (script'i aç)", yol: scriptYolu } };
  }
  if (veriDegisti) {
    return { metin: "Test verisi değişti: kod eski değerle üretildi", ayrinti: null, eylem: { tur: "yeniden_uret", etiket: "Yeniden üret" } };
  }
  return null;
}

/** Listedeki grup: dikkat gerekenler önce, süren/PR açık sonra, birleşen ve kapatılanlar en sonda. */
export function scriptGrubu(s: Script, veriDegisti = false): ScriptGrubu {
  if (dikkatNedeni(s, veriDegisti)) return "dikkat";
  if (s.durum === "merged" || s.durum === "closed") return "birlesen";
  return "suren";
}

export const GRUP_BASLIGI: Record<ScriptGrubu, string> = {
  dikkat: "Dikkat gerekenler",
  suren: "Süren üretim ve açık PR'lar",
  birlesen: "Birleşenler",
};
