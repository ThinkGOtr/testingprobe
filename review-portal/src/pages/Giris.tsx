import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { hataMesaji, mockZorunlu } from "../api/http";
import { useOturum } from "../auth";

export function Giris() {
  const { kullanici, girisYap } = useOturum();
  const [ad, setAd] = useState("");
  const [parola, setParola] = useState("");
  const [hata, setHata] = useState<string | null>(null);
  const [gonderiliyor, setGonderiliyor] = useState(false);
  const git = useNavigate();
  const konum = useLocation();
  const hedef = (konum.state as { from?: string } | null)?.from;

  // Rol bazlı açılış "/" (AnaSayfa) üzerinden: canlı derlemede core'un sunduğu ekranlara göre seçilir.
  if (kullanici) return <Navigate to={hedef ?? "/"} replace />;

  async function gonder(e: FormEvent) {
    e.preventDefault();
    if (!ad.trim() || !parola) {
      setHata("Kullanıcı adı ve parola zorunlu.");
      return;
    }
    setGonderiliyor(true);
    setHata(null);
    try {
      await girisYap(ad.trim(), parola);
      git(hedef ?? "/", { replace: true });
    } catch (err) {
      setHata(hataMesaji(err));
    } finally {
      setGonderiliyor(false);
    }
  }

  return (
    <div className="giris-sayfa">
      <main className="giris-kart">
        <div className="marka marka-buyuk">
          <span className="marka-isaret" aria-hidden="true" />
          <span>
            AI Testing Probe <span className="marka-alt">İnceleme portalı</span>
          </span>
        </div>
        <h1>Oturum aç</h1>
        <p className="soluk">AI üretir, insan onaylar. Her karar adınıza kayıt altına alınır.</p>
        <form onSubmit={gonder} noValidate>
          <div className="alan">
            <label htmlFor="kullanici-adi">Kullanıcı adı</label>
            <input
              id="kullanici-adi"
              name="kullanici_adi"
              autoComplete="username"
              value={ad}
              onChange={(e) => setAd(e.target.value)}
              aria-invalid={!!hata || undefined}
              aria-describedby={hata ? "giris-hata" : undefined}
              autoFocus
            />
          </div>
          <div className="alan">
            <label htmlFor="parola">Parola</label>
            <input
              id="parola"
              name="parola"
              type="password"
              autoComplete="current-password"
              value={parola}
              onChange={(e) => setParola(e.target.value)}
              aria-invalid={!!hata || undefined}
              aria-describedby={hata ? "giris-hata" : undefined}
            />
          </div>
          {hata && (
            <p id="giris-hata" className="alan-hata" role="alert">
              {hata}
            </p>
          )}
          <button type="submit" className="dugme dugme-birincil dugme-genis" disabled={gonderiliyor} aria-busy={gonderiliyor || undefined}>
            {gonderiliyor ? "Giriş yapılıyor…" : "Giriş yap"}
          </button>
        </form>
        <details className="giris-ipucu">
          <summary>Demo kullanıcıları</summary>
          <ul>
            <li>
              <code>analist</code> — gereksinim, bulgu ve case kararları
            </li>
            <li>
              <code>po</code> — serbest metin gereksinimlerde PO teyidi
            </li>
            <li>
              <code>muhendis</code> — kod üretimi, kırarak doğrulama, merge
            </li>
            <li>
              <code>testci</code> — bug taslağı onayı
            </li>
            <li>
              <code>sunucu</code> — deploy/gece tetikleri ve demo kontrolleri
            </li>
          </ul>
          <p className="soluk">
            {mockZorunlu()
              ? "Örnek veri modu: herhangi bir boş olmayan parola kabul edilir."
              : "Parola .env dosyasındaki SEED_USER_PASSWORD değeridir."}
          </p>
        </details>
      </main>
    </div>
  );
}
