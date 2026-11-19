// Ortak tasarım sistemi bileşenleri (UX-T, aip-review/tp-ux-denetim/sistem.md §2/§4). Kullanım kuralları:
// review-portal/README.md "Tasarım sistemi kullanımı". Yeni renk yok; yalnız mevcut belirteçler.
import { useId, useRef, useState, type ReactNode } from "react";
import { type Ton } from "../lib/etiketler";
import { Ipucu } from "./Ipucu";
import { Cip, OdaklanabilirKilitBaglami } from "./ui";

export { OdaklanabilirKilitBaglami };

// ------------------------------------------------------------------ Kimlik / KisaDeger

export type KimlikTuru = "jira" | "ac" | "kosu" | "case" | "sha" | "uuid" | "yol" | "diger";

/** Değeri kısaltır: `orta` → baş…son, `bas` → baştan, `son` → sondan. Kısa değer aynen döner. */
export function kisalt(deger: string, uzunluk: number, kirp: "orta" | "bas" | "son" = "orta"): string {
  if (deger.length <= uzunluk + 1) return deger;
  if (kirp === "bas") return `${deger.slice(0, uzunluk)}…`;
  if (kirp === "son") return `…${deger.slice(-uzunluk)}`;
  const bas = Math.ceil(uzunluk * 0.6);
  return `${deger.slice(0, bas)}…${deger.slice(-(uzunluk - bas))}`;
}

const VARSAYILAN_UZUNLUK: Partial<Record<KimlikTuru, number>> = { sha: 7, uuid: 8, yol: 40 };

/**
 * Kimlik (TS-08/09): mono, tek satır. Uzun teknik değer (sha, uuid, yol) kısaltılır; tam değer klavyeyle ve
 * dokunarak açılan ipucunda (`Ipucu`) ve ekran okuyucuda okunur; `kopyala` ile panoya alınır.
 * `href` verilirse kimlik bağlantıdır (`baglanti` çağıranın Link/Baglanti öğesi; burada çizilmez).
 */
export function Kimlik({
  deger,
  tur = "diger",
  kisaltUzunluk,
  kirp = tur === "yol" ? "bas" : "orta",
  kopyala = false,
  className,
  testId,
}: {
  deger: string;
  tur?: KimlikTuru;
  /** Görünen en çok karakter; verilmezse türün varsayılanı (sha 7, uuid 8, yol 40), diğerleri kısaltılmaz. */
  kisaltUzunluk?: number;
  kirp?: "orta" | "bas" | "son";
  kopyala?: boolean;
  className?: string;
  testId?: string;
}) {
  const uzunluk = kisaltUzunluk ?? VARSAYILAN_UZUNLUK[tur];
  const gorunen = uzunluk ? kisalt(deger, uzunluk, tur === "yol" ? "son" : kirp) : deger;
  const kisaldi = gorunen !== deger;
  const govde = (
    <span className={`kimlik kimlik-${tur} mono${className ? ` ${className}` : ""}`} data-testid={testId} data-deger={kisaldi ? deger : undefined}>
      {gorunen}
    </span>
  );
  return (
    <span className="kimlik-sarici">
      {kisaldi ? <Ipucu metin={deger}>{govde}</Ipucu> : govde}
      {kopyala && <KopyalaDugmesi deger={deger} />}
    </span>
  );
}

/** Uzun teknik değer (sha, uuid, run id, dosya yolu): `Kimlik`in kısaltan kısayolu. */
export function KisaDeger({ deger, uzunluk = 7, kopyala = true, kirp = "orta" }: { deger: string; uzunluk?: number; kopyala?: boolean; kirp?: "orta" | "bas" | "son" }) {
  return <Kimlik deger={deger} tur="sha" kisaltUzunluk={uzunluk} kopyala={kopyala} kirp={kirp} />;
}

export function KopyalaDugmesi({ deger, etiket = "Kopyala" }: { deger: string; etiket?: string }) {
  const [durum, setDurum] = useState<"bos" | "tamam" | "hata">("bos");
  return (
    <button
      type="button"
      className="kopyala-dugmesi"
      aria-label={`${etiket}: ${deger}`}
      onClick={() => {
        const yaz = navigator.clipboard?.writeText(deger);
        if (!yaz) return setDurum("hata");
        yaz.then(
          () => setDurum("tamam"),
          () => setDurum("hata"),
        );
        window.setTimeout(() => setDurum("bos"), 2000);
      }}
    >
      <span aria-hidden="true">{durum === "tamam" ? "✓" : "⧉"}</span>
      <span className="gorunmez" role="status">
        {durum === "tamam" ? "Kopyalandı" : durum === "hata" ? "Kopyalanamadı" : ""}
      </span>
    </button>
  );
}

// ------------------------------------------------------------------ DurumCipi

/**
 * Durum çipi (TS-07): `lib/etiketler.ts` haritasından etiket + ton. Bilinmeyen değer nötr ve aynen yazılır.
 * `aciklama` verilirse erişilebilir ipucu (yalnız `title` değil, ET-06).
 */
export function DurumCipi<K extends string>({
  harita,
  deger,
  aciklama,
}: {
  harita: Partial<Record<K, { etiket: string; ton: Ton }>> | Record<string, { etiket: string; ton: Ton }>;
  deger: K | string;
  aciklama?: string;
}) {
  const d = (harita as Record<string, { etiket: string; ton: Ton } | undefined>)[deger] ?? { etiket: deger, ton: "notr" as Ton };
  return (
    <Cip ton={d.ton} aciklama={aciklama}>
      {d.etiket}
    </Cip>
  );
}

// ------------------------------------------------------------------ MetaIzgara / MetaSatiri

export interface MetaOgesi {
  etiket: ReactNode;
  deger: ReactNode;
  /** Izgarada iki sütunu da kaplar (uzun değer). */
  genis?: boolean;
}

/**
 * "Etiket: değer" ızgarası (TS-05). `duzen="yan"`: dt solda (max-content), dd sağda; `duzen="ust"`: çok sütun,
 * dt değerin üstünde. ≤640 px'te `yan` da üst düzene iner. Boş değer "—" (soluk).
 */
export function MetaIzgara({ ogeler, duzen = "yan", yogun, className, etiket }: { ogeler: MetaOgesi[]; duzen?: "yan" | "ust"; yogun?: boolean; className?: string; etiket?: string }) {
  return (
    <dl className={`meta-izgara meta-izgara-${duzen}${yogun ? " meta-izgara-yogun" : ""}${className ? ` ${className}` : ""}`} aria-label={etiket}>
      {ogeler.map((o, i) => (
        <div key={i} className={o.genis ? "meta-oge meta-oge-genis" : "meta-oge"}>
          <dt>{o.etiket}</dt>
          <dd>{bosMu(o.deger) ? <span className="bos-hucre">—</span> : o.deger}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Satır içi meta (2–4 kısa bilgi): "Etiket değer · Etiket değer"; sarar. Daha çoğu ya da uzun değer → MetaIzgara. */
export function MetaSatiri({ ogeler, className }: { ogeler: { etiket?: ReactNode; deger: ReactNode }[]; className?: string }) {
  const dolu = ogeler.filter((o) => !bosMu(o.deger));
  return (
    <p className={`meta-satiri${className ? ` ${className}` : ""}`}>
      {dolu.map((o, i) => (
        <span key={i} className="meta-satiri-oge">
          {o.etiket && <span className="meta-satiri-etiket">{o.etiket}</span>}
          {o.etiket && " "}
          {o.deger}
        </span>
      ))}
    </p>
  );
}

function bosMu(d: ReactNode): boolean {
  return d === null || d === undefined || d === false || (typeof d === "string" && d.trim() === "");
}

// ------------------------------------------------------------------ SuzgecCubugu / SegmentSecici

/**
 * Süzgeç çubuğu (TS-06): süzgeç denetimlerini (SegmentSecici, SuzgecSecimi, arama, sıralama) tek satırda toplar;
 * `sonuc` ("12 / 41 test") sağda, canlı bölgede okunur.
 */
export function SuzgecCubugu({ etiket, sonuc, children, className }: { etiket: string; sonuc?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={`suzgec-cubugu${className ? ` ${className}` : ""}`} role="group" aria-label={etiket}>
      <div className="suzgec-cubugu-denetimler">{children}</div>
      {sonuc !== undefined && (
        <span className="suzgec-sonuc" role="status">
          {sonuc}
        </span>
      )}
    </div>
  );
}

export interface SegmentSecenegi<D extends string> {
  deger: D;
  ad: ReactNode;
  sayi?: number | null;
  pasif?: boolean;
}

/** Az seçenekli süzgeç (hap düğmeler, `aria-pressed`). Gezinme sekmesi değildir (o, DetaySayfasi `Sekmeler`). */
export function SegmentSecici<D extends string>({
  etiket,
  secenekler,
  deger,
  degistir,
}: {
  etiket: string;
  secenekler: SegmentSecenegi<D>[];
  deger: D;
  degistir: (d: D) => void;
}) {
  return (
    <div className="segment-secici" role="group" aria-label={etiket}>
      {secenekler.map((s) => (
        <button
          key={s.deger}
          type="button"
          className="sekme"
          aria-pressed={s.deger === deger}
          disabled={s.pasif}
          onClick={() => degistir(s.deger)}
        >
          {s.ad}
          {s.sayi != null && " "}
          {s.sayi != null && (
            <span className="ds-sayi">
              <span className="gorunmez">(</span>
              {s.sayi}
              <span className="gorunmez">)</span>
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ EylemCubugu

/**
 * Eylem çubuğu (TS-17): `hiza="son"` sayfa/özet kartı eylemleri (sağda), `hiza="bas"` kart içi karar eylemleri
 * (solda). Birincil eylem ilk çocuk. Sınıf `.eylemler` korunur (IslemDugmesi ortak neden gruplaması buna bağlı).
 */
export function EylemCubugu({ hiza = "bas", etiket, children, className, testId }: { hiza?: "bas" | "son"; etiket?: string; children: ReactNode; className?: string; testId?: string }) {
  return (
    <OdaklanabilirKilitBaglami.Provider value={true}>
      <div className={`eylemler eylem-cubugu eylem-cubugu-${hiza}${className ? ` ${className}` : ""}`} role={etiket ? "group" : undefined} aria-label={etiket} data-testid={testId}>
        {children}
      </div>
    </OdaklanabilirKilitBaglami.Provider>
  );
}

// ------------------------------------------------------------------ TabloSarici

/**
 * Tablo standardı (sistem.md §4): sarıcı kendi içinde yatay kayar (odaklanabilir bölge), sayfa kaymaz.
 * - `darEkran="yigin"` (kayıt tablosu: satır = bir kayıt) → ≤640 px'te "etiket: değer" kartı; hücreler `data-etiket` taşır.
 * - `darEkran="kaydir"` (matris tablo: karar tablosu, sürüm × ölçüt) → kayar, ilk sütun yapışkan.
 * - `yogunluk="sik"`: kart içi/detay tabloları; `th` ve `td` yatay dolgusu her yoğunlukta eşit.
 * - `uzun`: uzun liste (≥ ~20 satır) — sarıcı en çok görünüm yüksekliğinin %70'i kadar, kendi içinde dikey kayar,
 *   başlık satırı yapışkan (ET-02).
 * Sütun türleri hücre sınıfıyla: `sutun-kimlik | sutun-durum | sutun-sayi | sutun-tarih | sutun-metin | sutun-zengin | sutun-eylem`.
 */
export function TabloSarici({
  etiket,
  darEkran = "yigin",
  yogunluk = "normal",
  uzun,
  satirBaglanti,
  className,
  tabloClassName,
  testId,
  children,
}: {
  etiket: string;
  darEkran?: "yigin" | "kaydir";
  yogunluk?: "normal" | "sik";
  uzun?: boolean;
  /**
   * Satırın tamamı tıklanır (ET-03): satırdaki `.satir-baglanti` bağlantısının tıklama alanı satırı (yığın
   * kipinde kartı) kaplar; satır başına tek Tab durağı o bağlantıdır (ET-08). Satırdaki diğer bağlantı ve
   * düğmeler (PR, Triage, kopyala) üstte kalır ve ayrı ayrı tıklanır.
   */
  satirBaglanti?: boolean;
  className?: string;
  tabloClassName?: string;
  testId?: string;
  children: ReactNode;
}) {
  const sarici = ["tablo-sarici", uzun && "tablo-sarici-uzun", className].filter(Boolean).join(" ");
  const tablo = [
    "tablo",
    yogunluk === "sik" && "tablo-sik",
    darEkran === "yigin" ? "tablo-yigin" : "tablo-matris",
    satirBaglanti && "tablo-satir-baglantili",
    tabloClassName,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={sarici} tabIndex={0} role="region" aria-label={etiket} data-testid={testId}>
      <table className={tablo}>{children}</table>
    </div>
  );
}

// ------------------------------------------------------------------ Satır eylemleri (CL-02/CL-03)

export type SatirEylemi = { ad: string; erisilebilirAd?: string; sec: () => void; tur?: "ikincil" | "hayalet" | "tehlike"; pasif?: boolean };

/**
 * Tablo satırının eylemleri tek Tab durağında (CL-03, ET-08): "İşlemler" açılır düğmesi (disclosure,
 * `aria-expanded`) eylemleri satır içinde tek grup olarak açar; Esc kapatır ve odak düğmeye döner. Eylem
 * seçilince grup kapanır, odak düğmeye döner, sonra eylem çalışır (açılan form/onay odağı geri bu düğmeye verir).
 * Eylem sütunu dar kalır (`sutun-eylem`): 1024 px'te gizli sütun bırakmaz (CL-02).
 */
export function SatirEylemleri({ etiket, eylemler }: { etiket: string; eylemler: SatirEylemi[] }) {
  const [acik, setAcik] = useState(false);
  const dugme = useRef<HTMLButtonElement>(null);
  const id = useId();
  if (eylemler.length === 0) return null;
  // Tek eylem açılır gerektirmez: düğme doğrudan çizilir (yine tek durak).
  if (eylemler.length === 1) {
    const e = eylemler[0];
    return (
      <div className="satir-eylemleri">
        <button type="button" className={`dugme dugme-${e.tur ?? "ikincil"} dugme-kucuk`} aria-label={e.erisilebilirAd} disabled={e.pasif} onClick={e.sec}>
          {e.ad}
        </button>
      </div>
    );
  }
  return (
    <div
      className="satir-eylemleri"
      onKeyDown={(e) => {
        if (e.key === "Escape" && acik) {
          e.stopPropagation();
          setAcik(false);
          dugme.current?.focus();
        }
      }}
    >
      <button
        ref={dugme}
        type="button"
        className="dugme dugme-hayalet dugme-kucuk satir-eylemleri-dugme"
        aria-expanded={acik}
        aria-controls={acik ? id : undefined}
        aria-label={`İşlemler: ${etiket}`}
        onClick={() => setAcik((a) => !a)}
      >
        İşlemler <span aria-hidden="true">{acik ? "▴" : "▾"}</span>
      </button>
      {acik && (
        <div id={id} className="satir-eylemleri-liste" role="group" aria-label={`${etiket} işlemleri`}>
          {eylemler.map((e) => (
            <button
              key={e.ad}
              type="button"
              className={`dugme dugme-${e.tur ?? "ikincil"} dugme-kucuk`}
              aria-label={e.erisilebilirAd}
              disabled={e.pasif}
              onClick={() => {
                setAcik(false);
                dugme.current?.focus();
                e.sec();
              }}
            >
              {e.ad}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ Sayfalama

/**
 * Liste sayfalaması (DZ-20, ET-08): "41–60 / 132 olay" + Önceki / sayfa no / Sonraki. Durum adreste
 * (`useSayfalama`, `?sayfa=`). Tek sayfalık listede çizilmez. Sayfa değişince odak tablonun başına
 * taşınmaz; liste başı `hedefId` verilirse oraya kaydırılır (klavye kullanıcısı yeni sayfanın başından okur).
 */
export function Sayfalama({
  sayfa,
  sayfaSayisi,
  toplam,
  boyut,
  git,
  birim = "kayıt",
  hedefId,
  children,
}: {
  sayfa: number;
  sayfaSayisi: number;
  toplam: number;
  boyut: number;
  git: (n: number) => void;
  birim?: string;
  hedefId?: string;
  /** Sayfalamanın yanında ek eylem (ör. "Daha eski olayları yükle"). */
  children?: ReactNode;
}) {
  if (sayfaSayisi <= 1 && !children) return null;
  const bas = toplam === 0 ? 0 : (sayfa - 1) * boyut + 1;
  const son = Math.min(sayfa * boyut, toplam);
  const gec = (n: number) => {
    git(n);
    if (hedefId) document.getElementById(hedefId)?.scrollIntoView?.({ block: "start" });
  };
  // En çok 7 numara: ilk, son, geçerli ±1 ve aralarda "…".
  const numaralar: (number | "…")[] = [];
  for (let n = 1; n <= sayfaSayisi; n++) {
    if (n === 1 || n === sayfaSayisi || Math.abs(n - sayfa) <= 1) numaralar.push(n);
    else if (numaralar[numaralar.length - 1] !== "…") numaralar.push("…");
  }
  return (
    <nav className="sayfalama sayfalama-cubugu" aria-label="Sayfalar" data-testid="sayfalama">
      <span className="sayfalama-ozet" aria-live="polite">
        {bas}–{son} / {toplam} {birim}
      </span>
      {sayfaSayisi > 1 && (
        <span className="sayfalama-dugmeler">
          <button type="button" className="dugme dugme-ikincil dugme-kucuk" disabled={sayfa <= 1} onClick={() => gec(sayfa - 1)}>
            <span aria-hidden="true">‹</span> Önceki
          </button>
          {numaralar.map((n, i) =>
            n === "…" ? (
              <span key={`a${i}`} className="sayfalama-ara" aria-hidden="true">
                …
              </span>
            ) : (
              <button
                key={n}
                type="button"
                className="dugme dugme-hayalet dugme-kucuk sayfalama-no"
                aria-current={n === sayfa ? "page" : undefined}
                aria-label={`Sayfa ${n}`}
                onClick={() => gec(n)}
              >
                {n}
              </button>
            ),
          )}
          <button type="button" className="dugme dugme-ikincil dugme-kucuk" disabled={sayfa >= sayfaSayisi} onClick={() => gec(sayfa + 1)}>
            Sonraki <span aria-hidden="true">›</span>
          </button>
        </span>
      )}
      {children}
    </nav>
  );
}
