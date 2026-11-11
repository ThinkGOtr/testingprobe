import type { UretimKipi } from "../api/tasarimModeliTipleri";

/** Üretim kipleri (011 K1): iki tur varsayılan ve önerilen; tek tur hızlı yol. */
export const URETIM_KIPLERI: { deger: UretimKipi; ad: string; aciklama: string }[] = [
  {
    deger: "iki_tur",
    ad: "İki tur (önerilen)",
    aciklama: "Önce test tasarım modeli, onayınızdan sonra yalnız onaylı modelden case.",
  },
  {
    deger: "tek_tur",
    ad: "Tek tur (hızlı)",
    aciklama: "Doğrudan case üretimi.",
  },
];

export const VARSAYILAN_KIP: UretimKipi = "iki_tur";

/**
 * Üretim başlatma formunun kip seçimi. Portal kipi her zaman açıkça gönderir (gövdesiz çağrı
 * core'da tek tur kalır; geriye uyum). Seçim yalnız bu ekranda tutulur.
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
  return (
    <fieldset className="uretim-kipi" disabled={disabled} data-testid="uretim-kipi" aria-describedby="uretim-kipi-ipucu">
      <legend>Üretim kipi</legend>
      {URETIM_KIPLERI.map((s) => (
        <label key={s.deger} className="secenek-satir">
          <input type="radio" name="uretim-kipi" value={s.deger} checked={kip === s.deger} onChange={() => degistir(s.deger)} />
          <span>
            <strong>{s.ad}</strong>: {s.aciklama}
          </span>
        </label>
      ))}
      <p className="kucuk soluk" id="uretim-kipi-ipucu">
        İki turda model; koşulları, seçilen teknikleri, bölümleri, sınırları, karar ve durum tablolarını, açık soruları gösterir.
        Onayladığınız modelde olmayan davranış için case yazılmaz. Seçimi "Case üret" düğmesi kullanır.
      </p>
    </fieldset>
  );
}
