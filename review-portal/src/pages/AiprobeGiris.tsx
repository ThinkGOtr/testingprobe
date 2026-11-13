// AI Probe kipinde oturum yoksa ya da düştüyse (401) AI Probe girişine tam sayfa yönlendirme
// (specs/010-aiprobe-sso T040). Dönüş adresi `continue` olarak verilir; core yalnız göreli yolu kabul
// eder. Girişten dönüşte oturum yine açılamıyorsa sonsuz döngü yerine hata kartı gösterilir.

import { useEffect, useState } from "react";
import { aiprobeGirisAdresi, cikisSurecinde, gezinti, yonlendirmeSayaciniSifirla, yonlendirmeyeIzinVar } from "../lib/kimlikKipi";

function MarkaBasligi() {
  return (
    <div className="marka marka-buyuk">
      <span className="marka-isaret" aria-hidden="true" />
      <span>
        AI Testing <strong data-metin="Probe">Probe</strong> <span className="marka-alt">İnceleme portalı</span>
      </span>
    </div>
  );
}

export function AiprobeGirisineYonlendir({ devam }: { devam: string }) {
  const [dongu, setDongu] = useState(false);
  useEffect(() => {
    // Çıkış sürerken (AI Probe çıkış sayfasına gidiliyor) yeniden giriş başlatılmaz.
    if (cikisSurecinde()) return;
    if (yonlendirmeyeIzinVar()) gezinti.git(aiprobeGirisAdresi(devam));
    else setDongu(true);
  }, [devam]);

  if (cikisSurecinde()) {
    return (
      <div className="giris-sayfa">
        <main className="giris-kart" aria-busy="true">
          <MarkaBasligi />
          <p role="status">Çıkış yapılıyor…</p>
        </main>
      </div>
    );
  }
  if (!dongu) {
    return (
      <div className="giris-sayfa">
        <main className="giris-kart" aria-busy="true">
          <MarkaBasligi />
          <p role="status">AI Probe girişine yönlendiriliyorsunuz…</p>
        </main>
      </div>
    );
  }
  return (
    <div className="giris-sayfa">
      <main className="giris-kart">
        <MarkaBasligi />
        <h1>Oturum açılamadı</h1>
        <p className="alan-hata" role="alert">
          AI Probe girişinden döndünüz ama Testing Probe oturumu açılamadı. Tarayıcınızın çerezlere izin verdiğini kontrol
          edip tekrar deneyin.
        </p>
        <a className="dugme dugme-birincil dugme-genis" href={aiprobeGirisAdresi(devam)} onClick={() => yonlendirmeSayaciniSifirla()}>
          Tekrar dene
        </a>
      </main>
    </div>
  );
}

/** Giriş ekranındaki AI Probe girişi (aiprobe kipinde tek yol, both kipinde yerel formun yanında). */
export function AiprobeGirisDugmesi({ devam, birincil }: { devam: string; birincil?: boolean }) {
  return (
    <a
      className={`dugme ${birincil ? "dugme-birincil" : "dugme-ikincil"} dugme-genis`}
      href={aiprobeGirisAdresi(devam)}
      onClick={() => yonlendirmeSayaciniSifirla()}
    >
      AI Probe hesabıyla giriş yap
    </a>
  );
}

export { MarkaBasligi };
