// `/rol-sec` — AI Probe rol seçici ve "Rol değiştir" (specs/010-aiprobe-sso US2, T041).
//
// - Girişte (seçim çerezi): kişi birden çok TP rol hesabına bağlıysa core callback buraya yönlenir;
//   `GET /auth/aiprobe/hesaplar` aday hesapları ve dönüş yolunu (`continue`) verir, seçim
//   `POST /auth/aiprobe/rol-sec` ile oturumu açar.
// - Açık AI Probe oturumunda (değiştiricideki "Rol değiştir"): aynı uç `aktif_id` ile döner, seçim
//   `POST /auth/aiprobe/rol-degistir` (parola yok; sunucu bağı ve rolü taze kontrolle doğrular, yeni
//   oturum kimliği verir).
// Her karar seçilen rol hesabı adına kaydedilir (İlke I, VIII). `local` kipte ekran yoktur (`/`).

import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { ApiError, hataMesaji } from "../api/http";
import type { AiprobeHesaplari, AiprobeHesabi } from "../api/types";
import { useOturum } from "../auth";
import { useBildirim } from "../components/Bildirim";
import { ROL } from "../lib/etiketler";
import { aiprobeGirisAdresi, guvenliDevam, useKimlikKipi } from "../lib/kimlikKipi";
import { MarkaBasligi } from "./AiprobeGiris";

type Durum =
  | { tur: "yukleniyor" }
  | { tur: "hazir"; veri: AiprobeHesaplari }
  | { tur: "hata"; status: number; mesaj: string };

function hataDurumu(e: unknown): Durum {
  return { tur: "hata", status: e instanceof ApiError ? e.status : 0, mesaj: hataMesaji(e) };
}

export function RolSec() {
  const { kullanici, yukleniyor, oturumKur } = useOturum();
  const kip = useKimlikKipi();
  const [parametreler] = useSearchParams();
  const git = useNavigate();
  const bildir = useBildirim();
  const [durum, setDurum] = useState<Durum>({ tur: "yukleniyor" });
  const [gonderilen, setGonderilen] = useState<string | null>(null);
  const [islemHatasi, setIslemHatasi] = useState<string | null>(null);
  const [deneme, setDeneme] = useState(0);
  const parametreDevam = guvenliDevam(parametreler.get("continue"));

  useEffect(() => {
    if (yukleniyor || kip.kip === "local") return;
    let iptal = false;
    setDurum({ tur: "yukleniyor" });
    api
      .aiprobeHesaplar()
      .then((veri) => !iptal && setDurum({ tur: "hazir", veri }))
      .catch((e: unknown) => !iptal && setDurum(hataDurumu(e)));
    return () => {
      iptal = true;
    };
  }, [yukleniyor, kip.kip, deneme]);

  if (!yukleniyor && kip.kip === "local") return <Navigate to="/" replace />;

  const degistir = durum.tur === "hazir" && !!durum.veri.aktif_id;
  const devam = durum.tur === "hazir" && durum.veri.continue ? guvenliDevam(durum.veri.continue) : parametreDevam;

  async function sec(h: AiprobeHesabi) {
    setGonderilen(h.id);
    setIslemHatasi(null);
    try {
      if (degistir) {
        const k = await api.aiprobeRolDegistir(h.id);
        oturumKur(k);
        bildir(`Rol değiştirildi: ${ROL[k.rol] ?? k.rol}.`);
        // Yeni rolün açılış ekranı (önceki ekran bu rolde olmayabilir).
        git("/", { replace: true });
      } else {
        const { continue: donus, ...k } = await api.aiprobeRolSec(h.id);
        oturumKur(k);
        git(guvenliDevam(donus ?? devam), { replace: true });
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setDurum(hataDurumu(e));
      else setIslemHatasi(hataMesaji(e));
    } finally {
      setGonderilen(null);
    }
  }

  return (
    <div className="giris-sayfa">
      <main className="giris-kart rol-sec" aria-busy={durum.tur === "yukleniyor" || undefined}>
        <MarkaBasligi />
        <h1>{degistir ? "Rol değiştir" : "Rol seçin"}</h1>
        {durum.tur === "yukleniyor" && <p role="status">Rol hesaplarınız yükleniyor…</p>}
        {durum.tur === "hata" && (
          <>
            <p className="alan-hata" role="alert">
              {durum.status === 401
                ? kullanici
                  ? "Oturumunuz sonlandı; yeniden giriş yapın."
                  : "Rol seçiminin süresi doldu; yeniden giriş yapın."
                : durum.mesaj}
            </p>
            {durum.status === 401 || durum.status === 0 ? (
              <a className="dugme dugme-birincil dugme-genis" href={aiprobeGirisAdresi(devam)}>
                Yeniden giriş yap
              </a>
            ) : (
              <button type="button" className="dugme dugme-birincil dugme-genis" onClick={() => setDeneme((n) => n + 1)}>
                Tekrar dene
              </button>
            )}
          </>
        )}
        {durum.tur === "hazir" && (
          <>
            <p className="soluk">
              {degistir
                ? "Parola girmeden diğer rol hesabınıza geçersiniz. Bundan sonraki kararlar seçtiğiniz rol adına kaydedilir."
                : "AI Probe hesabınız birden çok Testing Probe rolüne bağlı. Bu oturumda hangi rolle çalışacağınızı seçin; kararlar seçtiğiniz rol adına kaydedilir."}
            </p>
            {durum.veri.hesaplar.length === 0 ? (
              <p className="alan-hata" role="alert">
                Bu AI Probe hesabına bağlı kullanılabilir rol hesabı yok.
              </p>
            ) : (
              <ul className="rol-secenekleri" aria-label="Rol hesapları">
                {durum.veri.hesaplar.map((h) => {
                  const aktif = h.id === durum.veri.aktif_id;
                  return (
                    <li key={h.id}>
                      <button
                        type="button"
                        className={`rol-secenek${aktif ? " aktif" : ""}`}
                        disabled={aktif || gonderilen !== null}
                        aria-busy={gonderilen === h.id || undefined}
                        aria-current={aktif ? "true" : undefined}
                        onClick={() => void sec(h)}
                      >
                        <span className="rol-secenek-rol">{ROL[h.rol] ?? h.rol}</span>
                        <span className="rol-secenek-ad">{h.gorunen_ad}</span>
                        <span className="rol-secenek-not">{aktif ? "Şu anki rolünüz" : h.kullanici_adi}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
            {islemHatasi && (
              <p className="alan-hata" role="alert">
                {islemHatasi}
              </p>
            )}
            {degistir && (
              <p>
                <Link to={parametreDevam}>Vazgeç</Link>
              </p>
            )}
          </>
        )}
      </main>
    </div>
  );
}
