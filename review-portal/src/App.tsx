import { useEffect, useState, type ReactNode } from "react";
import { canliDerleme, cekirdekYetenekleri, ucVar, type Yetenekler } from "./api/http";
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { OlayProvider } from "./api/events";
import type { Rol } from "./api/types";
import { OTOMASYON_ROLLERI, OturumProvider, useOturum, varsayilanSayfa } from "./auth";
import { BildirimProvider } from "./components/Bildirim";
import { Kabuk } from "./components/Kabuk";
import { AsistanPaneli } from "./components/asistan/AsistanPaneli";
import { BosDurum, Kart, SayfaBasligi, Yukleniyor } from "./components/ui";
import { BugTaslakDetay, BugTaslaklari } from "./pages/BugTaslaklari";
import { CaseReview } from "./pages/CaseReview";
import { ClaudeCode } from "./pages/ClaudeCode";
import { Denetim } from "./pages/Denetim";
import { DemoKontrolleri } from "./pages/DemoKontrolleri";
import { GereksinimDetay } from "./pages/GereksinimDetay";
import { Gereksinimler } from "./pages/Gereksinimler";
import { Giris } from "./pages/Giris";
import { HataDetay } from "./pages/HataDetay";
import { Kod } from "./pages/Kod";
import { KontrolKulesi } from "./pages/KontrolKulesi";
import { KosuDetay, Kosular } from "./pages/Kosular";
import { ScriptDetay } from "./pages/ScriptDetay";
import { TestCaseleri } from "./pages/TestCaseleri";
import { Yayin } from "./pages/Yayin";
import { YolHaritasi } from "./pages/YolHaritasi";
import { ROL } from "./lib/etiketler";
import { useKimlikKipi } from "./lib/kimlikKipi";
import { AiprobeGirisineYonlendir } from "./pages/AiprobeGiris";
import { RolSec } from "./pages/RolSec";

function OturumGerekli({ children }: { children: ReactNode }) {
  const { kullanici, yukleniyor } = useOturum();
  const { kip } = useKimlikKipi();
  const konum = useLocation();
  if (yukleniyor) return <Yukleniyor metin="Oturum kontrol ediliyor…" />;
  // Yalnız AI Probe kipinde (yerel giriş kapalı) oturum yoksa doğrudan AI Probe girişine gidilir;
  // `local` ve `both` kipte giriş ekranı (both: yerel form + AI Probe düğmesi).
  if (!kullanici && kip === "aiprobe") return <AiprobeGirisineYonlendir devam={konum.pathname + konum.search} />;
  if (!kullanici) return <Navigate to="/giris" replace state={{ from: konum.pathname + konum.search }} />;
  return <OlayProvider etkin>{children}</OlayProvider>;
}

function RolGerekli({ roller, children }: { roller: Rol[]; children: ReactNode }) {
  const { kullanici } = useOturum();
  if (!kullanici || !roller.includes(kullanici.rol)) {
    return (
      <Kart>
        <BosDurum baslik="Bu ekran için yetkiniz yok.">Gereken rol: {roller.map((r) => ROL[r]).join(" / ")}</BosDurum>
      </Kart>
    );
  }
  return <>{children}</>;
}

function AnaSayfa() {
  const { kullanici } = useOturum();
  const canli = canliDerleme();
  const [yetenekler, setYetenekler] = useState<Yetenekler | null | undefined>(canli ? undefined : null);
  useEffect(() => {
    if (!canli) return;
    let iptal = false;
    void cekirdekYetenekleri().then((y) => !iptal && setYetenekler(y));
    return () => {
      iptal = true;
    };
  }, [canli]);
  if (!kullanici) return <Navigate to="/giris" replace />;
  // Canlı derlemede core'un uç listesi okunana kadar bekle (henüz olmayan ekrana yönlendirme yok).
  if (yetenekler === undefined) return <Yukleniyor />;
  const y = yetenekler;
  return <Navigate to={varsayilanSayfa(kullanici.rol, y ? (m, yol) => ucVar(y, m, yol) : undefined)} replace />;
}

function Bulunamadi() {
  return (
    <>
      <SayfaBasligi baslik="Sayfa bulunamadı" />
      <Kart>
        <BosDurum baslik="Aradığınız adres bu portalda yok.">
          <Link to="/">Ana sayfaya dön</Link>
        </BosDurum>
      </Kart>
    </>
  );
}

export function Rotalar() {
  return (
    <Routes>
      <Route path="/giris" element={<Giris />} />
      <Route path="/rol-sec" element={<RolSec />} />
      <Route
        element={
          <OturumGerekli>
            <Kabuk />
            {/* Portal asistanı (AI-ASISTAN-PLANI §11): Kabuk'un kardeşi, olay akışı içinde; /giris'te yok. */}
            <AsistanPaneli />
          </OturumGerekli>
        }
      >
        <Route index element={<AnaSayfa />} />
        <Route path="gereksinimler" element={<Gereksinimler />} />
        <Route path="gereksinimler/:id" element={<GereksinimDetay />} />
        <Route path="gereksinimler/:id/caseler" element={<CaseReview />} />
        <Route path="gereksinimler/:id/yayin" element={<Yayin />} />
        <Route path="caseler" element={<TestCaseleri />} />
        <Route
          path="kod"
          element={
            <RolGerekli roller={OTOMASYON_ROLLERI}>
              <Kod />
            </RolGerekli>
          }
        />
        <Route path="kod/:id" element={<ScriptDetay />} />
        <Route
          path="kosular"
          element={
            <RolGerekli roller={OTOMASYON_ROLLERI}>
              <Kosular />
            </RolGerekli>
          }
        />
        <Route path="kosular/:id" element={<KosuDetay />} />
        <Route path="hatalar/:id" element={<HataDetay />} />
        <Route path="bug-taslaklari" element={<BugTaslaklari />} />
        <Route path="bug-taslaklari/:id" element={<BugTaslakDetay />} />
        <Route path="kontrol-kulesi" element={<KontrolKulesi />} />
        <Route path="yol-haritasi" element={<YolHaritasi />} />
        <Route path="denetim" element={<Denetim />} />
        <Route
          path="claude-code"
          element={
            <RolGerekli roller={["analyst"]}>
              <ClaudeCode />
            </RolGerekli>
          }
        />
        <Route
          path="demo"
          element={
            <RolGerekli roller={["presenter"]}>
              <DemoKontrolleri />
            </RolGerekli>
          }
        />
        <Route path="*" element={<Bulunamadi />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <OturumProvider>
        <BildirimProvider>
          <Rotalar />
        </BildirimProvider>
      </OturumProvider>
    </BrowserRouter>
  );
}
