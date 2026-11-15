// Çok proje: sağ üstte (rol seçicinin yanında) proje seçici (TP-COK-PROJE-PLANI §6.3, Şerit 6).
//
// - `ProjeSaglayici` (Kabuk içinde) listeyi bir kez okur (`GET /api/projeler`) ve tüm parçalara verir:
//   üst çubuk seçicisi, dar ekran çekmecesindeki seçici, "rolünüz yok" ekranı ve AI Probe ortak
//   değiştiricisi (1.1.0: `AIProbeSwitcher.setProjects`).
// - Ortak değiştirici proje menüsünü destekliyorsa seçici onundur: portal kendi düğmesini ve
//   "Organizasyon · Proje" satırını çizmez (çift seçici yok); `aiprobe:project-change` olayını iptal edip
//   geçişi kendisi yapar (önbellek temizliği + liste sayfasına dönüş, lib/proje.ts).
// - Değiştirici yoksa (yerel kip, eski sürüm, yüklenemedi) kendi açılır listesi (`role=listbox`; ok
//   tuşları, Home/End, Enter/Boşluk, Esc). Tek proje varsa yalnız "Organizasyon · Proje" yazılır.
// - Başka sekmede proje değişirse (409 `proje_degisti`) kullanıcıya söylenir ve sekme yeni projede
//   yenilenir; seçili projede rol yoksa (403 `proje_rolu_yok`) ekran yerine proje seçtiren bilgi gösterilir.
import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../api/client";
import { hataMesaji, projeOlayinaAbone } from "../api/http";
import type { Kullanici, ProjeListesi, ProjeOzeti } from "../api/types";
import { oturumProjesi, projeRolleri, useOturum } from "../auth";
import { degistiriciyiYukle } from "../lib/degistirici";
import { useKimlikKipi } from "../lib/kimlikKipi";
import {
  degistiriciProjeDestegi,
  degistiriciyeProjeleriVer,
  PROJE_OLAYI,
  projeBasligi,
  projeMetni,
  projeRolEtiketi,
  projeyiDegistir,
  yeniProjedeYenile,
} from "../lib/proje";
import { useBildirim } from "./Bildirim";

/** 409 `proje_degisti` bildirimi ile yeniden yükleme arasındaki süre (ileti okunabilsin). */
export const YENILEME_GECIKMESI_MS = 1500;

interface ProjeDurumu {
  /** Gösterilecek liste: sunucu listesi, yoksa oturumdaki tek proje; proje bilgisi hiç yoksa null. */
  liste: ProjeListesi | null;
  /** Liste sunucudan geldi mi (false: oturumdan türetilmiş tek satır; seçim yapılamaz). */
  tam: boolean;
  /** Ortak değiştirici proje menüsünü gösteriyor: portal kendi seçicisini çizmez. */
  degistiriciVar: boolean;
  /** Geçiş istenen proje (istek sürerken). */
  gecilen: string | null;
  hata: string | null;
  /** Seçili projede rol yok (403 `proje_rolu_yok`). */
  rolYok: boolean;
  sec: (pid: string) => Promise<void>;
}

const Baglam = createContext<ProjeDurumu | null>(null);

export function useProjeDurumu(): ProjeDurumu | null {
  return useContext(Baglam);
}

/** Oturumdaki tek projeden liste (sunucu listesi yokken gösterim ve değiştirici için). */
export function oturumdanListe(k: Kullanici | null): ProjeListesi | null {
  const pid = oturumProjesi(k);
  if (!k || !k.proje || !pid) return null;
  return {
    projeler: [{ pid, ad: k.proje.ad, kod: k.proje.kod ?? null, org_ad: k.organizasyon?.ad ?? null, roller: projeRolleri(k) }],
    secili: pid,
  };
}

export function ProjeSaglayici({ children }: { children: ReactNode }) {
  const { kullanici } = useOturum();
  const kip = useKimlikKipi();
  const bildir = useBildirim();
  const konum = useLocation();
  const konumRef = useRef(konum.pathname);
  konumRef.current = konum.pathname;
  const [sunucuListesi, setSunucuListesi] = useState<ProjeListesi | null>(null);
  const [degistiriciVar, setDegistiriciVar] = useState(false);
  const [gecilen, setGecilen] = useState<string | null>(null);
  const [hata, setHata] = useState<string | null>(null);
  const [rolYok, setRolYok] = useState(false);

  const pid = oturumProjesi(kullanici);
  // Tek projeli kullanıcıda (`projeler_sayisi: 1`) liste istenmez; proje alanı yoksa (eski core) hiç.
  const listeGerekli = !!pid && kullanici?.projeler_sayisi !== 1;
  useEffect(() => {
    setSunucuListesi(null);
    if (!listeGerekli) return;
    let iptal = false;
    api
      .projeler()
      .then((l) => !iptal && setSunucuListesi(l))
      .catch(() => {
        /* uç yok / hata: oturumdaki proje adı gösterilir (seçim yapılamaz) */
      });
    return () => {
      iptal = true;
    };
  }, [listeGerekli, pid, kullanici?.id]);

  const yedek = useMemo(() => oturumdanListe(kullanici), [kullanici]);
  const liste = sunucuListesi ?? yedek;
  const tam = !!sunucuListesi;

  // Ortak değiştirici (yalnız AI Probe kipinde yüklenir) proje menüsünü destekliyor mu.
  useEffect(() => {
    if (kip.kip === "local") {
      setDegistiriciVar(false);
      return;
    }
    let iptal = false;
    degistiriciyiYukle()
      .then(() => !iptal && setDegistiriciVar(degistiriciProjeDestegi()))
      .catch(() => !iptal && setDegistiriciVar(false));
    return () => {
      iptal = true;
    };
  }, [kip.kip]);

  // Değiştiriciyi besle: liste her değiştiğinde (sonradan bağlanan değiştirici de `projects`'ten alır).
  useEffect(() => {
    if (degistiriciVar) degistiriciyeProjeleriVer(liste);
  }, [degistiriciVar, liste]);

  const sec = useCallback(
    async (hedef: string) => {
      if (gecilen || hedef === liste?.secili) return;
      setGecilen(hedef);
      setHata(null);
      try {
        await projeyiDegistir(hedef, konumRef.current);
        // Başarıda sekme tam sayfa yeniden yüklenir; testte gezinti sahteyse durum burada kalır.
      } catch (e) {
        setHata(`${projeMetni("degistirilemedi")} ${hataMesaji(e)}`);
        setGecilen(null);
        bildir(`${projeMetni("degistirilemedi")} ${hataMesaji(e)}`, "hata");
      }
    },
    [gecilen, liste?.secili, bildir],
  );
  const secRef = useRef(sec);
  secRef.current = sec;

  // Ortak değiştiricinin seçimi: olay iptal edilir (değiştirici kendi PUT/yenilemesini yapmaz), geçiş bizde.
  useEffect(() => {
    const dinle = (e: Event) => {
      const hedef = (e as CustomEvent<{ pid?: unknown }>).detail?.pid;
      if (typeof hedef !== "string" || !hedef) return;
      e.preventDefault();
      void secRef.current(hedef);
    };
    window.addEventListener(PROJE_OLAYI, dinle);
    return () => window.removeEventListener(PROJE_OLAYI, dinle);
  }, []);

  // 409 `proje_degisti` → bildir + yeni projede yenile (bir kez); 403 `proje_rolu_yok` → seçtiren ekran.
  useEffect(() => {
    let yenileniyor = false;
    let zaman: ReturnType<typeof setTimeout> | null = null;
    const iptal = projeOlayinaAbone((olay) => {
      if (olay === "proje_rolu_yok") {
        setRolYok(true);
        return;
      }
      if (yenileniyor) return;
      yenileniyor = true;
      bildir(projeMetni("baskaSekme"), "bilgi");
      zaman = setTimeout(() => yeniProjedeYenile(konumRef.current), YENILEME_GECIKMESI_MS);
    });
    return () => {
      iptal();
      if (zaman) clearTimeout(zaman);
    };
  }, [bildir]);

  const deger = useMemo<ProjeDurumu>(
    () => ({ liste, tam, degistiriciVar, gecilen, hata, rolYok, sec }),
    [liste, tam, degistiriciVar, gecilen, hata, rolYok, sec],
  );
  return <Baglam.Provider value={deger}>{children}</Baglam.Provider>;
}

function rolMetni(p: ProjeOzeti, liste: ProjeListesi): string {
  if (!p.roller.length) return "";
  const etiket = projeMetni(p.roller.length > 1 ? "roller" : "rol");
  return `${etiket}: ${p.roller.map((r) => projeRolEtiketi(r, liste)).join(", ")}`;
}

/**
 * Üst çubuk (`yer="ust"`) ya da dar ekran çekmecesi (`yer="menu"`) seçicisi. Ortak değiştirici proje
 * menüsünü gösteriyorsa hiçbir şey çizmez.
 */
export function ProjeSecici({ yer = "ust" }: { yer?: "ust" | "menu" }) {
  const durum = useProjeDurumu();
  const kok = useRef<HTMLDivElement>(null);
  const dugme = useRef<HTMLButtonElement>(null);
  const listeRef = useRef<HTMLUListElement>(null);
  const [acik, setAcik] = useState(false);
  const [etkin, setEtkin] = useState(0);
  const kimlik = useId();

  const liste = durum?.liste ?? null;
  const secili = liste?.projeler.find((p) => p.pid === liste.secili) ?? null;
  const secilebilir = !!durum?.tam && (liste?.projeler.length ?? 0) > 1;

  const kapat = useCallback((odakDon = true) => {
    setAcik(false);
    if (odakDon) dugme.current?.focus();
  }, []);

  useEffect(() => {
    if (!acik) return;
    listeRef.current?.focus();
    const disTik = (e: MouseEvent) => {
      if (kok.current && !kok.current.contains(e.target as Node)) setAcik(false);
    };
    document.addEventListener("mousedown", disTik);
    return () => document.removeEventListener("mousedown", disTik);
  }, [acik]);

  if (!durum || !liste || durum.degistiriciVar) return null;
  const baslik = projeBasligi(secili) || projeMetni("projeSec");
  const sinif = yer === "menu" ? "proje-secici proje-secici-menu" : "proje-secici";

  if (!secilebilir) {
    if (!secili) return null;
    return (
      <span className={yer === "menu" ? "menu-kullanici-rol" : "proje-baglami"} role="group" aria-label={projeMetni("grup")} data-testid="proje-baglami" title={baslik}>
        {baslik}
      </span>
    );
  }

  const ac = () => {
    setEtkin(Math.max(0, liste.projeler.findIndex((p) => p.pid === liste.secili)));
    setAcik(true);
  };

  const listeTusu = (e: ReactKeyboardEvent<HTMLUListElement>) => {
    const n = liste.projeler.length;
    const harf = e.key.length === 1 && /\S/.test(e.key) ? e.key.toLocaleLowerCase() : null;
    if (e.key === "ArrowDown") setEtkin((i) => (i + 1) % n);
    else if (e.key === "ArrowUp") setEtkin((i) => (i - 1 + n) % n);
    else if (e.key === "Home") setEtkin(0);
    else if (e.key === "End") setEtkin(n - 1);
    else if (e.key === "Enter" || e.key === " ") {
      const p = liste.projeler[etkin];
      if (p) sec(p.pid);
    } else if (e.key === "Escape") {
      // preventDefault (aşağıda): çekmecenin Escape dinleyicisi (Kabuk) çekmeceyi de kapatmaz.
      kapat();
    } else if (e.key === "Tab") {
      setAcik(false);
      return;
    } else if (harf) {
      const sira = liste.projeler.map((_, i) => (etkin + 1 + i) % n);
      const bulunan = sira.find((i) => liste.projeler[i].ad.toLocaleLowerCase("tr-TR").startsWith(harf));
      if (bulunan === undefined) return;
      setEtkin(bulunan);
    } else return;
    e.preventDefault();
    e.stopPropagation();
  };

  function sec(pid: string) {
    if (pid === liste!.secili) {
      kapat();
      return;
    }
    void durum!.sec(pid);
  }

  const etiket = durum.gecilen ? projeMetni("geciliyor") : baslik;
  return (
    <div className={sinif} ref={kok} data-testid={yer === "menu" ? "proje-secici-menu" : "proje-secici"}>
      <button
        ref={dugme}
        type="button"
        className="proje-secici-dugme"
        aria-haspopup="listbox"
        aria-expanded={acik}
        aria-controls={acik ? `${kimlik}-liste` : undefined}
        aria-busy={!!durum.gecilen}
        aria-label={`${projeMetni("proje")}: ${baslik} (${projeMetni("projeDegistir").toLocaleLowerCase("tr-TR")})`}
        title={secili ? `${baslik}${secili.roller.length ? ` (${rolMetni(secili, liste)})` : ""}` : baslik}
        disabled={!!durum.gecilen}
        onClick={() => (acik ? kapat(false) : ac())}
      >
        {secili?.org_ad && !durum.gecilen && (
          <>
            <span className="proje-secici-org">{secili.org_ad}</span>
            <span className="proje-secici-ayrac" aria-hidden="true">
              ·
            </span>
          </>
        )}
        <span className="proje-secici-ad">{durum.gecilen ? etiket : (secili?.ad ?? etiket)}</span>
        <span aria-hidden="true">▾</span>
      </button>
      {acik && (
        <div className="proje-secici-panel">
          <p className="rol-secici-baslik" id={`${kimlik}-baslik`}>
            {projeMetni("projeler")}
          </p>
          <ul
            ref={listeRef}
            id={`${kimlik}-liste`}
            role="listbox"
            tabIndex={-1}
            aria-labelledby={`${kimlik}-baslik`}
            aria-activedescendant={`${kimlik}-oge-${etkin}`}
            onKeyDown={listeTusu}
          >
            {liste.projeler.map((p, i) => {
              const ayrinti = [p.org_ad, rolMetni(p, liste)].filter(Boolean).join(" · ");
              return (
                <li
                  key={p.pid}
                  id={`${kimlik}-oge-${i}`}
                  role="option"
                  aria-selected={p.pid === liste.secili}
                  className={`proje-secici-oge${i === etkin ? " etkin" : ""}${p.pid === liste.secili ? " aktif" : ""}`}
                  onMouseEnter={() => setEtkin(i)}
                  onClick={() => sec(p.pid)}
                >
                  <span className="proje-secici-oge-ad">{p.ad}</span>
                  {ayrinti && <span className="proje-secici-oge-alt">{ayrinti}</span>}
                  {p.pid === liste.secili && <span className="rol-secici-isaret">{projeMetni("secili")}</span>}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Seçili projede rol yoksa (403 `proje_rolu_yok`) ekran içeriği yerine gösterilir; proje seçtirir. */
export function ProjeRolYok() {
  const durum = useProjeDurumu();
  const baslikRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    baslikRef.current?.focus();
  }, []);
  if (!durum) return null;
  const secenekler = (durum.tam ? durum.liste?.projeler ?? [] : []).filter((p) => p.pid !== durum.liste?.secili && p.roller.length > 0);
  return (
    <section className="kart proje-rol-yok" data-testid="proje-rol-yok" aria-labelledby="proje-rol-yok-baslik">
      <h2 id="proje-rol-yok-baslik" ref={baslikRef} tabIndex={-1}>
        {projeMetni("rolYokBaslik")}
      </h2>
      <p>{projeMetni("rolYokMetin")}</p>
      {secenekler.length > 0 ? (
        <ul className="proje-rol-yok-liste">
          {secenekler.map((p) => (
            <li key={p.pid}>
              <button type="button" className="dugme dugme-ikincil" disabled={!!durum.gecilen} onClick={() => void durum.sec(p.pid)}>
                {projeBasligi(p)}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="soluk">{projeMetni("projeYok")}</p>
      )}
      {durum.hata && (
        <p className="alan-hata" role="alert">
          {durum.hata}
        </p>
      )}
    </section>
  );
}
