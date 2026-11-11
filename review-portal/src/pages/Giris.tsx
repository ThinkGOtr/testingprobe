import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { hataMesaji, mockZorunlu } from "../api/http";
import { useOturum } from "../auth";
import { useKimlikKipi } from "../lib/kimlikKipi";
import { AiprobeGirisDugmesi, MarkaBasligi } from "./AiprobeGiris";

export function Giris() {
  const { kullanici, girisYap } = useOturum();
  const [ad, setAd] = useState("");
  const [parola, setParola] = useState("");
  const [hata, setHata] = useState<string | null>(null);
  const [gonderiliyor, setGonderiliyor] = useState(false);
  const git = useNavigate();
  const konum = useLocation();
  const hedef = (konum.state as { from?: string } | null)?.from;
  const { kip } = useKimlikKipi();

  // Rol bazlı açılış "/" (AnaSayfa) üzerinden: canlı derlemede core'un sunduğu ekranlara göre seçilir.
  if (kullanici) return <Navigate to={hedef ?? "/"} replace />;

  // TP_AUTH_MODE=aiprobe: yerel giriş kapalı (core `/auth/login` 404); tek yol AI Probe hesabı.
  if (kip === "aiprobe") {
    return (
      <div className="giris-sayfa">
        <main className="giris-kart">
          <MarkaBasligi />
          <h1>Oturum aç</h1>
          <p className="soluk">Testing Probe'a AI Probe hesabınızla girersiniz. Her karar adınıza kayıt altına alınır.</p>
          <AiprobeGirisDugmesi devam={hedef ?? "/"} birincil />
        </main>
      </div>
    );
  }

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
            AI Testing <strong data-metin="Probe">Probe</strong> <span className="marka-alt">İnceleme portalı</span>
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
        {kip === "both" && (
          <div className="giris-aiprobe">
            <p className="giris-ayrac" aria-hidden="true">
              <span>ya da</span>
            </p>
            <AiprobeGirisDugmesi devam={hedef ?? "/"} />
          </div>
        )}
        <details className="giris-ipucu">
          <summary>Demo kullanıcıları</summary>
          <ul>
            <li>
              <code>sunucu</code> — Sistem Yöneticisi: demo kontrolleri ve sistem işletimi
            </li>
            <li>
              <code>analist</code> — Analist: gereksinim içe aktarma, ön inceleme, case son onayı
            </li>
            <li>
              <code>po</code> — PO: baz değer ve doküman düzeltmesi (PO onayı Jira'da)
            </li>
            <li>
              <code>testci</code> — Testçi: case üretimi, kararı ve yayını; bug kararı
            </li>
            <li>
              <code>muhendis</code> — Automation Engineer: kod üretimi, kırarak doğrulama, merge, koşu tetikleri
            </li>
            <li>
              <code>gelistirici</code> — Developer: onaylı case'ler ve koşular; manuel koşu
            </li>
            <li>
              <code>denetci</code> — Denetçi: denetim kaydı (salt okunur)
            </li>
            <li>
              <code>izleyici</code> — Görüntüleyici: Kontrol Kulesi ve koşu özetleri
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
