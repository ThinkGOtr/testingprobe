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
            {!tek.kullanilabilir && tek.neden ? ` · Kullanılamıyor: ${tek.neden}` : ""}
          </span>
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
          neden: s.neden,
        }))}
      />
      <div className="dil-notu kucuk">
        <span role="status" data-testid="dil-notu" data-kaynak={elle ? "secildi" : diller.kaynak}>
          {elle
            ? `${secili?.etiket ?? DIL_ETIKETI[deger]} elle seçildi.`
            : diller.kaynak === "algilandi"
              ? `${algilanan} repodan algılandı${dayanak(diller)}.`
              : `Depoda elle yazılmış test bulunamadı; varsayılan dil ${algilanan}.`}
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
