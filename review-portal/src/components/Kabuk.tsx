import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { canliDerleme, cekirdekYetenekleri, mockDegisikligineAbone, mockUclari, mockZorunlu, ucVar, type Yetenekler } from "../api/http";
import { useBaglantiDurumu, type BaglantiDurumu } from "../api/events";
import type { Rol } from "../api/types";
import { useOturum } from "../auth";
import { ROL } from "../lib/etiketler";
import { TEMA_ETIKETI, useTema } from "../lib/tema";
import { Ikon, type IkonAdi } from "./Ikon";

interface NavOgesi {
  yol: string;
  ad: string;
  /** Menü öğesinin dekoratif ikonu (aria-hidden; erişilebilir ad `ad`dır). */
  ikon: IkonAdi;
  /** Yalnızca bu rollere görünür (boşsa herkese). */
  gorunur?: Rol[];
  /** Bu rollerin asıl çalışma alanı (vurgulanır). */
  odak?: Rol[];
  /** Ekranın core'daki veri ucu. Canlı derlemede core bu ucu sunmuyorsa öğe pasiftir ("bu fazda yok"). */
  uc: readonly [string, string];
}

const NAV: { grup: string; ogeler: NavOgesi[] }[] = [
  {
    grup: "İş akışı",
    ogeler: [
      { yol: "/gereksinimler", ad: "Gereksinimler", ikon: "gereksinim", odak: ["analyst", "po"], uc: ["GET", "/requirements"] },
      { yol: "/kod", ad: "Kod üretimi", ikon: "kod", odak: ["engineer"], uc: ["GET", "/scripts"] },
      { yol: "/kosular", ad: "Koşular", ikon: "kosu", odak: ["presenter", "engineer"], uc: ["GET", "/runs"] },
      { yol: "/bug-taslaklari", ad: "Bug taslakları", ikon: "bug", odak: ["tester"], uc: ["GET", "/bug-drafts"] },
    ],
  },
  {
    grup: "İzleme",
    ogeler: [
      { yol: "/yol-haritasi", ad: "Demo yol haritası", ikon: "harita", odak: ["presenter"], uc: ["GET", "/requirements"] },
      { yol: "/kontrol-kulesi", ad: "Kontrol Kulesi", ikon: "kule", odak: ["presenter"], uc: ["GET", "/control-tower"] },
      { yol: "/demo", ad: "Demo kontrolleri", ikon: "demo", gorunur: ["presenter"], odak: ["presenter"], uc: ["POST", "/demo/break-locator"] },
      { yol: "/denetim", ad: "Denetim", ikon: "denetim", uc: ["GET", "/audit"] },
      { yol: "/claude-code", ad: "Claude Code kanalı", ikon: "terminal", gorunur: ["analyst"], uc: ["GET", "/tokens"] },
    ],
  },
];

const BAGLANTI: Record<BaglantiDurumu, { etiket: string; sinif: string }> = {
  bagli: { etiket: "Canlı olaylar", sinif: "bagli" },
  baglaniyor: { etiket: "Bağlanıyor…", sinif: "bekliyor" },
  yeniden: { etiket: "Yeniden bağlanıyor…", sinif: "uyari" },
  mock: { etiket: "Olaylar: örnek veri", sinif: "mock" },
  kapali: { etiket: "Olay akışı kapalı", sinif: "kapali" },
};

function useMockUclari(): string[] {
  const anlik = useSyncExternalStore(mockDegisikligineAbone, () => mockUclari().join("|"));
  return anlik ? anlik.split("|") : [];
}

/**
 * Canlı derlemede (VITE_MOCK=0) core'un uç listesi: menüde core'un henüz sunmadığı ekranlar
 * pasif gösterilir. Örnek veri derlemesinde ya da liste okunamazsa `null` (hepsi etkin).
 */
export function useCanliYetenekler(): Yetenekler | null {
  const [y, setY] = useState<Yetenekler | null>(null);
  useEffect(() => {
    if (!canliDerleme()) return;
    let iptal = false;
    void cekirdekYetenekleri().then((v) => {
      if (!iptal) setY(v);
    });
    return () => {
      iptal = true;
    };
  }, []);
  return y;
}

/** Avatar için baş harfler (en çok iki): "Cengizhan Gunaydin" → "CG", "sunucu" → "S". */
export function basHarfler(ad: string): string {
  const parcalar = ad.trim().split(/[\s._-]+/).filter(Boolean);
  return parcalar
    .slice(0, 2)
    .map((p) => p[0]!.toLocaleUpperCase("tr-TR"))
    .join("");
}

export function Kabuk() {
  const { kullanici, cikisYap } = useOturum();
  const baglanti = useBaglantiDurumu();
  const mockUclar = useMockUclari();
  const yetenekler = useCanliYetenekler();
  const [tema, temaDegistir] = useTema();
  const [menuAcik, setMenuAcik] = useState(false);
  const konum = useLocation();
  const git = useNavigate();

  const menuDugmesi = useRef<HTMLButtonElement>(null);
  const kabukRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLElement>(null);

  // Rota değişince menü kapanır. Açık mobil menüden gezinildiyse odak yeni sayfanın içeriğine (#ana-icerik,
  // "İçeriğe atla" hedefi, tabIndex=-1) taşınır: kapanan menüdeki bağlantı gizlenir, odak body'ye düşmez
  // (WCAG 2.4.3). Geniş ekranda (menü hep görünür) odak tıklanan bağlantıda kalır.
  const menuAcikRef = useRef(menuAcik);
  menuAcikRef.current = menuAcik;
  useEffect(() => {
    if (!menuAcikRef.current) return;
    setMenuAcik(false);
    // İçerik açık menüde inert; inert kaldırma efekti yeniden çizimde çalışır, odak ondan önce taşınır.
    const ana = document.getElementById("ana-icerik");
    if (ana) {
      ana.inert = false;
      ana.focus({ preventScroll: true });
    }
  }, [konum.pathname]);

  // Açık mobil menü geniş ekrana geçişte kapanır (geri daraltınca perdeyle yeniden açılmaz).
  useEffect(() => {
    if (!menuAcik || typeof window.matchMedia !== "function") return;
    const genis = window.matchMedia("(min-width: 861px)");
    const kapat = () => {
      if (genis.matches) setMenuAcik(false);
    };
    kapat();
    genis.addEventListener("change", kapat);
    return () => genis.removeEventListener("change", kapat);
  }, [menuAcik]);

  // Açık mobil menü Escape ile kapanır; odak menü düğmesine döner (kapanan menüde kalmaz).
  useEffect(() => {
    if (!menuAcik) return;
    const kapat = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      setMenuAcik(false);
      menuDugmesi.current?.focus();
    };
    document.addEventListener("keydown", kapat);
    return () => document.removeEventListener("keydown", kapat);
  }, [menuAcik]);

  // Açık mobil menü kipsel davranır (WCAG 2.4.11 / 2.4.3): menü düğmesi ve menü dışındaki her şey (İçeriğe atla,
  // marka, üst çubuğun sağı, içerik) inert olur; Tab yalnız menü düğmesi ile menü bağlantıları arasında döngüyle dolaşır,
  // odak menünün altında kalan içeriğe geçemez. Açılışta odak ilk menü bağlantısına taşınır. Kapanış: Escape,
  // menü düğmesi ya da bir bağlantıyla gezinme (yukarıdaki efektler).
  useEffect(() => {
    if (!menuAcik) return;
    const kok = kabukRef.current;
    if (!kok) return;
    const arka = [...kok.querySelectorAll<HTMLElement>(":scope > .atla, .ust-cubuk > .marka, .ust-cubuk > .ust-sag, #ana-icerik")];
    for (const e of arka) e.inert = true;
    menuRef.current?.querySelector<HTMLElement>("a[href]")?.focus();
    // Döngü: son bağlantıdan Tab menü düğmesine, menü düğmesinden Shift+Tab son bağlantıya (sayfa dışına çıkmaz).
    const dongu = (e: KeyboardEvent) => {
      if (e.key !== "Tab" || e.altKey || e.ctrlKey || e.metaKey) return;
      const dugme = menuDugmesi.current;
      const baglantilar = [...(menuRef.current?.querySelectorAll<HTMLElement>("a[href]") ?? [])];
      if (!dugme || baglantilar.length === 0) return;
      const sira = [dugme, ...baglantilar];
      const i = sira.indexOf(document.activeElement as HTMLElement);
      const hedef = e.shiftKey ? (i <= 0 ? sira[sira.length - 1] : null) : i === -1 || i === sira.length - 1 ? sira[0] : null;
      if (!hedef) return;
      e.preventDefault();
      hedef.focus();
    };
    document.addEventListener("keydown", dongu);
    return () => {
      document.removeEventListener("keydown", dongu);
      for (const e of arka) e.inert = false;
    };
  }, [menuAcik]);

  const mockAktif = mockZorunlu() || mockUclar.length > 0;
  const b = BAGLANTI[baglanti];

  return (
    <div className="kabuk" ref={kabukRef}>
      <a className="atla" href="#ana-icerik">
        İçeriğe atla
      </a>
      <header className="ust-cubuk">
        <button
          ref={menuDugmesi}
          type="button"
          className="menu-dugmesi"
          aria-expanded={menuAcik}
          aria-controls="yan-menu"
          onClick={() => setMenuAcik((m) => !m)}
        >
          <Ikon ad="menu" />
          <span className="gorunmez">Menü</span>
        </button>
        <NavLink to="/" className="marka">
          <span className="marka-isaret" aria-hidden="true" />
          <span>
            <span className="marka-on">AI Testing</span> <strong>Probe</strong> <span className="marka-alt">İnceleme portalı</span>
          </span>
        </NavLink>
        <div className="ust-sag">
          {mockAktif && (
            <span
              className="rozet rozet-mock"
              title={
                mockZorunlu()
                  ? "Portal örnek veri modunda (VITE_MOCK=1) derlendi. Gösterilen veriler gerçek değildir."
                  : `Şu uçlar henüz core-api'de yok; örnek veriyle cevaplandı:\n${mockUclar.join("\n")}`
              }
            >
              ÖRNEK VERİ
            </span>
          )}
          <span className={`baglanti baglanti-${b.sinif}`} role="status">
            <span className="nokta" aria-hidden="true" />
            <span className="baglanti-metin">{b.etiket}</span>
          </span>
          <button type="button" className="dugme dugme-hayalet dugme-kucuk" onClick={temaDegistir} aria-label={`${TEMA_ETIKETI[tema]} (değiştir)`}>
            <Ikon ad={tema === "koyu" ? "ay" : tema === "acik" ? "gunes" : "sistem"} />
          </button>
          {kullanici && (
            <div className="kullanici">
              <span className="kullanici-avatar" aria-hidden="true">
                {basHarfler(kullanici.ad_soyad || kullanici.kullanici_adi)}
              </span>
              <span className="kullanici-ad" title={`${kullanici.gorunen_ad ?? ROL[kullanici.rol]} (${kullanici.kullanici_adi})`}>
                {kullanici.ad_soyad || kullanici.kullanici_adi}
              </span>
              <span className="kullanici-rol">{ROL[kullanici.rol]}</span>
            </div>
          )}
          <button
            type="button"
            className="dugme dugme-ikincil dugme-kucuk"
            onClick={async () => {
              await cikisYap();
              git("/giris", { replace: true });
            }}
          >
            Çıkış
          </button>
        </div>
      </header>
      <div className="govde">
        <nav ref={menuRef} id="yan-menu" className={`yan-menu${menuAcik ? " acik" : ""}`} aria-label="Ana menü">
          {NAV.map((g) => {
            const ogeler = g.ogeler.filter((o) => !o.gorunur || (kullanici && o.gorunur.includes(kullanici.rol)));
            if (ogeler.length === 0) return null;
            return (
              <div key={g.grup} className="menu-grup">
                <div className="menu-grup-baslik">{g.grup}</div>
                <ul>
                  {ogeler.map((o) => (
                    <li key={o.yol}>
                      {yetenekler && !ucVar(yetenekler, ...o.uc) ? (
                        <span
                          className="menu-oge menu-oge-pasif"
                          aria-disabled="true"
                          title="Bu fazda yok: çekirdek bu ekranın verisini henüz sunmuyor (örnek veri gösterilmez)."
                        >
                          <Ikon ad={o.ikon} />
                          <span>{o.ad}</span>
                          <span className="menu-oge-not">bu fazda yok</span>
                        </span>
                      ) : (
                      <NavLink to={o.yol} className={({ isActive }) => `menu-oge${isActive ? " aktif" : ""}`}>
                        <Ikon ad={o.ikon} />
                        <span>{o.ad}</span>
                        {kullanici && o.odak?.includes(kullanici.rol) && (
                          <span className="odak-isaret" title="Rolünüzün çalışma alanı">
                            <span className="gorunmez">(rolünüzün çalışma alanı)</span>
                          </span>
                        )}
                      </NavLink>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </nav>
        <main id="ana-icerik" className="icerik" tabIndex={-1}>
          {mockAktif && (
            <div className={`uyari-kutusu uyari-uyari ornek-veri-bandi${mockZorunlu() ? " ornek-veri-tam" : ""}`} role="note" data-testid="ornek-veri-bandi">
              <strong>ÖRNEK VERİ — gerçek değil.</strong>{" "}
              {mockZorunlu()
                ? "Bu portal örnek veriyle derlendi; sayılar ve oranlar ölçüm değildir."
                : "Bu ekrandaki verinin bir kısmı core'da henüz olmadığı için örnek veriden geliyor; sayılar ve oranlar ölçüm değildir."}
            </div>
          )}
          <Outlet />
        </main>
      </div>
    </div>
  );
}
