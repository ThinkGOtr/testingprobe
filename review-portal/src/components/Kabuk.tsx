import { useEffect, useState, useSyncExternalStore } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { mockDegisikligineAbone, mockUclari, mockZorunlu } from "../api/http";
import { useBaglantiDurumu, type BaglantiDurumu } from "../api/events";
import type { Rol } from "../api/types";
import { useOturum } from "../auth";
import { ROL } from "../lib/etiketler";

interface NavOgesi {
  yol: string;
  ad: string;
  /** Yalnızca bu rollere görünür (boşsa herkese). */
  gorunur?: Rol[];
  /** Bu rollerin asıl çalışma alanı (vurgulanır). */
  odak?: Rol[];
}

const NAV: { grup: string; ogeler: NavOgesi[] }[] = [
  {
    grup: "İş akışı",
    ogeler: [
      { yol: "/gereksinimler", ad: "Gereksinimler", odak: ["analyst", "po"] },
      { yol: "/kod", ad: "Kod üretimi", odak: ["engineer"] },
      { yol: "/kosular", ad: "Koşular", odak: ["presenter", "engineer"] },
      { yol: "/bug-taslaklari", ad: "Bug taslakları", odak: ["tester"] },
    ],
  },
  {
    grup: "İzleme",
    ogeler: [
      { yol: "/kontrol-kulesi", ad: "Kontrol Kulesi", odak: ["presenter"] },
      { yol: "/denetim", ad: "Denetim" },
      { yol: "/claude-code", ad: "Claude Code kanalı", gorunur: ["analyst"] },
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

type Tema = "sistem" | "acik" | "koyu";

function temaOku(): Tema {
  try {
    const t = localStorage.getItem("tp-tema");
    if (t === "acik" || t === "koyu") return t;
  } catch {
    /* depolama yok */
  }
  return "sistem";
}

function useTema(): [Tema, () => void] {
  const [tema, setTema] = useState<Tema>(temaOku);
  useEffect(() => {
    const kok = document.documentElement;
    if (tema === "sistem") kok.removeAttribute("data-theme");
    else kok.setAttribute("data-theme", tema === "acik" ? "light" : "dark");
    try {
      localStorage.setItem("tp-tema", tema);
    } catch {
      /* yoksay */
    }
  }, [tema]);
  const degistir = () => setTema((t) => (t === "sistem" ? "koyu" : t === "koyu" ? "acik" : "sistem"));
  return [tema, degistir];
}

const TEMA_ETIKETI: Record<Tema, string> = { sistem: "Tema: sistem", acik: "Tema: açık", koyu: "Tema: koyu" };

function useMockUclari(): string[] {
  const anlik = useSyncExternalStore(mockDegisikligineAbone, () => mockUclari().join("|"));
  return anlik ? anlik.split("|") : [];
}

export function Kabuk() {
  const { kullanici, cikisYap } = useOturum();
  const baglanti = useBaglantiDurumu();
  const mockUclar = useMockUclari();
  const [tema, temaDegistir] = useTema();
  const [menuAcik, setMenuAcik] = useState(false);
  const konum = useLocation();
  const git = useNavigate();

  useEffect(() => setMenuAcik(false), [konum.pathname]);

  const mockAktif = mockZorunlu() || mockUclar.length > 0;
  const b = BAGLANTI[baglanti];

  return (
    <div className="kabuk">
      <a className="atla" href="#ana-icerik">
        İçeriğe atla
      </a>
      <header className="ust-cubuk">
        <button
          type="button"
          className="menu-dugmesi"
          aria-expanded={menuAcik}
          aria-controls="yan-menu"
          onClick={() => setMenuAcik((m) => !m)}
        >
          <span aria-hidden="true">☰</span>
          <span className="gorunmez">Menü</span>
        </button>
        <NavLink to="/" className="marka">
          <span className="marka-isaret" aria-hidden="true" />
          <span>
            AI Testing Probe <span className="marka-alt">Kontrol Kulesi</span>
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
            {tema === "koyu" ? "☾" : tema === "acik" ? "☀" : "◐"}
          </button>
          {kullanici && (
            <div className="kullanici">
              <span className="kullanici-ad">{kullanici.kullanici_adi}</span>
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
        <nav id="yan-menu" className={`yan-menu${menuAcik ? " acik" : ""}`} aria-label="Ana menü">
          {NAV.map((g) => {
            const ogeler = g.ogeler.filter((o) => !o.gorunur || (kullanici && o.gorunur.includes(kullanici.rol)));
            if (ogeler.length === 0) return null;
            return (
              <div key={g.grup} className="menu-grup">
                <div className="menu-grup-baslik">{g.grup}</div>
                <ul>
                  {ogeler.map((o) => (
                    <li key={o.yol}>
                      <NavLink to={o.yol} className={({ isActive }) => `menu-oge${isActive ? " aktif" : ""}`}>
                        <span>{o.ad}</span>
                        {kullanici && o.odak?.includes(kullanici.rol) && (
                          <span className="odak-isaret" title="Rolünüzün çalışma alanı">
                            <span className="gorunmez">(rolünüzün çalışma alanı)</span>
                          </span>
                        )}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </nav>
        <main id="ana-icerik" className="icerik" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
