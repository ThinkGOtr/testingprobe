// 011 üretim dili: dil rozeti ve Kod üretimi ekranının dil seçicisi.
//
// Rozet kategorik bilgidir (nötr hap; platform rozetinin yanında durur), çatı adı `title` ve ekran
// okuyucu metnidir. Seçici platform seçiciyle aynı segment grubudur (yerel radyolar); seçenekler
// core `GET /code/languages`'tan gelir, algılanan dil seçili açılır ve kaynağı ("repodan algılandı" /
// "varsayılan" / "elle seçildi") grubun altında yazılır.
import type { DilSecenegi, KodDilleri, KurulumPr } from "../api/types";
import { DIL_CATISI, DIL_ETIKETI, KIRARAK_DOGRULANMADI, KIRARAK_DOGRULANMADI_ACIKLAMA, type Dil } from "../lib/dil";
import { Baglanti, Uyari } from "./ui";
import { PLATFORM_ETIKETI, type Platform } from "../lib/platform";
import { ortamAdlariniGizle } from "../api/http";
import { SegmentGrubu } from "./Platform";

/** Projenin platform test dilleri ayarının AI Probe'daki yeri (core `dil_listesi_yolu` ile aynı; Home'daki adlar). */
export function dilListesiYolu(platform: Platform): string {
  return `AI Probe › Proje › Platform ayarları › ${PLATFORM_ETIKETI[platform]} › Test dilleri`;
}

/** Dil projenin platform test dillerinde seçili değil (core `liste_engeli_metni` ile aynı metin). */
export function listeEngeliMetni(platform: Platform, etiket: string): string {
  return `${etiket} bu projenin ${PLATFORM_ETIKETI[platform]} test dillerinde seçili değil. Açmak için ${dilListesiYolu(platform)} bölümünde ${etiket} seçeneğini işaretleyin`;
}

/**
 * core'un eski Java web engeli ("GitHub kipinde Java web hattı etkin değil (TP_WEB_DILLERI …)"). Yeni core
 * aynı metni kendisi yazar (`liste` engeli); eski core'da da kullanıcı açma yolunu görür (T2-2, ekran testi 2 TP-3).
 */
export const JAVA_WEB_KAPALI = listeEngeliMetni("web", "Java");

/** Değerlendirme kapısı ("Yakında"): projeden açılamaz; ürün değerlendirmesi bitince açılır. */
export const YAKINDA_ACIKLAMA = "Değerlendirme sürüyor: bu dil ürün değerlendirmesi tamamlanınca açılır, projeden açılamaz";

/** core: GitHub App kipinde algılama worker'da sürüyor (`codegen.dil_algila`, bekleme süresi doldu). */
export const ALGILAMA_SURUYOR = /algılama sürüyor/i;

/**
 * Seçenek nedenini kullanıcı metnine çevirir: yapılandırma adı (TP_*), iş akışı / zorunlu check gibi
 * iç ayrıntı görünür metinden çıkar, `ayrinti` olarak (yalnız ipucu) döner. Yeni core metni zaten
 * temizdir; eski core'un "GitHub kipinde X hattı etkin değil (TP_…)" metni platform biliniyorsa
 * açma yoluyla yeniden yazılır. "Değerlendirme sürüyor" açıklanır (her kapalı nedende yol/durum).
 */
export function dilNedeni(
  neden: string | null | undefined,
  platform?: Platform | null,
): { metin: string | null; ayrinti: string | null } {
  const n = neden?.trim();
  if (!n) return { metin: null, ayrinti: null };
  if (/^Değerlendirme sürüyor$/i.test(n)) return { metin: YAKINDA_ACIKLAMA, ayrinti: null };
  const teknik = /\bTP_[A-Z0-9_]+|iş akışı|zorunlu check|Yapılandırma hatası/i.test(n);
  if (!teknik) return { metin: n, ayrinti: null };
  if (/Java web hattı etkin değil/i.test(n)) return { metin: JAVA_WEB_KAPALI, ayrinti: n };
  const hat = /GitHub kipinde (.+?) hattı etkin değil/i.exec(n);
  if (hat && platform) return { metin: listeEngeliMetni(platform, hat[1]), ayrinti: n };
  if (/^Yapılandırma hatası/i.test(n)) {
    if (!/\bTP_[A-Z0-9_]+/.test(n)) return { metin: n, ayrinti: null };
    return { metin: platform ? `Yapılandırma hatası: ${PLATFORM_ETIKETI[platform]} test dilleri ayarı geçersiz. ${dilListesiYolu(platform)} bölümünü kontrol edip yeniden kaydedin` : "Bu dil bu kurulumda yapılandırılmamış", ayrinti: n };
  }
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

/** Algılama worker'da sürüyorsa (core üst düzey `neden`) "depo okunamadı" denmez. */
export function algilamaSuruyorMu(diller: Pick<KodDilleri, "neden"> | null | undefined): boolean {
  return !!diller?.neden && ALGILAMA_SURUYOR.test(diller.neden);
}

function algilamaNotu(diller: KodDilleri, elleSecilebilir = true): string {
  const algilanan = DIL_ETIKETI[diller.algilanan];
  if (algilamaSuruyorMu(diller)) return `Dil algılanıyor; şimdilik varsayılan: ${algilanan}. Birkaç saniye içinde yeniden denenir.`;
  return algilanamadiMesaji(algilanan, elleSecilebilir);
}

/** Dil notunun metni: elle seçim, repodan algılama, algılama sonuçsuz ya da algılama yapılamadı. */
function dilNotu(diller: KodDilleri, elle: boolean, seciliEtiket: string): string {
  const algilanan = DIL_ETIKETI[diller.algilanan];
  if (elle) return `${seciliEtiket} elle seçildi.`;
  if (diller.neden) return algilamaNotu(diller);
  if (diller.kaynak === "algilandi") return `${algilanan} repodan algılandı${dayanak(diller)}.`;
  const engelli = engelliAlgilanan(diller);
  if (engelli) return engelliAlgilananNotu(engelli, algilanan, diller);
  return `${ALGILAMA_KAPSAMI} elle yazılmış test bulunamadı; varsayılan: ${algilanan}.`;
}

/**
 * Algılanan (en çok testi olan) dil seçilemediği için varsayılana düşüldüyse o dil ve sayısı (ekran testi 2
 * TP-2). Yeni core `engelli_algilanan` gönderir; eski core'da sayılardan çıkarılır (en çok testi olan dil).
 */
export function engelliAlgilanan(diller: Pick<KodDilleri, "kaynak" | "algilanan" | "sayilar" | "engelli_algilanan" | "secenekler" | "en_az">) {
  if (diller.kaynak === "algilandi") return null;
  if (diller.engelli_algilanan) return diller.engelli_algilanan;
  if (diller.engelli_algilanan === null) return null; // yeni core: algılanan seçilebilir ya da test yok
  let enCok: Dil | null = null;
  for (const [d, n] of Object.entries(diller.sayilar) as [Dil, number][]) {
    if (n > 0 && (enCok === null || n > (diller.sayilar[enCok] ?? 0))) enCok = d;
  }
  if (!enCok || enCok === diller.algilanan) return null;
  const s = diller.secenekler.find((x) => x.dil === enCok);
  return { dil: enCok, sayi: diller.sayilar[enCok] ?? 0, en_az: !!diller.en_az?.includes(enCok), engel: s?.engel ?? null, neden: s?.neden ?? null };
}

const ENGEL_KISA: Record<string, string> = {
  liste: "bu projede seçili değil",
  yakinda: "henüz değerlendirmede (Yakında)",
  depo: "bu depoda üretilemiyor",
  yapilandirma: "yapılandırma hatası nedeniyle seçilemiyor",
};

function engelliAlgilananNotu(e: NonNullable<ReturnType<typeof engelliAlgilanan>>, varsayilan: string, diller: KodDilleri): string {
  const ad = DIL_ETIKETI[e.dil];
  const sayi = `${e.en_az ? "en az " : ""}${e.sayi}`;
  const neden = (e.engel && ENGEL_KISA[e.engel]) || "seçilemiyor";
  return `Depoda en çok ${ad} testi var (${sayi}) ama ${ad} ${neden}; varsayılan: ${varsayilan}.${sayilarMetni(diller)}`;
}

/** " Depodaki elle yazılmış test dosyaları: TypeScript 8, Java 5, C# 9." (birden çok dilde test varsa). */
export function sayilarMetni(diller: Pick<KodDilleri, "sayilar" | "en_az">): string {
  const parcalar = (Object.entries(diller.sayilar) as [Dil, number][])
    .filter(([, n]) => n > 0)
    .map(([d, n]) => `${DIL_ETIKETI[d]} ${diller.en_az?.includes(d) ? "≥" : ""}${n}`);
  return parcalar.length > 1 ? ` Depodaki elle yazılmış test dosyaları: ${parcalar.join(", ")}.` : "";
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

/** Seçenek rozeti: durum (Yakında) ve hat (Müşteri CI) ayrı bilgilerdir; ikisi varsa birlikte yazılır. */
export function secenekRozeti(s: Pick<DilSecenegi, "durum" | "hat">): string | null {
  const parcalar = [s.durum === "yakinda" ? "Yakında" : null, s.hat === "musteri_ci" ? "Müşteri CI" : null].filter(Boolean);
  return parcalar.length ? parcalar.join(" · ") : null;
}

function liste(adlar: string[]): string {
  return adlar.length > 1 ? `${adlar.slice(0, -1).join(", ")} ve ${adlar[adlar.length - 1]}` : (adlar[0] ?? "");
}

/**
 * Kod üretimi sayfa açıklaması (T2-2): yalnız bu kurulumda seçilebilen dillerden söz eder (ör. Java web
 * hattı kapalıyken Java anılmaz). Hat başına: tam → yerel kontrol + PR; müşteri CI → koşu müşterinin
 * CI'ında; doğrulanmamış → kod doğrulanmamış çıkar.
 */
export function uretimAciklamasi(diller: Pick<KodDilleri, "secenekler">): string {
  const acik = diller.secenekler.filter((s) => s.durum !== "yakinda" && s.kullanilabilir);
  const adlar = (hat: DilSecenegi["hat"]) => acik.filter((s) => s.hat === hat).map((s) => s.etiket);
  const tam = adlar("tam");
  const musteri = adlar("musteri_ci");
  const dogrulanmamis = adlar("dogrulanmamis");
  let m =
    "Onaylı case'ler seçilen platformda adım adım doğrulanır (Web: Playwright MCP; Android, iOS, Windows: Appium), page object'lere eşlenir ve seçilen dilde şablondan teste dönüşür. Model kod yazmaz; ";
  m += tam.length ? `${liste(tam)} için yerel kontrol yeşilse bot ayrı dalda PR açar` : "yerel kontrol yeşilse bot ayrı dalda PR açar";
  if (musteri.length) m += `; ${liste(musteri)} testleri müşteri CI'da koşar`;
  if (dogrulanmamis.length) m += `; ${liste(dogrulanmamis)} kodu doğrulanmamış olarak çıkar`;
  return `${m}.`;
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
              <span title={dilNedeni(tek.neden, diller.platform).ayrinti ?? undefined}>
                {tek.kullanilabilir ? ` · ${dilNedeni(tek.neden, diller.platform).metin}` : ` · Kullanılamıyor: ${dilNedeni(tek.neden, diller.platform).metin}`}
              </span>
            ) : (
              ""
            )}
          </span>
          {diller.neden && (
            <span className="kucuk" role="status" data-testid="dil-notu" data-kaynak="algilanamadi">
              {algilamaNotu(diller, false)}
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
          // İki bilgi birlikte: "Yakında" müşteri CI hattını gizlemez (T2-3).
          rozet: secenekRozeti(s),
          pasif: !s.kullanilabilir,
          pasifOnek: s.durum === "yakinda" ? "Yakında" : undefined,
          // Algılama hiç yapılamadıysa (üst düzey `neden`) kullanılabilir seçeneklerdeki aynı "depo
          // okunamadı" nedeni her kutuda tekrarlanmaz; durum altta tek notla söylenir.
          neden: diller.neden && s.kullanilabilir ? undefined : dilNedeni(s.neden, diller.platform).metin,
          nedenAyrinti: diller.neden && s.kullanilabilir ? undefined : dilNedeni(s.neden, diller.platform).ayrinti,
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
