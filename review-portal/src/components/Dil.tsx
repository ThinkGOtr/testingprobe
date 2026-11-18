// 011 üretim dili: dil rozeti ve Kod üretimi ekranının dil seçicisi.
//
// Rozet kategorik bilgidir (nötr hap; platform rozetinin yanında durur), çatı adı `title` ve ekran
// okuyucu metnidir. Seçici platform seçiciyle aynı segment grubudur (yerel radyolar); seçenekler
// core `GET /code/languages`'tan gelir, algılanan dil seçili açılır ve kaynağı ("repodan algılandı" /
// "varsayılan" / "elle seçildi") grubun altında yazılır.
import type { DilSecenegi, KodDilleri, KurulumPr } from "../api/types";
import { DIL_CATISI, DIL_ETIKETI, KIRARAK_DOGRULANMADI, KIRARAK_DOGRULANMADI_ACIKLAMA, type Dil } from "../lib/dil";
import { Baglanti, Uyari } from "./ui";
import type { Platform } from "../lib/platform";
import { ortamAdlariniGizle } from "../api/http";
import { SegmentGrubu } from "./Platform";

/** core'un Java web engeli ("GitHub kipinde Java web hattı etkin değil (TP_WEB_DILLERI …)"). */
export const JAVA_WEB_KAPALI = "Java web hattı bu kurulumda etkin değil";

/**
 * Seçenek nedenini kullanıcı metnine çevirir: yapılandırma adı (TP_*), iş akışı / zorunlu check gibi
 * iç ayrıntı görünür metinden çıkar, `ayrinti` olarak (yalnız ipucu) döner.
 */
export function dilNedeni(neden: string | null | undefined): { metin: string | null; ayrinti: string | null } {
  const n = neden?.trim();
  if (!n) return { metin: null, ayrinti: null };
  const teknik = /\bTP_[A-Z0-9_]+|iş akışı|zorunlu check|Yapılandırma hatası/i.test(n);
  if (!teknik) return { metin: n, ayrinti: null };
  if (/Java web hattı etkin değil/i.test(n)) return { metin: JAVA_WEB_KAPALI, ayrinti: n };
  if (/^Yapılandırma hatası/i.test(n)) return { metin: "Bu dil bu kurulumda yapılandırılmamış", ayrinti: n };
  const temiz = ortamAdlariniGizle(n.replace(/\s*\([^)]*(?:TP_|iş akışı|check)[^)]*\)/gi, "")).trim();
  return { metin: temiz || "Bu kurulumda kullanılamıyor", ayrinti: n };
}

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

/** Seçeneğin altındaki açıklama: çatı + hat notu (doğrulanmamış / müşteri CI'da kırarak doğrulama yok). */
export function secenekAciklamasi(s: Pick<DilSecenegi, "cati" | "hat">): string {
  if (s.hat === "dogrulanmamis") return `${s.cati} · doğrulanmamış`;
  if (s.hat === "musteri_ci") return `${s.cati} · koşu müşteri CI'da, kırarak doğrulama yok`;
  return s.cati;
}

/**
 * 014 müşteri CI hattı notu (Kod üretimi, seçili dil `musteri_ci`): test TP'de koşmaz, müşterinin GitHub
 * Actions iş akışında koşar; kırarak doğrulama yapılmaz (kullanıcı kararı 2).
 */
export function MusteriCiNotu({ etiket, id }: { etiket: string; id?: string }) {
  return (
    <div data-testid="musteri-ci-notu">
      <Uyari ton="bilgi" baslik={`Müşteri CI hattı: ${etiket} · ${KIRARAK_DOGRULANMADI}`} id={id}>
        {KIRARAK_DOGRULANMADI_ACIKLAMA} PR'da ve script detayında "{KIRARAK_DOGRULANMADI}" rozeti görünür.
      </Uyari>
    </div>
  );
}

const KURULUM_BASLIGI: Record<KurulumPr["durum"], string> = {
  gerekli: "Kurulum PR'ı gerekli",
  acik: "Kurulum PR'ı açık",
  birlesti: "Kurulum PR'ı birleşti",
  kapali: "Kurulum PR'ı kapatıldı",
};

/**
 * 014 kurulum PR'ı (kullanıcı kararı 1): depoda dilin iskeleti / ekran nesnesi kütüphanesi / CI iş akışı
 * yoksa TP tek seferlik, insan onaylı bir PR açar. Birleşmiş kurulum yalnız kısa satırdır.
 */
export function KurulumBilgisi({ kurulum, dilEtiketi }: { kurulum: KurulumPr | null | undefined; dilEtiketi: string }) {
  if (!kurulum) return null;
  if (kurulum.durum === "birlesti") {
    return (
      <p className="kucuk soluk kurulum-pr" data-testid="kurulum-pr" data-durum="birlesti">
        {dilEtiketi} kurulumu tamam
        {kurulum.number !== null && (
          <>
            {" "}
            (kurulum PR'ı <span className="mono">#{kurulum.number}</span> birleşti)
          </>
        )}
        .
      </p>
    );
  }
  const ton = kurulum.durum === "kapali" ? "uyari" : "bilgi";
  return (
    <div className="kurulum-pr" data-testid="kurulum-pr" data-durum={kurulum.durum}>
      <Uyari ton={ton} baslik={`${KURULUM_BASLIGI[kurulum.durum]}: ${dilEtiketi}`}>
        <p className="kucuk">
          {kurulum.durum === "gerekli"
            ? `Depoda ${dilEtiketi} için eksikler var. TP tek seferlik bir kurulum PR'ı açar; insan onayıyla birleşince bu dilde üretilen testler CI'da koşar.`
            : kurulum.durum === "acik"
              ? `Kurulum PR'ı birleşene kadar ${dilEtiketi} testleri CI'da koşamaz.`
              : `Kurulum PR'ı birleşmeden kapatıldı; ${dilEtiketi} testleri CI'da koşamaz.`}
          {kurulum.number !== null && (
            <>
              {" "}
              {kurulum.url ? <Baglanti href={kurulum.url}>{`#${kurulum.number}${kurulum.baslik ? ` ${kurulum.baslik}` : ""}`}</Baglanti> : <span className="mono">#{kurulum.number}</span>}
            </>
          )}
        </p>
        {kurulum.eksikler.length > 0 && (
          <ul className="kucuk" aria-label="Kurulumun eklediği">
            {kurulum.eksikler.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        )}
        {kurulum.elle_adimlar.length > 0 && (
          <>
            <p className="kucuk">
              <strong>Elle yapılacak:</strong>
            </p>
            <ul className="kucuk" aria-label="Elle yapılacak adımlar">
              {kurulum.elle_adimlar.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          </>
        )}
      </Uyari>
    </div>
  );
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
            {tek.neden && !(diller.neden && tek.kullanilabilir) ? (
              <span title={dilNedeni(tek.neden).ayrinti ?? undefined}>
                {tek.kullanilabilir ? ` · ${dilNedeni(tek.neden).metin}` : ` · Kullanılamıyor: ${dilNedeni(tek.neden).metin}`}
              </span>
            ) : (
              ""
            )}
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
          aciklama: secenekAciklamasi(s),
          rozet: s.durum === "yakinda" ? "Yakında" : s.hat === "musteri_ci" ? "Müşteri CI" : null,
          pasif: !s.kullanilabilir,
          pasifOnek: s.durum === "yakinda" ? "Yakında" : undefined,
          // Algılama hiç yapılamadıysa (üst düzey `neden`) kullanılabilir seçeneklerdeki aynı "depo
          // okunamadı" nedeni her kutuda tekrarlanmaz; durum altta tek notla söylenir.
          neden: diller.neden && s.kullanilabilir ? undefined : dilNedeni(s.neden).metin,
          nedenAyrinti: diller.neden && s.kullanilabilir ? undefined : dilNedeni(s.neden).ayrinti,
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
