import type { ReactNode } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { OlayProvider } from "./api/events";
import type { Rol } from "./api/types";
import { OturumProvider, useOturum, varsayilanSayfa } from "./auth";
import { BildirimProvider } from "./components/Bildirim";
import { Kabuk } from "./components/Kabuk";
import { BosDurum, Kart, Yukleniyor } from "./components/ui";
import { BugTaslakDetay, BugTaslaklari } from "./pages/BugTaslaklari";
import { CaseReview } from "./pages/CaseReview";
import { ClaudeCode } from "./pages/ClaudeCode";
import { Denetim } from "./pages/Denetim";
import { GereksinimDetay } from "./pages/GereksinimDetay";
import { Gereksinimler } from "./pages/Gereksinimler";
import { Giris } from "./pages/Giris";
import { HataDetay } from "./pages/HataDetay";
import { Kod } from "./pages/Kod";
import { KontrolKulesi } from "./pages/KontrolKulesi";
import { KosuDetay, Kosular } from "./pages/Kosular";
import { ScriptDetay } from "./pages/ScriptDetay";
import { Yayin } from "./pages/Yayin";
import { ROL } from "./lib/etiketler";

function OturumGerekli({ children }: { children: ReactNode }) {
  const { kullanici, yukleniyor } = useOturum();
  const konum = useLocation();
  if (yukleniyor) return <Yukleniyor metin="Oturum kontrol ediliyor…" />;
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
  return <Navigate to={kullanici ? varsayilanSayfa(kullanici.rol) : "/giris"} replace />;
}

function Bulunamadi() {
  return (
    <Kart>
      <BosDurum baslik="Sayfa bulunamadı.">
        <Link to="/">Ana sayfaya dön</Link>
      </BosDurum>
    </Kart>
  );
}

export function Rotalar() {
  return (
    <Routes>
      <Route path="/giris" element={<Giris />} />
      <Route
        element={
          <OturumGerekli>
            <Kabuk />
          </OturumGerekli>
        }
      >
        <Route index element={<AnaSayfa />} />
        <Route path="gereksinimler" element={<Gereksinimler />} />
        <Route path="gereksinimler/:id" element={<GereksinimDetay />} />
        <Route path="gereksinimler/:id/caseler" element={<CaseReview />} />
        <Route path="gereksinimler/:id/yayin" element={<Yayin />} />
        <Route path="kod" element={<Kod />} />
        <Route path="kod/:id" element={<ScriptDetay />} />
        <Route path="kosular" element={<Kosular />} />
        <Route path="kosular/:id" element={<KosuDetay />} />
        <Route path="hatalar/:id" element={<HataDetay />} />
        <Route path="bug-taslaklari" element={<BugTaslaklari />} />
        <Route path="bug-taslaklari/:id" element={<BugTaslakDetay />} />
        <Route path="kontrol-kulesi" element={<KontrolKulesi />} />
        <Route path="denetim" element={<Denetim />} />
        <Route
          path="claude-code"
          element={
            <RolGerekli roller={["analyst"]}>
              <ClaudeCode />
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
