// Portal asistan paneli (AI-ASISTAN-PLANI §11): sağ altta "Asistan" düğmesi; masaüstünde
// modal olmayan 420 px bindirme (`role="complementary"`), < 760 px tam ekran modal. İki sekme:
// "Sohbet" | "Öneriler" (Öneriler içeriği Öneri şeridinin `OnerilerSekmesi` bileşeni).
// App.tsx'te `OturumGerekli` içinde Kabuk'un kardeşi olarak çizilir (OlayProvider içinde, /giris'te yok);
// rota parametrelerini `useEkranBaglami` (useLocation + matchPath) ile okur.
import "./asistan.css";
import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent } from "react";
import { api } from "../../api/client";
import { mockZorunlu } from "../../api/http";
import { useEkranBaglami, type EkranBaglami } from "../../lib/ekranBaglami";
import { DegerlendirmeNotu, Uyari } from "../ui";
import { elemanTanimi, noktadakiOge, type SeciliEleman } from "./buNe";
import { istegiTuket, paneliAc, paneliKapat, panelHazirAyarla, sekmeSec, useAsistanKontrol, type AsistanSekmesi } from "./kontrol";
import { OnerilerSekmesi } from "./OnerilerSekmesi";
import { SohbetSekmesi } from "./SohbetSekmesi";
import { useAsistanKapisi } from "./yetenek";

export const DAR_EKRAN_PX = 760;

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
  const panelRef = useRef<HTMLElement>(null);
  const baslikRef = useRef<HTMLHeadingElement>(null);
  const baslaticiRef = useRef<HTMLButtonElement>(null);
  /** Panel dışında en son odaklanan öğe: kapanınca odak oraya (yoksa başlatıcıya) döner. */
  const disOdakRef = useRef<HTMLElement | null>(null);
  const oncekiAcik = useRef(kontrol.acik);
  const baslikId = useId();

  const hazir = kapi.tur === "hazir";
  useEffect(() => {
    panelHazirAyarla(hazir);
    return () => panelHazirAyarla(false);
  }, [hazir]);

  const buNeBitir = useCallback(() => {
    setBuNe(false);
    setVurgu(null);
    setBuNeMesaji(null);
  }, []);

  // Esc: önce "Bu ne?"den çıkar (belge düzeyinde; bindirme odak almaz).
  useEffect(() => {
    if (!buNe) return;
    const fn = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        buNeBitir();
      }
    };
    document.addEventListener("keydown", fn);
    return () => document.removeEventListener("keydown", fn);
  }, [buNe, buNeBitir]);

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
      if (!p) return;
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

  const atla = useCallback((el: Element) => el === bindirmeRef.current || !!bindirmeRef.current?.contains(el), []);

  const bindirmeTikla = (e: ReactMouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const sonuc = noktadakiOge(e.clientX, e.clientY, atla);
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
    buNeBitir();
    sekmeSec("sohbet");
    paneliAc();
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
    if (e.key === "Escape" && !buNe && !dar) {
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
        <button
          ref={baslaticiRef}
          type="button"
          className={`asistan-baslatici${pasifNeden ? " pasif" : ""}`}
          data-asistan-gizli
          title={pasifNeden ?? "Asistanı aç"}
          aria-label={pasifNeden ? `Asistan (kapalı: ${pasifNeden})` : "Asistanı aç"}
          onClick={() => {
            // Pasifken de açılır: neden Sohbet sekmesindeki uyarıda görünür (dokunmatikte title yok).
            sekmeSec("sohbet");
            paneliAc();
          }}
        >
          <span aria-hidden="true">✦</span> Asistan
        </button>
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
            {buNeMesaji ?? "Sormak istediğiniz öğeye tıklayın."} <span className="soluk">Esc ile çıkın.</span>
            <button type="button" className="dugme dugme-ikincil dugme-kucuk" onClick={buNeBitir}>
              Vazgeç
            </button>
          </div>
        </div>
      )}

      {panelGorunur && (
        <aside
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
            <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={paneliKapat} aria-label="Asistanı kapat">
              ✕
            </button>
          </header>
          <p className="asistan-denetim-notu soluk kucuk">Sorular denetim kaydına girer; sohbet 90 gün saklanır.</p>
          {!yalnizOneri && (
            <div className="asistan-sekmeler" role="tablist" aria-label="Asistan sekmeleri">
              {sekmeDugmesi("sohbet", "Sohbet")}
              {sekmeDugmesi("oneriler", "Öneriler")}
            </div>
          )}
          <div
            className="asistan-sekme-icerik"
            role="tabpanel"
            id={`asistan-sekme-icerik-${sekme}`}
            aria-labelledby={yalnizOneri ? undefined : `asistan-sekme-${sekme}`}
          >
            {sekme === "oneriler" ? (
              <OnerilerSekmesi
                ekran={ekran}
                asistan={asistan}
                oneriKuralId={kontrol.istek?.sekme === "oneriler" ? (kontrol.istek.oneriKuralId ?? null) : null}
                onGit={onGit}
              />
            ) : pasifNeden || !asistan ? (
              <Uyari ton="uyari" baslik="Asistan kullanılamıyor">
                {pasifNeden ?? "Asistan kapalı."}
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
          </div>
        </aside>
      )}
    </>
  );
}
