import { useId } from "react";
import type { UretimKipi } from "../api/tasarimModeliTipleri";
import { VARSAYILAN_URETIM_KIPI } from "../lib/uretimSecenekleri";

/** Üretim kipleri (011 K1): iki tur varsayılan ve önerilen; tek tur hızlı yol. */
export const URETIM_KIPLERI: { deger: UretimKipi; ad: string; aciklama: string }[] = [
  {
    deger: "iki_tur",
    ad: "İki tur (önerilen)",
    aciklama: "Önce test tasarım modeli üretilir; modeli onayladığınızda case'ler yalnız onaylı modelden otomatik üretilir.",
  },
  {
    deger: "tek_tur",
    ad: "Tek tur (hızlı)",
    aciklama: "Case'ler doğrudan üretilir; tasarım modeli adımı yoktur.",
  },
];

export const VARSAYILAN_KIP: UretimKipi = VARSAYILAN_URETIM_KIPI;

/**
 * Üretim kipi seçimi (radyo grubu, fieldset + legend). Gereksinim ekranında üretim formunun ilk
 * alanıdır; form kapalıyken üst düğmelerin altında tek başına durur. Portal kipi her zaman açıkça
 * gönderir (gövdesiz çağrı core'da tek tur kalır; geriye uyum). İlk değer gereksinimde kayıtlı
 * tercihten gelir (D1), yoksa iki tur.
 */
export function UretimKipiSecici({
  kip,
  degistir,
  disabled,
}: {
  kip: UretimKipi;
  degistir: (k: UretimKipi) => void;
  disabled?: boolean;
}) {
  const kimlik = useId();
  return (
    <fieldset className="uretim-kipi" disabled={disabled} data-testid="uretim-kipi" aria-describedby={`${kimlik}-ipucu`}>
      <legend>Üretim kipi</legend>
      {URETIM_KIPLERI.map((s) => (
        <label key={s.deger} className="secenek-satir">
          <input type="radio" name={`${kimlik}-kip`} value={s.deger} checked={kip === s.deger} onChange={() => degistir(s.deger)} />
          <span>
            <strong>{s.ad}</strong>: {s.aciklama}
          </span>
        </label>
      ))}
      <p className="kucuk soluk" id={`${kimlik}-ipucu`}>
        İki turda model; koşulları, seçilen teknikleri, bölümleri, sınırları, karar ve durum tablolarını, açık soruları gösterir.
        Onayladığınız modelde olmayan davranış için case yazılmaz. Üretimi başlatan düğme seçili kipi adıyla söyler.
      </p>
    </fieldset>
  );
}
