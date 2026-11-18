// Detay sayfa iskeleti (DS-1): bütün varlık detay sayfaları (gereksinim, case, koşu, script, hata …)
// aynı düzende çizilir:
//
//   ┌ OzetKarti ─────────────────────────────────────────────┐
//   │ ← geri · kimlik  Başlık                 [eylemler →]  │
//   │ rozetler · meta                                        │
//   │ Sıradaki adım: …                                       │
//   └────────────────────────────────────────────────────────┘
//   [serit]   (ör. kompakt akış adımları şeridi)
//   [ust]     (sayfa geneli uyarılar, açılan formlar)
//   ── Sekme · Sekme (3) · Sekme ──────────────── (role=tablist, yapışkan)
//   ┌ etkin sekmenin paneli (role=tabpanel) ────────────────┐
//
// Sekme seçimi adreste durur: `?sekme=<id>` (paylaşılabilir derin bağlantı). Eski bölüm çapaları
// (`#tasarim-modeli`, `#bulgular` …) sekmenin `capalar` listesindeyse o sekme açılır; Kabuk'un
// `useCapayaKaydir`'ı sonra öğeye kaydırır. Klavye: ←/→ (sarmalı), Home/End; otomatik etkinleştirme
// (WAI-ARIA APG "Tabs with automatic activation"). Paneller tembel çizilir: ilk açılışta bağlanır,
// sonra `hidden` ile saklanır (form ve düzenleyici durumu sekme değişince kaybolmaz).
// Ölçüler styles.css'teki --space-* ölçeğinden (8/12/16/24/32); renkler yalnız mevcut token'lar.
import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { EylemCubugu } from "./tasarim";
import { dugumMetni, useSekmeBasligi } from "./ui";

/** Bir sekmenin tanımı (ana ya da alt düzey). */
export interface DetaySekmesi {
  /** Adresteki değer (`?sekme=<id>`) ve DOM önekli kimliklerin kökü; sayfada tekil, URL güvenli. */
  id: string;
  /** Görünen ad (TR). */
  ad: string;
  /** Ad yanındaki sayı rozeti; `null`/`undefined` → rozet yok, 0 → "0" gösterilir (boş da bilgidir). */
  sayi?: number | null;
  /** Rozetin dikkat çekmesi gerekiyorsa (ör. karar bekleyen engelleyici bulgu): uyarı tonu. */
  dikkat?: boolean;
  /** Bu sekmenin içinde duran eski bölüm çapaları: adres `#<çapa>` taşıyorsa bu sekme açılır. */
  capalar?: readonly string[];
  /** Panel içeriği. İşlev verilirse yalnız sekme ilk açıldığında çağrılır (tembel çizim). */
  icerik: ReactNode | (() => ReactNode);
}

interface SecimAyari {
  /**
   * Seçimin adreste tutulduğu sorgu parametresi (`sekme`, alt düzeyde ör. `model`). `null` → yerel
   * durum (adres değişmez).
   */
  param?: string | null;
  /** Adreste geçerli seçim yokken açılan sekme; yoksa ilk sekme. */
  varsayilan?: string;
}

/**
 * Etkin sekmeyi adresten türetir: (1) hash bir sekmenin `capalar`ında ya da bir sekmenin kimliğiyse o
 * sekme, (2) `?<param>=<id>`, (3) `varsayilan`, (4) ilk sekme. `sec(id)` seçimi adrese yazar (`replace`;
 * hash temizlenir ki eski çapa seçimi ezmesin).
 */
export function useSekmeSecimi(sekmeler: readonly Pick<DetaySekmesi, "id" | "capalar">[], { param = "sekme", varsayilan }: SecimAyari = {}) {
  const konum = useLocation();
  const git = useNavigate();
  const [yerel, setYerel] = useState<string | null>(null);
  const var_ = (id: string | null | undefined): id is string => !!id && sekmeler.some((s) => s.id === id);

  let aktif: string | undefined;
  let hashten: string | undefined;
  const parametre = param ? new URLSearchParams(konum.search).get(param) : null;
  if (param) {
    const hash = cozHash(konum.hash);
    if (hash) hashten = aktif = sekmeler.find((s) => s.id === hash || s.capalar?.includes(hash))?.id;
    if (!aktif && var_(parametre)) aktif = parametre;
  } else if (var_(yerel)) {
    aktif = yerel;
  }
  if (!aktif) aktif = var_(varsayilan) ? varsayilan : sekmeler[0]?.id;

  // Çapadan açılan sekme parametreye de yazılır (hash korunur): alt düzey bir seçim hash'i temizlediğinde
  // üst sekme varsayılana dönmesin.
  useEffect(() => {
    if (!param || !hashten || parametre === hashten) return;
    const ara = new URLSearchParams(konum.search);
    ara.set(param, hashten);
    git({ pathname: konum.pathname, search: `?${ara.toString()}`, hash: konum.hash }, { replace: true });
  }, [param, hashten, parametre, konum.search, konum.pathname, konum.hash, git]);

  const sec = useCallback(
    (id: string) => {
      if (!param) return setYerel(id);
      const ara = new URLSearchParams(konum.search);
      ara.set(param, id);
      git({ pathname: konum.pathname, search: `?${ara.toString()}`, hash: "" }, { replace: true });
    },
    [param, konum.search, konum.pathname, git],
  );
  return { aktif: aktif ?? "", sec };
}

function cozHash(h: string): string {
  const ham = h.replace(/^#/, "");
  if (!ham) return "";
  try {
    return decodeURIComponent(ham);
  } catch {
    return "";
  }
}

/**
 * Sekme listesi + panelleri (ana ya da alt düzey). Erişilebilirlik: role=tablist/tab/tabpanel,
 * aria-selected, aria-controls ↔ aria-labelledby, gezici tabindex. Liste dar ekranda yatay kayar
 * (sayfa kaymaz); etkin sekme görünür alana getirilir.
 */
export function Sekmeler({
  etiket,
  sekmeler,
  aktif,
  sec,
  duzey = "ana",
  tembel = true,
  yapiskan = duzey === "ana",
  testId,
}: {
  /** tablist'in erişilebilir adı (ör. "Gereksinim bölümleri"). */
  etiket: string;
  sekmeler: readonly DetaySekmesi[];
  aktif: string;
  sec: (id: string) => void;
  /** "ana": alt çizgili sekme şeridi; "alt": kart içi segment (hap) düğmeleri. */
  duzey?: "ana" | "alt";
  /** true: panel ilk açılışta bağlanır, sonra saklanır. false: hepsi baştan çizilir (gizli). */
  tembel?: boolean;
  /** Şerit üst çubuğun altında yapışkan (yalnız ana düzey, ≥641 px). */
  yapiskan?: boolean;
  testId?: string;
}) {
  const kok = useId().replace(/:/g, "");
  const listeRef = useRef<HTMLDivElement>(null);
  const [acilmis, setAcilmis] = useState<ReadonlySet<string>>(() => new Set([aktif]));
  useEffect(() => {
    setAcilmis((a) => (a.has(aktif) ? a : new Set(a).add(aktif)));
  }, [aktif]);
  // Etkin sekme yatay kayan şeritte görünür kalsın (dar ekran, derin bağlantı).
  useEffect(() => {
    const el = listeRef.current?.querySelector<HTMLElement>('[aria-selected="true"]');
    const liste = listeRef.current;
    if (!el || !liste || liste.scrollWidth <= liste.clientWidth) return;
    liste.scrollLeft = Math.max(0, el.offsetLeft - liste.clientWidth / 2 + el.offsetWidth / 2);
  }, [aktif]);

  const sekmeId = (id: string) => `${kok}-sekme-${id}`;
  const panelId = (id: string) => `${kok}-panel-${id}`;

  const secVeOdakla = (id: string) => {
    sec(id);
    requestAnimationFrame(() => document.getElementById(sekmeId(id))?.focus());
  };
  const tus = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const n = sekmeler.length;
    const hedef =
      e.key === "ArrowRight" ? (i + 1) % n : e.key === "ArrowLeft" ? (i - 1 + n) % n : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : -1;
    if (hedef < 0) return;
    e.preventDefault();
    secVeOdakla(sekmeler[hedef].id);
  };

  return (
    <div className={`ds-sekmeler ds-sekmeler-${duzey}`} data-testid={testId}>
      <div className={`ds-sekme-serit${yapiskan && duzey === "ana" ? " ds-sekme-serit-yapiskan" : ""}`}>
        <div ref={listeRef} role="tablist" aria-label={etiket} className="ds-sekme-liste">
          {sekmeler.map((s, i) => {
            const secili = s.id === aktif;
            return (
              <button
                key={s.id}
                type="button"
                role="tab"
                id={sekmeId(s.id)}
                aria-selected={secili}
                aria-controls={panelId(s.id)}
                tabIndex={secili ? 0 : -1}
                className={duzey === "alt" ? `sekme${secili ? " aktif" : ""}` : "ds-sekme"}
                data-sekme={s.id}
                onClick={() => sec(s.id)}
                onKeyDown={(e) => tus(e, i)}
              >
                {s.ad}
                {s.sayi != null && <Sayac sayi={s.sayi} dikkat={s.dikkat} />}
              </button>
            );
          })}
        </div>
      </div>
      {sekmeler.map((s) => {
        const secili = s.id === aktif;
        const ciz = !tembel || secili || acilmis.has(s.id);
        return (
          <div
            key={s.id}
            role="tabpanel"
            id={panelId(s.id)}
            aria-labelledby={sekmeId(s.id)}
            hidden={!secili}
            className="ds-panel"
            data-panel={s.id}
          >
            {ciz && (typeof s.icerik === "function" ? (s.icerik as () => ReactNode)() : s.icerik)}
          </div>
        );
      })}
    </div>
  );
}

/** Kırıntının bir halkası: `yol` verilirse bağlantı; son halka (bulunulan sayfa) yolsuz yazılır. */
export interface KirintiHalkasi {
  ad: ReactNode;
  yol?: string | null;
}

/**
 * Kırıntı gezinme (IA-22): `Gereksinimler › TPD-1 › Case review`. Bütün detay sayfaları aynı biçimi kullanır
 * (eski "← Liste" geri bağlantılarının yerine). Son halka `aria-current="page"`; yolsuz ara halka düz metin.
 */
export function Kirinti({ halkalar, testId = "kirinti" }: { halkalar: readonly KirintiHalkasi[]; testId?: string }) {
  return (
    <nav className="ds-kirinti" aria-label="Kırıntı" data-testid={testId}>
      <ol>
        {halkalar.map((h, i) => {
          const son = i === halkalar.length - 1;
          return (
            <li key={i} aria-current={son ? "page" : undefined}>
              {h.yol && !son ? <Link to={h.yol}>{h.ad}</Link> : <span>{h.ad}</span>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/**
 * Detay sayfasının üst kartı: kırıntı (+ ilgili sayfa bağlantıları), kimlik + başlık (h1), durum rozetleri, meta
 * satırı, tek "Sıradaki adım" ve sağda eylemler (EylemCubugu: kilitli düğme aria-disabled, nedeni okunur). ≤960 px'te
 * eylemler başlığın altına yığılır (sağa yaslı kalır).
 */
export function OzetKarti({
  kirinti,
  ust,
  kimlik,
  baslik,
  rozetler,
  meta,
  siradaki,
  eylemler,
  sekme,
  testId = "ozet-karti",
}: {
  /** Kırıntı halkaları (IA-22); son halka bu sayfa. */
  kirinti?: readonly KirintiHalkasi[];
  /** Kırıntının sağında ilgili sayfa bağlantıları (ör. Karar tabloları). Kırıntı yoksa geri bağlantısı. */
  ust?: ReactNode;
  /** Kısa kimlik (ör. Jira anahtarı TPD-1, case #3); tek aralıklı yazılır. */
  kimlik?: ReactNode;
  baslik: ReactNode;
  /** Durum çipleri (DurumCipi / Cip). */
  rozetler?: ReactNode;
  /** İkincil bilgiler (kaynak, dış bağlantı, tarih) — MetaSatiri ya da "·" ayraçlı span'ler. */
  meta?: ReactNode;
  /** "Sıradaki adım" metni (tek satır; bağlantı içerebilir). */
  siradaki?: ReactNode;
  eylemler?: ReactNode;
  /** Tarayıcı sekmesi başlığındaki sayfa adı (IA-11); verilmezse h1'in düz metni (kimlik + başlık). */
  sekme?: string;
  testId?: string;
}) {
  useSekmeBasligi(sekme ?? `${kimlik ? `${dugumMetni(kimlik)} ` : ""}${dugumMetni(baslik)}`);
  return (
    // `sayfa-basligi`: eylem grubu ve pasiflik nedeni yerleşimi sayfa başlığıyla aynı kurallardan (sağa yaslı,
    // neden düğmenin altında; styles.css ".sayfa-basligi > .eylemler").
    <header className="kart ds-ozet sayfa-basligi" data-testid={testId}>
      <div className="ds-ozet-govde">
        {(kirinti || ust) && (
          <div className="ds-ozet-ust">
            {kirinti && <Kirinti halkalar={kirinti} />}
            {ust && <div className="ust-baglanti">{ust}</div>}
          </div>
        )}
        <h1 className="ds-ozet-baslik">
          {kimlik && (
            <>
              <span className="mono baslik-anahtar">{kimlik}</span>{" "}
            </>
          )}
          {baslik}
        </h1>
        {(rozetler || meta) && (
          <div className="ds-ozet-satir">
            {rozetler && <span className="satir-ogeler">{rozetler}</span>}
            {meta && <span className="satir-ogeler soluk">{meta}</span>}
          </div>
        )}
        {siradaki && (
          <p className="ds-siradaki" data-testid="siradaki-adim">
            <strong>Sıradaki adım:</strong> {siradaki}
          </p>
        )}
      </div>
      {eylemler && (
        <EylemCubugu hiza="son" etiket="Sayfa eylemleri" className="ds-ozet-eylemler">
          {eylemler}
        </EylemCubugu>
      )}
    </header>
  );
}

/**
 * Sayfa iskeleti: özet kartı + şerit + üst alan + ana sekmeler. Sekme seçimi `?sekme=`'de
 * (bkz. `useSekmeSecimi`); `varsayilanSekme` sayfanın durumuna göre seçilebilir (ör. bulgular açıkken
 * "Tutarlılık"). Adreste seçim yokken varsayılan, kullanıcı sekme alanında bir şeye dokunana (tıklama,
 * tuş) kadar `varsayilanSekme`'yi izler (ör. özetteki "Model üret" sonrası model sekmesi açılır); dokunduktan
 * sonra o anki sekme sabitlenir — kendi eylemi durumu değiştirince kullanıcı bulunduğu sekmeden koparılmaz.
 * Farklı varlığa geçişte bileşen `key` ile yeniden kurulmalıdır (ör. `key={id}`).
 */
export function DetaySayfasi({
  ozet,
  serit,
  ust,
  sekmeler,
  sekmeEtiketi,
  varsayilanSekme,
  param = "sekme",
}: {
  ozet: ReactNode;
  serit?: ReactNode;
  ust?: ReactNode;
  sekmeler: readonly DetaySekmesi[];
  sekmeEtiketi: string;
  varsayilanSekme?: string;
  param?: string;
}) {
  const [sabit, setSabit] = useState<string | null>(null);
  const { aktif, sec } = useSekmeSecimi(sekmeler, { param, varsayilan: sabit ?? varsayilanSekme });
  const sabitle = () => {
    if (sabit === null) setSabit(aktif);
  };
  return (
    <div className="ds-sayfa">
      {ozet}
      {serit && <div className="ds-serit">{serit}</div>}
      {ust && <div className="ds-ust">{ust}</div>}
      <div className="ds-sekme-alani" onPointerDownCapture={sabitle} onKeyDownCapture={sabitle}>
        <Sekmeler etiket={sekmeEtiketi} sekmeler={sekmeler} aktif={aktif} sec={sec} testId="detay-sekmeleri" />
      </div>
    </div>
  );
}

/**
 * Sayı rozeti (sekme ve segment adlarının yanında). Erişilebilir adda "Ad (3)" okunur; görsel olarak hap.
 * Segment/süzgeç düğmelerindeki "(15)" metni de bununla çizilir.
 */
export function Sayac({ sayi, dikkat }: { sayi: number; dikkat?: boolean }) {
  return (
    <span className={`ds-sayi${dikkat ? " ds-sayi-dikkat" : ""}`}>
      <span className="gorunmez"> (</span>
      {sayi}
      <span className="gorunmez">)</span>
    </span>
  );
}
