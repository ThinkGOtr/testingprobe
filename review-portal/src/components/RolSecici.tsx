// Üst çubukta (sağ üst) etkin rol + atanmış rollerin listesi ve doğrudan geçiş.
//
// Kişinin AI Probe'da atanmış her Testing Probe rolü için ayrı bir rol hesabı vardır (JIT,
// `kimlik_bagi`); geçiş `POST /auth/aiprobe/rol-degistir` ile parola sormadan yapılır ve sonraki
// kararlar seçilen rol hesabı adına kaydedilir. Tek rollü oturumda ya da `local` kipte yalnız etkin
// rol etiketi gösterilir. Liste açılırken taze okunur (rol AI Probe'dan kaldırıldıysa görünmez).

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { hataMesaji } from "../api/http";
import type { AiprobeHesabi } from "../api/types";
import { useOturum } from "../auth";
import { useKimlikKipi } from "../lib/kimlikKipi";
import { rolEtiketi } from "../lib/yetki";
import { useBildirim } from "./Bildirim";

export function RolSecici() {
  const { kullanici, oturumKur } = useOturum();
  const kip = useKimlikKipi();
  const git = useNavigate();
  const bildir = useBildirim();
  const kap = useRef<HTMLDivElement>(null);
  const [acik, setAcik] = useState(false);
  const [hesaplar, setHesaplar] = useState<AiprobeHesabi[] | null>(null);
  const [hata, setHata] = useState<string | null>(null);
  const [gonderilen, setGonderilen] = useState<string | null>(null);

  const cokRollu = kip.kip !== "local" && !!kullanici?.product && (kullanici.roles?.length ?? 0) > 1;

  useEffect(() => {
    if (!acik) return;
    let iptal = false;
    setHata(null);
    api
      .aiprobeHesaplar()
      .then((v) => !iptal && setHesaplar(v.hesaplar))
      .catch((e: unknown) => !iptal && setHata(hataMesaji(e)));
    const disTik = (e: MouseEvent) => {
      if (kap.current && !kap.current.contains(e.target as Node)) setAcik(false);
    };
    const tus = (e: KeyboardEvent) => {
      if (e.key === "Escape") setAcik(false);
    };
    document.addEventListener("mousedown", disTik);
    document.addEventListener("keydown", tus);
    return () => {
      iptal = true;
      document.removeEventListener("mousedown", disTik);
      document.removeEventListener("keydown", tus);
    };
  }, [acik]);

  if (!kullanici) return null;
  if (!cokRollu) return <span className="kullanici-rol">{rolEtiketi(kullanici.rol)}</span>;

  async function sec(h: AiprobeHesabi) {
    if (!kullanici || h.id === kullanici.id) {
      setAcik(false);
      return;
    }
    setGonderilen(h.id);
    setHata(null);
    try {
      const k = await api.aiprobeRolDegistir(h.id);
      oturumKur(k);
      setAcik(false);
      bildir(`Rol değiştirildi: ${rolEtiketi(k.rol)}.`);
      // Yeni rolün açılış ekranı (önceki ekran bu rolde olmayabilir).
      git("/", { replace: true });
    } catch (e) {
      setHata(hataMesaji(e));
    } finally {
      setGonderilen(null);
    }
  }

  return (
    <div className="rol-secici" ref={kap}>
      <button
        type="button"
        className="kullanici-rol rol-secici-dugme"
        aria-haspopup="menu"
        aria-expanded={acik}
        aria-label={`Etkin rol: ${rolEtiketi(kullanici.rol)} (rol değiştir)`}
        onClick={() => setAcik((a) => !a)}
      >
        {rolEtiketi(kullanici.rol)} <span aria-hidden="true">▾</span>
      </button>
      {acik && (
        <div className="rol-secici-menu" role="menu" aria-label="Atanmış roller">
          <p className="rol-secici-baslik">Rolleriniz</p>
          {!hesaplar && !hata && <p className="soluk" role="status">Yükleniyor…</p>}
          {hata && (
            <p className="alan-hata" role="alert">
              {hata}
            </p>
          )}
          {hesaplar?.map((h) => {
            const aktif = h.id === kullanici.id;
            return (
              <button
                key={h.id}
                type="button"
                role="menuitemradio"
                aria-checked={aktif}
                className={`rol-secici-oge${aktif ? " aktif" : ""}`}
                disabled={gonderilen !== null}
                onClick={() => void sec(h)}
              >
                <span>{rolEtiketi(h.rol)}</span>
                {aktif && <span className="rol-secici-isaret">etkin</span>}
                {gonderilen === h.id && <span className="soluk">geçiliyor…</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
