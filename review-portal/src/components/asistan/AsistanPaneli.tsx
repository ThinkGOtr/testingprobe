// Portal asistan paneli (AI-ASISTAN-PLANI §11): sağ altta "Asistan" düğmesi; masaüstünde
// modal olmayan 420 px bindirme (`role="complementary"`), < 760 px tam ekran modal. İki sekme:
// "Sohbet" | "Öneriler" (Öneriler içeriği Öneri şeridinin `OnerilerSekmesi` bileşeni).
// App.tsx'te `OturumGerekli` içinde Kabuk'un kardeşi olarak çizilir (OlayProvider içinde, /giris'te yok);
// rota parametrelerini `useEkranBaglami` (useLocation + matchPath) ile okur.
import "./asistan.css";
// Oturum temizliği ana pakette: içerik modülleri hiç yüklenmeden çıkış yapılsa da kayıtlı anahtarlar silinir.
import "./oturumAnahtarlari";
import { Component, lazy, Suspense, useCallback, useEffect, useId, useRef, useState, type ComponentType, type ReactNode, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent } from "react";
import { api } from "../../api/client";
import { mockZorunlu } from "../../api/http";
import { useEkranBaglami, type EkranBaglami } from "../../lib/ekranBaglami";
import { Ikon } from "../Ikon";
import { DegerlendirmeNotu, Uyari, Yukleniyor } from "../ui";
import { elemanTanimi, noktadakiOge, yakalanabilirMi, type SeciliEleman } from "./buNe";
import { ekranAnahtariUret, ekranDegisti, istegiTuket, paneliAc, paneliKapat, panelHazirAyarla, sekmeSec, useAsistanKontrol, type AsistanSekmesi } from "./kontrol";
import type { OnerilerSekmesiOzellikleri } from "./OnerilerSekmesi";
import type { SohbetSekmesiOzellikleri } from "./SohbetSekmesi";
import { useAsistanKapisi } from "./yetenek";

export const DAR_EKRAN_PX = 760;

// Panel içeriği (Sohbet / Öneriler sekmeleri, cevap ve öneri kartları) ayrı parçadadır: panel kapalıyken
// ana pakete girmez; ilk açılışta (ya da başlatıcının üzerine gelinince / odaklanınca) yüklenir. Stiller
// (asistan.css, oneri.css) başlatıcı ve Öneri düğmesiyle ana pakette kalır: yükleme sırası değişmez.
// Yüklendikten sonra `lazy` eş zamanlı bir thenable alır ve askıya almadan çizer (testler önceden yükler).
type Icerik = { Sohbet: ComponentType<SohbetSekmesiOzellikleri>; Oneriler: ComponentType<OnerilerSekmesiOzellikleri> };
let icerik: Icerik | null = null;
let icerikYukleniyor: Promise<void> | null = null;

/** Parçaların dinamik içe aktarımı; testler yükleme hatasını taklit etmek için değiştirebilir. */
export const icerikYukleyici = {
  yukle: () => Promise.all([import("./SohbetSekmesi"), import("./OnerilerSekmesi")]),
};

/** Panel içerik parçasını yükler (bir kez); yükleme hatasında sonraki çağrı yeniden ister. */
export function asistanIceriginiYukle(): Promise<void> {
  icerikYukleniyor ??= icerikYukleyici.yukle().then(
    ([s, o]) => {
      icerik = { Sohbet: s.SohbetSekmesi, Oneriler: o.OnerilerSekmesi };
    },
    (e: unknown) => {
      icerikYukleniyor = null;
      throw e;
    },
  );
  return icerikYukleniyor;
}

function tembel<P>(sec: (i: Icerik) => ComponentType<P>) {
  return lazy<ComponentType<P>>(() => {
    if (icerik) {
      const c = sec(icerik);
      return { then: (coz: (m: { default: ComponentType<P> }) => void) => coz({ default: c }) } as Promise<{ default: ComponentType<P> }>;
    }
    return asistanIceriginiYukle().then(() => ({ default: sec(icerik!) }));
  });
}

// `lazy` reddi önbelleğe alır: yükleme hatasından sonra "Yeniden dene" yeni bileşenlerle ister.
const tembelSekmeler = () => ({ Sohbet: tembel((i) => i.Sohbet), Oneriler: tembel((i) => i.Oneriler) });
let sekmeler = tembelSekmeler();

/** İçerik parçası yüklenemezse (ağ kopukluğu, yeni sürümden sonra kalkmış eski parça) uygulama düşmez:
 * panel içinde hata ve yeniden deneme. */
class IcerikSiniri extends Component<{ children: ReactNode; yenidenDene: () => void }, { hata: boolean }> {
  state = { hata: false };
  static getDerivedStateFromError() {
    return { hata: true };
  }
  render() {
    if (!this.state.hata) return this.props.children;
    return (
      <Uyari ton="hata" baslik="Asistan yüklenemedi">
        Bağlantıyı denetleyip yeniden deneyin.{" "}
        <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={this.props.yenidenDene}>
          Yeniden dene
        </button>
      </Uyari>
    );
  }
}
const onYukle = () => void asistanIceriginiYukle().catch(() => undefined);

/** Pasif asistan (ör. `worker_yok`) panel açıkken bu aralıkla yeniden okunur (testler kısaltabilir). */
export const panelAyar = { pasifYoklamaMs: 30_000 };

const ODAKLANABILIR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

function darEkranMi(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(`(max-width: ${DAR_EKRAN_PX - 1}px)`).matches;
}

function useDarEkran(): boolean {
  const [dar, setDar] = useState(darEkranMi);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(`(max-width: ${DAR_EKRAN_PX - 1}px)`);
    const fn = () => setDar(mq.matches);
    mq.addEventListener?.("change", fn);
    return () => mq.removeEventListener?.("change", fn);
  }, []);
  return dar;
}

/** Gereksinim ekranlarında Jira anahtarı (TPD-3) çipte gösterilir; yalnız panel açıkken okunur. */
function useVarlikAnahtari(ekran: EkranBaglami, acik: boolean): string | null {
  const [anahtar, setAnahtar] = useState<{ id: string; anahtar: string | null } | null>(null);
  const id = ekran.varlik?.tur === "requirement" ? ekran.varlik.id : null;
  useEffect(() => {
    if (!acik || !id || anahtar?.id === id) return;
    let iptal = false;
    api
      .gereksinim(id)
      .then((g) => !iptal && setAnahtar({ id, anahtar: g.jira_key ?? null }))
      .catch(() => !iptal && setAnahtar({ id, anahtar: null }));
    return () => {
      iptal = true;
    };
  }, [acik, id, anahtar?.id]);
  return id && anahtar?.id === id ? anahtar.anahtar : null;
}

interface Vurgu {
  x: number;
  y: number;
  w: number;
  h: number;
}

export function AsistanPaneli() {
  const { kapi, yenile } = useAsistanKapisi();
  const kontrol = useAsistanKontrol();
  const dar = useDarEkran();
  const ekranHam = useEkranBaglami();
  const anahtar = useVarlikAnahtari(ekranHam, kontrol.acik);
  const ekran: EkranBaglami = ekranHam.varlik ? { ...ekranHam, varlik: { ...ekranHam.varlik, anahtar } } : ekranHam;
  const [buNe, setBuNe] = useState(false);
  const [buNeMesaji, setBuNeMesaji] = useState<string | null>(null);
  const [vurgu, setVurgu] = useState<Vurgu | null>(null);
  const [secili, setSecili] = useState<SeciliEleman | null>(null);
  const bindirmeRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const baslikRef = useRef<HTMLHeadingElement>(null);
  const baslaticiRef = useRef<HTMLButtonElement>(null);
  // u2 N17: sayfa kaydırılınca başlatıcı yalnız ikona küçülür (geniş düğme sağ sütunu ve son eylemleri örtüyordu);
  // sayfa tepesinde görünür adıyla kalır.
  const [kaydirildi, setKaydirildi] = useState(false);
  useEffect(() => {
    const izle = () => setKaydirildi(window.scrollY > 64);
    izle();
    window.addEventListener("scroll", izle, { passive: true });
    return () => window.removeEventListener("scroll", izle);
  }, []);
  /** Panel dışında en son odaklanan öğe: kapanınca odak oraya (yoksa başlatıcıya) döner. */
  const disOdakRef = useRef<HTMLElement | null>(null);
  const oncekiAcik = useRef(kontrol.acik);
  /** "Bu ne?" bir seçimle bitti: panel geri gelince odak soru alanına verilir. */
  const secimYapildi = useRef(false);
  const oncekiBuNe = useRef(false);
  const baslikId = useId();
  const nedenId = useId();
  /** İçerik yükleme denemesi: artınca hata sınırı sıfırlanır, sekmeler yeniden istenir. */
  const [icerikDenemesi, setIcerikDenemesi] = useState(0);
  /** "Yeniden dene" sınırla birlikte DOM'dan kalkar: odak body'ye düşmesin, panel başlığına verilir. */
  const odagiBasligaVer = useRef(false);
  const icerikYenidenDene = useCallback(() => {
    sekmeler = tembelSekmeler();
    odagiBasligaVer.current = true;
    setIcerikDenemesi((d) => d + 1);
  }, []);
  useEffect(() => {
    if (!odagiBasligaVer.current) return;
    odagiBasligaVer.current = false;
    const aktif = document.activeElement;
    if (!aktif || aktif === document.body || !aktif.isConnected) baslikRef.current?.focus();
  }, [icerikDenemesi]);
  const { Sohbet: SohbetSekmesi, Oneriler: OnerilerSekmesi } = sekmeler;

  // "Bu ne?" seçimi o ekrana aittir: rota/varlık değişince önceki ekranın öğesi yeni bağlamla gitmesin.
  useEffect(() => setSecili(null), [ekranHam.rota_kalibi, ekranHam.varlik?.id]);
  // Ekran çipi tercihi o ekrana aittir; Sohbet sekmesi çizili olmasa da rota değişince düşer.
  const ekranAnahtari = ekranAnahtariUret(ekranHam);
  useEffect(() => ekranDegisti(ekranAnahtari), [ekranAnahtari]);

  const hazir = kapi.tur === "hazir";
  // Pasifken durum yalnız ilk yüklemede okunsaydı worker sonradan gelse de panel sayfa yenilenene
  // kadar "kullanılamıyor" kalırdı: panel açılınca ve açık kaldıkça periyodik olarak yeniden okunur.
  const pasifAcik = kapi.tur === "pasif" && kontrol.acik;
  useEffect(() => {
    if (!pasifAcik) return;
    void yenile();
    const z = setInterval(() => void yenile(), panelAyar.pasifYoklamaMs);
    return () => clearInterval(z);
  }, [pasifAcik, yenile]);
  useEffect(() => {
    panelHazirAyarla(hazir);
    return () => panelHazirAyarla(false);
  }, [hazir]);

  const buNeBitir = useCallback(() => {
    setBuNe(false);
    setVurgu(null);
    setBuNeMesaji(null);
  }, []);

  /** "Bu ne?" kipinde bir öğe seçildi (fare ya da klavye): tanım bağlama girer, Sohbet açılır. */
  const ogeSec = useCallback(
    (sonuc: Element | "gizli" | null) => {
      if (sonuc === "gizli") {
        setBuNeMesaji("Bu öğe asistana gönderilmez (giriş alanı, kod ya da gizli içerik). Başka bir öğe seçin.");
        return;
      }
      const tanim = sonuc ? elemanTanimi(sonuc) : null;
      if (!tanim) {
        setBuNeMesaji("Burada tanımlanabilir bir öğe yok. Bir düğmeye, başlığa ya da etikete tıklayın.");
        return;
      }
      setSecili(tanim);
      secimYapildi.current = true;
      buNeBitir();
      sekmeSec("sohbet");
      paneliAc();
    },
    [buNeBitir],
  );

  // Esc: önce "Bu ne?"den çıkar (belge düzeyinde; bindirme odak almaz). Klavye yolu: kip açıkken
  // Tab ile sayfadaki öğeye gidilip Enter'a basılınca odaktaki öğe seçilir (panel içi hariç).
  useEffect(() => {
    if (!buNe) return;
    const fn = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        // Yayılım durdurulur: gerçek tarayıcıda dinleyiciler arasında mikro görev çalışır, React
        // buNe=false ile yeniden çizer ve panelin onKeyDown'u aynı Esc ile paneli de kapatırdı.
        e.preventDefault();
        e.stopPropagation();
        buNeBitir();
        return;
      }
      if (e.key !== "Enter" || e.defaultPrevented) return;
      const aktif = document.activeElement;
      if (!aktif || aktif === document.body || aktif === document.documentElement) return;
      if (panelRef.current?.contains(aktif) || bindirmeRef.current?.contains(aktif)) return;
      e.preventDefault();
      e.stopPropagation();
      ogeSec(yakalanabilirMi(aktif) ? aktif : "gizli");
    };
    // Yakalama evresinde: odaktaki düğmenin kendi Enter davranışı (tıklama) tetiklenmesin.
    document.addEventListener("keydown", fn, true);
    return () => document.removeEventListener("keydown", fn, true);
  }, [buNe, buNeBitir, ogeSec]);

  // Panel dışındaki son odak (başlatıcı, Öneri düğmesi, "Asistana sor"): kapanınca geri verilir.
  useEffect(() => {
    const fn = (e: FocusEvent) => {
      const t = e.target;
      if (t instanceof HTMLElement && !panelRef.current?.contains(t)) disOdakRef.current = t;
    };
    document.addEventListener("focusin", fn);
    return () => document.removeEventListener("focusin", fn);
  }, []);

  // Açılınca odak panele (içeride zaten odak yoksa başlığa; "Asistana sor" girdiyi odaklar),
  // kapanınca açan öğeye döner. Yalnız geçişlerde: sayfa yenilenip panel açık gelirse odak çalınmaz.
  useEffect(() => {
    const once = oncekiAcik.current;
    oncekiAcik.current = kontrol.acik;
    if (kontrol.acik && !once) {
      const p = panelRef.current;
      if (p && !p.contains(document.activeElement)) baslikRef.current?.focus();
    } else if (!kontrol.acik && once) {
      const hedef = disOdakRef.current;
      if (hedef && hedef.isConnected && hedef !== document.body) hedef.focus();
      else baslaticiRef.current?.focus();
    }
  }, [kontrol.acik]);

  // Dar ekran (modal dialog): Esc belge düzeyinde kapatır, Tab odağı panel içinde tutar.
  const modalAktif = dar && kontrol.acik && !buNe;
  useEffect(() => {
    if (!modalAktif) return;
    const fn = (e: KeyboardEvent) => {
      const p = panelRef.current;
      // İç modal (alıntı) tuşu kendisi işlediyse dokunulmaz.
      if (!p || e.defaultPrevented) return;
      if (e.key === "Escape") {
        e.preventDefault();
        paneliKapat();
        return;
      }
      if (e.key !== "Tab") return;
      const ogeler = Array.from(p.querySelectorAll<HTMLElement>(ODAKLANABILIR)).filter((el) => el.tabIndex >= 0 && !el.hasAttribute("hidden"));
      if (ogeler.length === 0) {
        e.preventDefault();
        baslikRef.current?.focus();
        return;
      }
      const ilk = ogeler[0];
      const son = ogeler[ogeler.length - 1];
      const aktif = document.activeElement;
      if (!p.contains(aktif)) {
        e.preventDefault();
        (e.shiftKey ? son : ilk).focus();
      } else if (e.shiftKey && (aktif === ilk || aktif === baslikRef.current)) {
        e.preventDefault();
        son.focus();
      } else if (!e.shiftKey && aktif === son) {
        e.preventDefault();
        ilk.focus();
      }
    };
    document.addEventListener("keydown", fn);
    return () => document.removeEventListener("keydown", fn);
  }, [modalAktif]);

  // Masaüstü (modal değil): panel sayfanın üstünde durur. ≥1440 px'te içerik panel kadar sağdan boşaltılır
  // (asistan.css); daha dar ekranda odaktaki sayfa öğesi panelin altında kalabilir (WCAG 2.4.11). Esc,
  // odak paneldeyken panelTus'la kapatır; odak panelin ALTINDAKİ bir sayfa öğesindeyse de kapatır —
  // kullanıcı odağı taşımadan öğeyi açığa çıkarır. Başka Esc dinleyicisi işlediyse dokunulmaz.
  const ortmeEscAktif = !dar && kontrol.acik && !buNe;
  useEffect(() => {
    if (!ortmeEscAktif) return;
    const fn = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      const p = panelRef.current;
      const aktif = document.activeElement;
      if (!p || !(aktif instanceof HTMLElement) || p.contains(aktif)) return;
      const pr = p.getBoundingClientRect();
      const r = aktif.getBoundingClientRect();
      if (pr.width === 0 || r.width === 0 || r.right <= pr.left || r.bottom <= pr.top) return;
      e.preventDefault();
      // Kapanışta odak geri dönüşü bu öğeyi hedefler: odak yerinde kalır (başlatıcıya taşınmaz).
      disOdakRef.current = aktif;
      paneliKapat();
    };
    document.addEventListener("keydown", fn);
    return () => document.removeEventListener("keydown", fn);
  }, [ortmeEscAktif]);

  // Dar ekran modalı: arka plan (panelin atalarının kardeşleri) `inert` ve sayfa kaydırması kilitli;
  // ekran okuyucunun sanal imleci arka plana kaçmasın, mobilde arka plan kaymasın. Kapanınca geri alınır.
  // Bildirim canlı bölgesi (`.bildirimler`) hariç: panelin "Kopyalandı/Gizlendi" durumları duyurulmalı.
  useEffect(() => {
    if (!modalAktif) return;
    const p = panelRef.current;
    if (!p) return;
    const degisenler: Element[] = [];
    for (let el: Element | null = p; el && el !== document.body; el = el.parentElement) {
      const ust: HTMLElement | null = el.parentElement;
      if (!ust) break;
      for (const kardes of Array.from<Element>(ust.children)) {
        if (kardes === el || kardes.hasAttribute("inert") || kardes.tagName === "SCRIPT" || kardes.classList.contains("bildirimler")) continue;
        kardes.setAttribute("inert", "");
        degisenler.push(kardes);
      }
    }
    const oncekiTasma = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      degisenler.forEach((el) => el.removeAttribute("inert"));
      document.body.style.overflow = oncekiTasma;
    };
  }, [modalAktif]);

  // "Bu ne?" bitince odak panele döner: dar ekranda kip açılınca panel (ve odaktaki "? Bu ne?")
  // DOM'dan kalkar, geri gelince odak body'de kalırdı. Seçim yapıldıysa soru alanına, yoksa düğmeye.
  useEffect(() => {
    const once = oncekiBuNe.current;
    oncekiBuNe.current = buNe;
    if (!once || buNe) return;
    const secildi = secimYapildi.current;
    secimYapildi.current = false;
    const p = panelRef.current;
    if (!p || !kontrol.acik) return;
    const hedef = p.querySelector<HTMLElement>(secildi ? "#asistan-soru" : ".asistan-bune-dugmesi");
    hedef?.focus();
  }, [buNe, kontrol.acik]);

  const atla = useCallback((el: Element) => el === bindirmeRef.current || !!bindirmeRef.current?.contains(el), []);

  const bindirmeTikla = (e: ReactMouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    ogeSec(noktadakiOge(e.clientX, e.clientY, atla));
  };

  const bindirmeHareket = (e: ReactMouseEvent) => {
    const sonuc = noktadakiOge(e.clientX, e.clientY, atla);
    if (!sonuc || sonuc === "gizli") {
      setVurgu(null);
      return;
    }
    const r = sonuc.getBoundingClientRect();
    setVurgu({ x: r.left, y: r.top, w: r.width, h: r.height });
  };

  // Sohbet çizilemiyorsa (asistan pasif ya da ucu yok) Sohbet'e yönelik dış istek tüketilir:
  // depoda kalıp asistan hazıra dönünce kullanıcı bir şey yapmadan eski soru gönderilmesin.
  const istekSirasi = kontrol.istek?.sekme === "sohbet" ? kontrol.istek.sira : null;
  useEffect(() => {
    if (istekSirasi !== null && (kapi.tur === "pasif" || kapi.tur === "gizli")) istegiTuket(istekSirasi);
  }, [istekSirasi, kapi.tur]);

  if (kapi.tur === "yukleniyor") return null;
  // Asistan ucu yok: düğme gizli; Öneri düğmesi paneli Öneriler sekmesinde yine açabilir.
  const yalnizOneri = kapi.tur === "gizli";
  if (yalnizOneri && !(kontrol.acik && kontrol.sekme === "oneriler")) return null;

  const asistan = kapi.tur === "hazir" || kapi.tur === "pasif" ? kapi.asistan : null;
  const pasifNeden = kapi.tur === "pasif" ? kapi.neden : null;
  const sekme: AsistanSekmesi = yalnizOneri ? "oneriler" : kontrol.sekme;
  const panelGorunur = kontrol.acik && !(dar && buNe);
  const onGit = dar ? paneliKapat : undefined;

  const panelTus = (e: ReactKeyboardEvent) => {
    // Dar ekranda Esc belge düzeyinde dinlenir (modalAktif).
    // Esc'i başka bir dinleyici (ör. "Bu ne?" kipinden çıkış) işlediyse panel kapanmaz.
    if (e.key === "Escape" && !buNe && !dar && !e.nativeEvent.defaultPrevented) {
      e.preventDefault();
      paneliKapat();
    }
  };

  const sekmeDugmesi = (s: AsistanSekmesi, ad: string) => (
    <button
      type="button"
      role="tab"
      id={`asistan-sekme-${s}`}
      aria-selected={sekme === s}
      // Yalnız seçili sekmenin paneli DOM'da: aria-controls var olmayan id'ye işaret etmesin.
      aria-controls={sekme === s ? `asistan-sekme-icerik-${s}` : undefined}
      tabIndex={sekme === s ? 0 : -1}
      className={`asistan-sekme${sekme === s ? " aktif" : ""}`}
      onClick={() => sekmeSec(s)}
      onKeyDown={(e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          const diger: AsistanSekmesi = s === "sohbet" ? "oneriler" : "sohbet";
          sekmeSec(diger);
          document.getElementById(`asistan-sekme-${diger}`)?.focus();
        }
      }}
    >
      {ad}
    </button>
  );

  return (
    <>
      {!yalnizOneri && !kontrol.acik && (
        // Kap yalnız konum içindir (sağ alt). Pasifken neden portalın pasiflik dilinde düğmenin DIŞINDA,
        // solunda görünür yazılır (.dugme-neden; dokunmatikte ve klavyede title okunmaz) ve
        // aria-describedby ile bağlıdır; düğme yine tıklanır, panel nedeni uyarıda da gösterir.
        <div className="asistan-baslatici-kap" data-asistan-gizli>
          {pasifNeden && (
            <p id={nedenId} className="dugme-neden asistan-baslatici-neden">
              {pasifNeden}
            </p>
          )}
          <button
            ref={baslaticiRef}
            type="button"
            className={`asistan-baslatici${pasifNeden ? " pasif" : ""}${kaydirildi ? " kucuk" : ""}`}
            data-asistan-gizli
            title={pasifNeden ?? "Asistanı aç"}
            aria-label={pasifNeden ? "Asistan (kapalı)" : "Asistanı aç"}
            aria-describedby={pasifNeden ? nedenId : undefined}
            onPointerEnter={onYukle}
            onFocus={onYukle}
            onClick={() => {
              // Pasifken de açılır: neden Sohbet sekmesindeki uyarıda da görünür.
              sekmeSec("sohbet");
              paneliAc();
            }}
          >
            {/* Görünür ad erişilebilir adın içinde (WCAG 2.5.3); dar/kısa ekranda gizlenir (yalnız ikon, asistan.css). */}
            <Ikon ad="asistan" />
            <span className="asistan-baslatici-metin">{pasifNeden ? "Asistan" : "Asistanı aç"}</span>
          </button>
        </div>
      )}

      {buNe && (
        <div
          ref={bindirmeRef}
          className="asistan-bune-bindirme"
          data-testid="asistan-bune-bindirme"
          onClick={bindirmeTikla}
          onMouseMove={bindirmeHareket}
        >
          {vurgu && <div className="asistan-bune-vurgu" style={{ left: vurgu.x, top: vurgu.y, width: vurgu.w, height: vurgu.h }} />}
          <div className="asistan-bune-ipucu" role="status" onClick={(e) => e.stopPropagation()}>
            {/* Metin tek akışta (flex öğesi tek): mesaj ve klavye ipucu satır içinde sarar, "Vazgeç" sağda. */}
            <span className="asistan-bune-metin">
              {buNeMesaji ?? "Sormak istediğiniz öğeye tıklayın."}{" "}
              <span className="soluk">Klavyeyle: Tab ile öğeye gidip Enter'a basın (pasif düğmeler odak almaz; kartın başlığını seçin). Esc ile çıkın.</span>
            </span>
            <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={buNeBitir}>
              Vazgeç
            </button>
          </div>
        </div>
      )}

      {panelGorunur && (
        // div + açık rol: <aside> üstünde role="dialog" ARIA-in-HTML'de izinli değil (axe aria-allowed-role).
        <div
          ref={panelRef}
          className={`asistan-panel${dar ? " asistan-panel-modal" : ""}`}
          data-asistan-gizli
          data-testid="asistan-paneli"
          role={dar ? "dialog" : "complementary"}
          aria-modal={dar ? true : undefined}
          aria-labelledby={baslikId}
          onKeyDown={panelTus}
        >
          <header className="asistan-panel-ust">
            <div className="asistan-panel-baslik">
              {/* AI kimliği (mor yalnız AI): dekoratif; başlığın adı "Asistan" kalır. */}
              <span className="asistan-kimlik" aria-hidden="true">
                <Ikon ad="asistan" />
              </span>
              <h2 id={baslikId} ref={baslikRef} tabIndex={-1}>
                Asistan
              </h2>
              {asistan?.mod === "off" && (
                <span className="rozet rozet-replay" title="Canlı model kapalı: yalnız hata sözlüğü, kayıt şablonları ve kural önerileri.">
                  HAZIR CEVAPLAR
                </span>
              )}
              {mockZorunlu() && (
                <span className="rozet rozet-mock" title="Örnek veri modu: cevaplar hazırlanmış örneklerdir.">
                  ÖRNEK VERİ
                </span>
              )}
              <DegerlendirmeNotu d={asistan?.degerlendirme} />
            </div>
            <button type="button" className="dugme dugme-hayalet dugme-kucuk asistan-kapat" onClick={paneliKapat} aria-label="Asistanı kapat">
              <Ikon ad="kapat" />
            </button>
          </header>
          <p className="asistan-denetim-notu soluk kucuk">Sorular denetim kaydına girer; sohbet 90 gün saklanır.</p>
          {!yalnizOneri && (
            <div className="asistan-sekmeler" role="tablist" aria-label="Asistan sekmeleri">
              {sekmeDugmesi("sohbet", "Sohbet")}
              {sekmeDugmesi("oneriler", "Öneriler")}
            </div>
          )}
          {/* Asistan ucu yokken (yalnız Öneriler) sekme listesi çizilmez: içerik adsız bir sekme
              paneli değil, adlı bir bölgedir. */}
          <div
            className="asistan-sekme-icerik"
            role={yalnizOneri ? "region" : "tabpanel"}
            id={`asistan-sekme-icerik-${sekme}`}
            aria-labelledby={yalnizOneri ? undefined : `asistan-sekme-${sekme}`}
            aria-label={yalnizOneri ? "Öneriler" : undefined}
          >
            <IcerikSiniri key={icerikDenemesi} yenidenDene={icerikYenidenDene}>
              <Suspense fallback={<Yukleniyor metin="Asistan yükleniyor…" />}>
                {sekme === "oneriler" ? (
                  <OnerilerSekmesi
                    ekran={ekran}
                    asistan={asistan}
                    oneriKuralId={kontrol.istek?.sekme === "oneriler" ? (kontrol.istek.oneriKuralId ?? null) : null}
                    onGit={onGit}
                  />
                ) : pasifNeden || !asistan ? (
                  <Uyari ton="uyari" baslik="Asistan kullanılamıyor">
                    {pasifNeden ?? "Asistan kapalı."}{" "}
                    <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={() => void yenile()}>
                      Yeniden dene
                    </button>
                  </Uyari>
                ) : (
                  <SohbetSekmesi
                    ekran={ekran}
                    asistan={asistan}
                    durumYenile={() => void yenile()}
                    buNeBaslat={() => {
                      setBuNeMesaji(null);
                      setBuNe((b) => !b);
                    }}
                    buNeAcik={buNe}
                    secili={secili}
                    seciliTemizle={() => setSecili(null)}
                    istek={kontrol.istek}
                    istegiTuket={istegiTuket}
                    onGit={onGit}
                  />
                )}
              </Suspense>
            </IcerikSiniri>
          </div>
        </div>
      )}
    </>
  );
}
