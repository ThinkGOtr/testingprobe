import { useEffect, useState, type ReactNode } from "react";
import { canliDerleme, cekirdekYetenekleri, ucVar, type Yetenekler } from "./api/http";
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { OlayProvider } from "./api/events";
import { OturumProvider, useIzin, useIzinler, useOturum, varsayilanSayfa } from "./auth";
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
import { Yayin } from "./pages/Yayin";
import { YolHaritasi } from "./pages/YolHaritasi";
import { ROTA_IZINLERI } from "./lib/yetki";
import { IzinGerekli } from "./components/IzinGerekli";
import { useKimlikKipi } from "./lib/kimlikKipi";
import { AiprobeGirisineYonlendir } from "./pages/AiprobeGiris";
import { RolSec } from "./pages/RolSec";

function OturumGerekli({ children }: { children: ReactNode }) {
  const { kullanici, yukleniyor } = useOturum();
  const { kip } = useKimlikKipi();
  const konum = useLocation();
  const olaylar = useIzin("events.read");
  if (yukleniyor) return <Yukleniyor metin="Oturum kontrol ediliyor…" />;
  // Yalnız AI Probe kipinde (yerel giriş kapalı) oturum yoksa doğrudan AI Probe girişine gidilir;
  // `local` ve `both` kipte giriş ekranı (both: yerel form + AI Probe düğmesi).
  if (!kullanici && kip === "aiprobe") return <AiprobeGirisineYonlendir devam={konum.pathname + konum.search} />;
  if (!kullanici) return <Navigate to="/giris" replace state={{ from: konum.pathname + konum.search }} />;
  // Canlı olaylar (SSE) `events.read` ister: Denetçi ve Görüntüleyici için akış açılmaz (ANALIZ 012 §6).
  return <OlayProvider etkin={olaylar}>{children}</OlayProvider>;
}

function AnaSayfa() {
  const { kullanici } = useOturum();
  const izinler = useIzinler();
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
  return <Navigate to={varsayilanSayfa(kullanici.rol, y ? (m, yol) => ucVar(y, m, yol) : undefined, izinler)} replace />;
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

/** Sayfa koruması: rotanın izni `ROTA_IZINLERI`'nden (ANALIZ 012 §4.2; menü ve açılış ekranı aynı tablo). */
function Korumali({ yol, children }: { yol: string; children: ReactNode }) {
  return <IzinGerekli izin={ROTA_IZINLERI[yol]}>{children}</IzinGerekli>;
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
        <Route path="gereksinimler" element={<Korumali yol="/gereksinimler"><Gereksinimler /></Korumali>} />
        <Route path="gereksinimler/:id" element={<Korumali yol="/gereksinimler/:id"><GereksinimDetay /></Korumali>} />
        <Route path="gereksinimler/:id/caseler" element={<Korumali yol="/gereksinimler/:id/caseler"><CaseReview /></Korumali>} />
        {/* Yayın ekranı kendi bilgi kartıyla korunur (aynı izin: `case.publish`). */}
        <Route path="gereksinimler/:id/yayin" element={<Yayin />} />
        <Route path="kod" element={<Korumali yol="/kod"><Kod /></Korumali>} />
        <Route path="kod/:id" element={<Korumali yol="/kod/:id"><ScriptDetay /></Korumali>} />
        <Route path="kosular" element={<Korumali yol="/kosular"><Kosular /></Korumali>} />
        <Route path="kosular/:id" element={<Korumali yol="/kosular/:id"><KosuDetay /></Korumali>} />
        <Route path="hatalar/:id" element={<Korumali yol="/hatalar/:id"><HataDetay /></Korumali>} />
        <Route path="bug-taslaklari" element={<Korumali yol="/bug-taslaklari"><BugTaslaklari /></Korumali>} />
        <Route path="bug-taslaklari/:id" element={<Korumali yol="/bug-taslaklari/:id"><BugTaslakDetay /></Korumali>} />
        <Route path="kontrol-kulesi" element={<Korumali yol="/kontrol-kulesi"><KontrolKulesi /></Korumali>} />
        <Route path="yol-haritasi" element={<Korumali yol="/yol-haritasi"><YolHaritasi /></Korumali>} />
        <Route path="denetim" element={<Korumali yol="/denetim"><Denetim /></Korumali>} />
        <Route path="claude-code" element={<Korumali yol="/claude-code"><ClaudeCode /></Korumali>} />
        <Route path="demo" element={<Korumali yol="/demo"><DemoKontrolleri /></Korumali>} />
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
