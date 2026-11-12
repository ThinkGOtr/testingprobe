// 011 üretim dili: dil rozeti ve Kod üretimi ekranının dil seçicisi.
//
// Rozet kategorik bilgidir (nötr hap; platform rozetinin yanında durur), çatı adı `title` ve ekran
// okuyucu metnidir. Seçici platform seçiciyle aynı segment grubudur (yerel radyolar); seçenekler
// core `GET /code/languages`'tan gelir, algılanan dil seçili açılır ve kaynağı ("repodan algılandı" /
// "varsayılan" / "elle seçildi") grubun altında yazılır.
import type { KodDilleri } from "../api/types";
import { DIL_CATISI, DIL_ETIKETI, type Dil } from "../lib/dil";
import type { Platform } from "../lib/platform";
import { SegmentGrubu } from "./Platform";

export function DilRozeti({ dil, platform }: { dil: Dil | null | undefined; platform?: Platform | null }) {
  if (!dil) return null;
  const cati = platform ? DIL_CATISI(platform, dil) : null;
  return (
    <span className="cip cip-notr dil-rozeti" data-dil={dil} data-testid="dil-rozeti" title={cati ?? undefined}>
      <span className="gorunmez">Dil: </span>
      {DIL_ETIKETI[dil]}
      {cati && <span className="gorunmez"> ({cati})</span>}
    </span>
  );
}

/**
 * Algılamanın baktığı yerler (core `dil_algila`, 011 §2.4 / K-T7): TS `e2e/tests`, Java `e2e-java`
 * (`src/test/java`), C# ve Python test projeleri. Algılama sonuçsuzsa (`kaynak="varsayilan"`) mesaj
 * "depoda test yok" demez: yalnız bu yerlerde elle yazılmış test bulunamadığını söyler.
 */
export const ALGILAMA_KAPSAMI = "e2e/, e2e-java/, C# ve Python test projelerinde";

/**
 * Algılama hiç yapılamadıysa (core üst düzey `neden` dolu: depo/forge okunamadı) "test bulunamadı"
 * denmez; dürüst ileti budur (MİM-B1).
 */
/**
 * Algılama yapılamadığında not. `elleSecilebilir` (varsayılan): seçenek birden çoksa elle seçim önerilir;
 * tek seçenekte öneri eklenmez (metin parçalardan kurulur, sonradan kırpılmaz).
 */
export function algilanamadiMesaji(varsayilan: string, elleSecilebilir = true): string {
  const temel = `Depo okunamadığı için dil algılanamadı; varsayılan: ${varsayilan}.`;
  return elleSecilebilir ? `${temel} Dili elle seçebilirsiniz.` : temel;
}

/** Dil notunun metni: elle seçim, repodan algılama, algılama sonuçsuz ya da algılama yapılamadı. */
function dilNotu(diller: KodDilleri, elle: boolean, seciliEtiket: string): string {
  const algilanan = DIL_ETIKETI[diller.algilanan];
  if (elle) return `${seciliEtiket} elle seçildi.`;
  if (diller.neden) return algilanamadiMesaji(algilanan);
  if (diller.kaynak === "algilandi") return `${algilanan} repodan algılandı${dayanak(diller)}.`;
  return `${ALGILAMA_KAPSAMI} elle yazılmış test bulunamadı; varsayılan: ${algilanan}.`;
}

/** Algılamanın dayanağı: "9 elle yazılmış test dosyası" (sayı bilinmiyorsa boş). */
function dayanak(diller: KodDilleri): string {
  const n = diller.sayilar[diller.algilanan];
  return typeof n === "number" && n > 0 ? ` (${n} elle yazılmış test dosyası)` : "";
}

export function DilSecici({
  diller,
  deger,
  degistir,
  elle,
  algilananaDon,
  disabled,
}: {
  diller: KodDilleri;
  /** Seçili dil (elle seçim yoksa algılanan). */
  deger: Dil;
  degistir: (d: Dil) => void;
  /** Kullanıcı algılanandan farklı bir dili elle seçti. */
  elle: boolean;
  algilananaDon: () => void;
  disabled?: boolean;
}) {
  const algilanan = DIL_ETIKETI[diller.algilanan];
  const secili = diller.secenekler.find((s) => s.dil === deger);

  // Tek seçenek (uygulama platformları: yalnız Java): seçim yok, salt bilgi.
  if (diller.secenekler.length === 1) {
    const tek = diller.secenekler[0];
    return (
      <div className="dil-bilgi" role="group" aria-label="Dil" data-testid="dil-bilgi">
        <span className="dil-bilgi-etiket">Dil</span>
        <span className="satir-ogeler">
          <DilRozeti dil={tek.dil} platform={diller.platform} />
          <span className="kucuk soluk">
            {tek.cati} · bu platformda tek dil
            {tek.neden && !(diller.neden && tek.kullanilabilir)
              ? tek.kullanilabilir
                ? ` · ${tek.neden}`
                : ` · Kullanılamıyor: ${tek.neden}`
              : ""}
          </span>
          {diller.neden && (
            <span className="kucuk" role="status" data-testid="dil-notu" data-kaynak="algilanamadi">
              {algilanamadiMesaji(DIL_ETIKETI[diller.algilanan], false)}
            </span>
          )}
        </span>
      </div>
    );
  }

  return (
    <div className="dil-secici">
      <SegmentGrubu
        etiket="Dil"
        deger={deger}
        degistir={degistir}
        disabled={disabled}
        aciklamali
        secenekler={diller.secenekler.map((s) => ({
          deger: s.dil,
          ad: s.etiket,
          aciklama: s.hat === "dogrulanmamis" ? `${s.cati} · doğrulanmamış` : s.cati,
          pasif: !s.kullanilabilir,
          // Algılama hiç yapılamadıysa (üst düzey `neden`) kullanılabilir seçeneklerdeki aynı "depo
          // okunamadı" nedeni her kutuda tekrarlanmaz; durum altta tek notla söylenir.
          neden: diller.neden && s.kullanilabilir ? undefined : s.neden,
        }))}
      />
      <div className="dil-notu kucuk">
        <span role="status" data-testid="dil-notu" data-kaynak={elle ? "secildi" : diller.neden ? "algilanamadi" : diller.kaynak}>
          {dilNotu(diller, elle, secili?.etiket ?? DIL_ETIKETI[deger])}
        </span>
        {elle && (
          <button type="button" className="dugme-metin" onClick={algilananaDon} disabled={disabled}>
            {diller.kaynak === "algilandi" ? "Algılanana dön" : "Varsayılana dön"} ({algilanan})
          </button>
        )}
      </div>
    </div>
  );
}
