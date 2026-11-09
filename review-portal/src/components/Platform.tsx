// 009: platform rozeti ve platform seçici (segmentli radyo grubu).
//
// Rozet kategorik bilgidir: nötr hap (K4 renk disiplini — mor yalnız AI, yeşil insan kapısı).
// Seçici yerel radyo düğmeleridir (fieldset + legend): ok tuşlarıyla gezilir, ekran okuyucu
// "Platform, radyo grubu" der. Seçili parça dolu `--accent-solid` + beyaz metin ve ✓ işaretiyle
// ayrılır (renk tek gösterge değil).
import { useId } from "react";
import {
  PLATFORMLAR,
  PLATFORM_ACIKLAMASI,
  PLATFORM_ETIKETI,
  type Platform,
  type PlatformSecimi,
} from "../lib/platform";

export function PlatformRozeti({ platform }: { platform: Platform | null | undefined }) {
  if (!platform) return null;
  return (
    <span className="cip cip-notr platform-rozeti" data-platform={platform} data-testid="platform-rozeti">
      <span className="gorunmez">Platform: </span>
      {PLATFORM_ETIKETI[platform]}
    </span>
  );
}

type SeciciOzellikleri<T extends string> = {
  /** Grubun görünen adı (legend). */
  etiket: string;
  deger: T;
  degistir: (p: T) => void;
  /** Her seçeneğin altında kısa açıklama (ör. "Emülatör · Appium + Java"). */
  aciklamali?: boolean;
  disabled?: boolean;
  /** Grubun altında açıklama metni (aria-describedby). */
  ipucu?: string;
  className?: string;
};

function SegmentGrubu<T extends string>({
  etiket,
  deger,
  degistir,
  secenekler,
  aciklamali,
  disabled,
  ipucu,
  className,
}: SeciciOzellikleri<T> & { secenekler: { deger: T; ad: string; aciklama?: string }[] }) {
  const ad = useId();
  const ipucuId = `${ad}-ipucu`;
  return (
    <fieldset className={`platform-secici${className ? ` ${className}` : ""}`} disabled={disabled} aria-describedby={ipucu ? ipucuId : undefined}>
      <legend>{etiket}</legend>
      <div className={`platform-secenekler${aciklamali ? " aciklamali" : ""}`}>
        {secenekler.map((s) => {
          // Ad yalnız platform adı; kısa açıklama ayrı tanım (aria-describedby) olarak okunur.
          const adId = `${ad}-${s.deger}-ad`;
          const altId = `${ad}-${s.deger}-alt`;
          const alt = aciklamali && s.aciklama;
          return (
            <label key={s.deger} className="platform-secenek">
              <input
                type="radio"
                name={ad}
                value={s.deger}
                checked={s.deger === deger}
                onChange={() => degistir(s.deger)}
                aria-labelledby={adId}
                aria-describedby={alt ? altId : undefined}
              />
              <span className="platform-secenek-ad" id={adId}>
                <span className="platform-secenek-isaret" aria-hidden="true">
                  ✓
                </span>
                {s.ad}
              </span>
              {alt && (
                <span className="platform-secenek-alt" id={altId}>
                  {s.aciklama}
                </span>
              )}
            </label>
          );
        })}
      </div>
      {ipucu && (
        <p className="kucuk soluk platform-secici-ipucu" id={ipucuId}>
          {ipucu}
        </p>
      )}
    </fieldset>
  );
}

/** Kod üretiminin hedef platformu (varsayılan Web). */
export function PlatformSecici(p: SeciciOzellikleri<Platform>) {
  return (
    <SegmentGrubu
      {...p}
      secenekler={PLATFORMLAR.map((x) => ({ deger: x, ad: PLATFORM_ETIKETI[x], aciklama: PLATFORM_ACIKLAMASI[x] }))}
    />
  );
}

/** Liste/ölçü süzgeci: "Tümü" + dört platform. */
export function PlatformSuzgeci(p: SeciciOzellikleri<PlatformSecimi>) {
  return (
    <SegmentGrubu
      {...p}
      className={`platform-suzgeci${p.className ? ` ${p.className}` : ""}`}
      secenekler={[{ deger: "tumu" as PlatformSecimi, ad: "Tümü" }, ...PLATFORMLAR.map((x) => ({ deger: x as PlatformSecimi, ad: PLATFORM_ETIKETI[x] }))]}
    />
  );
}
