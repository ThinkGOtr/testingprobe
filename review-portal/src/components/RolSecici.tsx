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
import type { AiprobeHesabi, Kullanici } from "../api/types";
import { useOturum } from "../auth";
import { useKimlikKipi } from "../lib/kimlikKipi";
import { rolEtiketi } from "../lib/yetki";
import { useBildirim } from "./Bildirim";

/** `/auth/me` yarışında (yeni oturum çerezi yazılmadan 401) bir kez yeniden denemeden önce beklenen süre. */
export const ME_YENIDEN_DENEME_MS = 400;

/**
 * Rol değişiminden sonra kurulacak oturum: `/auth/me` tam oturumu verirse o; vermezse (401 — yeni
 * çerez henüz yazılmamış) rol değiştir yanıtındaki `k`. `k` kişiye ait `roles`/`product`/`products`/
 * `kisiler` alanlarını taşımaz: seçici kaybolmasın diye önceki oturumdan (aynı kişi) alınır. Rol
 * izinleri (`izinler`) önceki rolden asla taşınmaz.
 */
export function rolDegisimOturumu(k: Kullanici, onceki: Kullanici | null): Kullanici {
  if (!onceki) return k;
  return {
    ...k,
    roles: k.roles ?? onceki.roles,
    product: k.product ?? onceki.product,
    products: k.products ?? onceki.products,
    kisiler: k.kisiler ?? onceki.kisiler,
    ad_soyad: k.ad_soyad ?? onceki.ad_soyad,
    ad_kaynak: k.ad_kaynak ?? onceki.ad_kaynak,
  };
}

/** `/auth/me`; 401 ise kısa beklemeyle bir kez daha; yine olmazsa null. */
async function tamOturum(): Promise<Kullanici | null> {
  try {
    return await api.me();
  } catch {
    await new Promise((r) => setTimeout(r, ME_YENIDEN_DENEME_MS));
    return api.me().catch(() => null);
  }
}

export function RolSecici() {
  const { kullanici, oturumKur } = useOturum();
  const kip = useKimlikKipi();
  const git = useNavigate();
  const bildir = useBildirim();
  const kap = useRef<HTMLDivElement>(null);
  const dugme = useRef<HTMLButtonElement>(null);
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
    // Escape yalnız rol listesini kapatır: yakalama (capture) evresinde tüketilir ki mobil çekmecenin
    // (Kabuk) document dinleyicisi çekmeceyi de kapatmasın (defaultPrevented + yayılım durur). Odak rol
    // düğmesine döner.
    const tus = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      setAcik(false);
      dugme.current?.focus();
    };
    document.addEventListener("mousedown", disTik);
    document.addEventListener("keydown", tus, true);
    return () => {
      iptal = true;
      document.removeEventListener("mousedown", disTik);
      document.removeEventListener("keydown", tus, true);
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
      // Yanıtta `roles`/`product` yok: seçicinin kaybolmaması için tam oturum /auth/me'den. me 401
      // dönerse (yeni çerez yazılmadan yarış) oturum yanıttaki `k` ile kurulur ve akış sürer.
      oturumKur((await tamOturum()) ?? rolDegisimOturumu(k, kullanici));
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
        ref={dugme}
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
