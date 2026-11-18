/**
 * Test ortamları: metinler (TR + EN, `<html lang>`; `lib/proje.ts` kalıbı) ve tür etiketleri.
 * Ortam listesi core `GET /environments`'tandır; canlı (prod) ortamda veriyi değiştiren işlemleri
 * (kırarak doğrulama, demo kırma/sıfırlama) sunucu 409 `engel: "canli_ortam"` ile reddeder; portal
 * düğmeleri önceden pasifler ve nedeni yazar.
 */
import type { OrtamTuru, TestOrtami } from "../api/types";
import { ApiError } from "../api/http";

export type OrtamDili = "tr" | "en";

const METINLER = {
  tr: {
    ortam: "Test ortamı",
    tumu: "Tümü",
    ortamsiz: "Ortamsız",
    varsayilan: "varsayılan",
    canliUyari: "Canlı ortam: koşu yalnız okuma amaçlıdır; veriyi değiştiren işlemler kapalıdır.",
    geceNotu: "Gece koşusu varsayılan ortamda çalışır.",
    tetikOrtami: "Koşunun ortamı",
    canliKapali: "Varsayılan test ortamı canlı (üretim): veriyi değiştiren işlemler kapalıdır.",
    canliKapaliBaslik: "Canlı ortam",
    kuleIpucu: "Geçme oranı, günlük eğilim, flaky testler ve son koşular seçili ortama göre süzülür; diğer ölçüler tüm ortamlar içindir.",
    rozetOnEki: "Test ortamı: ",
  },
  en: {
    ortam: "Test environment",
    tumu: "All",
    ortamsiz: "No environment",
    varsayilan: "default",
    canliUyari: "Production environment: the run is read-only; data-changing operations are disabled.",
    geceNotu: "The nightly run uses the default environment.",
    tetikOrtami: "Run environment",
    canliKapali: "The default test environment is production: data-changing operations are disabled.",
    canliKapaliBaslik: "Production environment",
    kuleIpucu: "Pass rate, daily trend, flaky tests and last runs are filtered by the selected environment; other metrics cover all environments.",
    rozetOnEki: "Test environment: ",
  },
} as const;

export type OrtamMetinAnahtari = keyof (typeof METINLER)["tr"];

const TUR_ETIKETI: Record<OrtamDili, Record<OrtamTuru, string>> = {
  tr: { dev: "Geliştirme", test: "Test", staging: "Staging", prod: "Canlı" },
  en: { dev: "Development", test: "Test", staging: "Staging", prod: "Production" },
};

export function ortamDili(): OrtamDili {
  const l = (typeof document !== "undefined" ? document.documentElement.lang : "").toLowerCase();
  return l.startsWith("en") ? "en" : "tr";
}

export function ortamMetni(anahtar: OrtamMetinAnahtari, dil: OrtamDili = ortamDili()): string {
  return METINLER[dil][anahtar] ?? METINLER.tr[anahtar];
}

export function ortamTuruEtiketi(tur: OrtamTuru, dil: OrtamDili = ortamDili()): string {
  return TUR_ETIKETI[dil][tur] ?? tur;
}

/** Seçenek metni: "Staging (Staging)", varsayılan ise "· varsayılan" eki. */
export function ortamSecenekMetni(o: TestOrtami & { varsayilan?: boolean }, dil: OrtamDili = ortamDili()): string {
  return `${o.ad} (${ortamTuruEtiketi(o.tur, dil)})${o.varsayilan ? ` · ${ortamMetni("varsayilan", dil)}` : ""}`;
}

/** Sunucunun canlı ortam engeli (409 `engel: "canli_ortam"`). */
export function canliOrtamEngeli(e: unknown): boolean {
  if (!(e instanceof ApiError) || e.status !== 409) return false;
  const g = e.govde;
  return !!g && typeof g === "object" && (g as { engel?: unknown }).engel === "canli_ortam";
}
