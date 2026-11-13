// 009: platform rozeti ve platform seçici (segmentli radyo grubu).
//
// Rozet kategorik bilgidir: nötr hap (K4 renk disiplini — mor yalnız AI, yeşil insan kapısı).
// Seçici yerel radyo düğmeleridir (fieldset + legend): ok tuşlarıyla gezilir, ekran okuyucu
// "Platform, radyo grubu" der. Seçili parça dolu `--accent-solid` + beyaz metin ve ✓ işaretiyle
// ayrılır (renk tek gösterge değil).
import { useId } from "react";
import type { ReactNode } from "react";
import {
  PLATFORMLAR,
  PLATFORM_ACIKLAMASI,
  PLATFORM_ETIKETI,
  PLATFORM_ORTAMI,
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
  ipucu?: ReactNode;
  className?: string;
};

export type SegmentSecenegi<T extends string> = {
  deger: T;
  ad: string;
  aciklama?: string;
  /**
   * Seçilemez seçenek. Radyo `disabled` yapılmaz (odaklanamaz, ekran okuyucu nedeni duymaz):
   * `aria-disabled` ile odakta kalır, seçim değişmez; `neden` seçeneğin içinde görünür yazılır ve
   * tanım (aria-describedby) olarak okunur.
   */
  pasif?: boolean;
  neden?: string | null;
  /** Nedenin teknik ayrıntısı (yapılandırma adı vb.): yalnız ipucu (`title`), görünür metinde yok. */
  nedenAyrinti?: string | null;
};

/** Segment görünümünde yerel radyo grubu (fieldset + legend). Platform ve dil seçicilerinin ortak gövdesi. */
export function SegmentGrubu<T extends string>({
  etiket,
  deger,
  degistir,
  secenekler,
  aciklamali,
  disabled,
  ipucu,
  className,
}: SeciciOzellikleri<T> & { secenekler: SegmentSecenegi<T>[] }) {
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
          const aciklama = aciklamali ? s.aciklama : undefined;
          // Pasif seçeneğin nedeni "Kullanılamıyor: …" diye; açık seçeneğin nedeni (ör. depo okunamadığı için
          // kullanılabilirlik bilinmiyor) de görünür ve aynı tanımla okunur (MİM-B1).
          const neden = s.pasif ? s.neden?.trim() || "Bu seçenek kullanılamıyor." : s.neden?.trim() || undefined;
          const alt = !!aciklama || !!neden;
          return (
            <label key={s.deger} className={`platform-secenek${s.pasif ? " pasif" : ""}`} title={s.nedenAyrinti ?? undefined}>
              <input
                type="radio"
                name={ad}
                value={s.deger}
                checked={s.deger === deger}
                // Pasif seçenek seçilemez: denetimli radyo eski değerinde kalır (odak seçenekte, neden okunur).
                onChange={() => {
                  if (!s.pasif) degistir(s.deger);
                }}
                aria-disabled={s.pasif || undefined}
                aria-labelledby={adId}
                aria-describedby={alt ? altId : undefined}
              />
              <span className="platform-secenek-ad" id={adId}>
                {s.ad}
              </span>
              {alt && (
                <span className="platform-secenek-alt" id={altId}>
                  {aciklama}
                  {neden && (
                    <span className="platform-secenek-neden" data-testid="secenek-neden" data-pasif={s.pasif ? "evet" : "hayir"}>
                      {aciklama && <span className="gorunmez">. </span>}
                      {s.pasif ? `Kullanılamıyor: ${neden}` : neden}
                    </span>
                  )}
                </span>
              )}
            </label>
          );
        })}
      </div>
      {ipucu && (
        <div className="kucuk soluk platform-secici-ipucu" id={ipucuId}>
          {ipucu}
        </div>
      )}
    </fieldset>
  );
}

/**
 * Kod üretiminin hedef platformu (varsayılan Web). `dilAyri`: dil ayrı seçiliyor (011) — seçenek
 * açıklaması yalnız ortam/araçtır ("Tarayıcı · Playwright"), dil adı taşımaz.
 */
export function PlatformSecici({ dilAyri, ...p }: SeciciOzellikleri<Platform> & { dilAyri?: boolean }) {
  const aciklama = dilAyri ? PLATFORM_ORTAMI : PLATFORM_ACIKLAMASI;
  return <SegmentGrubu {...p} secenekler={PLATFORMLAR.map((x) => ({ deger: x, ad: PLATFORM_ETIKETI[x], aciklama: aciklama[x] }))} />;
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
