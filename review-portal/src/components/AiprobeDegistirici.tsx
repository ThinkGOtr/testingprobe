// AI Probe ürün değiştiricisi ve "Rol değiştir" (specs/010-aiprobe-sso T042–T043).
//
// Yalnız `TP_AUTH_MODE=aiprobe|both` iken üst çubukta çizilir (Kabuk); `local` kipte bileşen hiç
// yoktur. Öğe imperatif oluşturulur: `.me` bağlanmadan önce `connectedCallback` çalışırsa değiştirici
// `me-url`'e ayrıca istek atardı (TP'de `/auth/me` boşta süresini uzatır). "Rol değiştir" yalnız
// birden çok rol hesabına bağlı AI Probe oturumunda `product-menu` yuvasına konur ve `/rol-sec`
// ekranını açar. Değiştiricinin "Çıkış" bağlantısı (`aiprobe:navigate` kind=logout) yakalanır:
// TP çıkışı (`POST /auth/logout`) yapılır, yanıttaki AI Probe çıkış sayfasına gidilir.

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router-dom";
import type { Kullanici } from "../api/types";
import { useOturum } from "../auth";
import { degistiriciyiYukle, type AiprobeSwitcher } from "../lib/degistirici";
import { gezinti, useKimlikKipi } from "../lib/kimlikKipi";

/** Çıkış: AI Probe oturumunda yanıttaki çıkış sayfasına tam sayfa, değilse `/giris`. */
export function useCikis(): () => Promise<void> {
  const { cikisYap } = useOturum();
  const git = useNavigate();
  return useCallback(async () => {
    const hedef = await cikisYap();
    if (hedef) gezinti.git(hedef);
    else git("/giris", { replace: true });
  }, [cikisYap, git]);
}

/**
 * Değiştiricinin `.me`'si (CONTRACT `/auth/me` alt kümesi: `product`, `roles`, `products`, `name`).
 * `products` (ürün kodu → roller) varsa değiştirici erişimi her ürün için kesin bilir ("Ürünleriniz"
 * / "Keşfet"); yoksa yalnız bu ürünü bilir.
 */
export function degistiriciMe(k: Kullanici | null): Record<string, unknown> | null {
  if (!k) return null;
  return {
    ...(k.product ? { product: k.product } : {}),
    ...(k.products && Object.keys(k.products).length ? { products: k.products } : {}),
    roles: k.roles ?? [k.rol],
    ...(k.ad_soyad ? { name: k.ad_soyad } : {}),
  };
}

export function AiprobeDegistirici() {
  const kip = useKimlikKipi();
  const { kullanici } = useOturum();
  const cikis = useCikis();
  const git = useNavigate();
  const konum = useLocation();
  const kap = useRef<HTMLSpanElement>(null);
  const kullaniciRef = useRef(kullanici);
  kullaniciRef.current = kullanici;
  const [oge, setOge] = useState<AiprobeSwitcher | null>(null);
  const [yuva] = useState(() => {
    const d = document.createElement("div");
    d.slot = "product-menu";
    return d;
  });
  const rolDegistirVar = !!kullanici?.product && (kullanici.roles?.length ?? 0) > 1;

  const oturumVar = !!kullanici;
  useEffect(() => {
    // Öğe kullanıcı bilinince oluşturulur: `.me` bağlanmadan `connectedCallback` çalışmasın.
    if (!oturumVar) return;
    let iptal = false;
    let olusan: AiprobeSwitcher | null = null;
    degistiriciyiYukle()
      .then(() => {
        if (iptal || !kap.current) return;
        const sw = document.createElement("aiprobe-switcher") as AiprobeSwitcher;
        sw.setAttribute("product", kip.urun);
        if (kip.home) sw.setAttribute("home-origin", kip.home);
        sw.setAttribute("lang", "tr");
        sw.setAttribute("me-url", "/api/auth/me");
        sw.setAttribute("logout-url", "/giris");
        // 1.0.1 varsayılanı `post` + `me.csrf_token` formu; TP CSRF'i Origin denetimidir (token
        // yok): çıkış bağlantısı `aiprobe:navigate` ile yakalanıp TP çıkışına yönlendirilir.
        sw.setAttribute("logout-method", "get");
        sw.me = degistiriciMe(kullaniciRef.current);
        kap.current.append(sw);
        olusan = sw;
        setOge(sw);
      })
      .catch(() => {
        /* değiştirici yüklenemedi: portal onsuz çalışmaya devam eder */
      });
    return () => {
      iptal = true;
      olusan?.remove();
      setOge(null);
    };
  }, [kip.urun, kip.home, oturumVar]);

  useEffect(() => {
    if (oge) oge.me = degistiriciMe(kullanici);
  }, [oge, kullanici]);

  // "Bu ürün" bölümü yalnız yuva doluyken çizilir (değiştirici yuvanın varlığına bakar).
  useEffect(() => {
    if (!oge) return;
    if (rolDegistirVar) oge.append(yuva);
    else yuva.remove();
  }, [oge, yuva, rolDegistirVar]);

  useEffect(() => {
    if (!oge) return;
    const dinle = (e: Event) => {
      const tur = (e as CustomEvent<{ kind?: string }>).detail?.kind;
      if (tur !== "logout") return;
      e.preventDefault();
      oge.close(false);
      void cikis();
    };
    oge.addEventListener("aiprobe:navigate", dinle);
    return () => oge.removeEventListener("aiprobe:navigate", dinle);
  }, [oge, cikis]);

  const rolDegistir = () => {
    oge?.close(false);
    git(`/rol-sec?continue=${encodeURIComponent(konum.pathname + konum.search)}`);
  };

  return (
    <span ref={kap} className="aiprobe-degistirici" data-testid="aiprobe-degistirici">
      {rolDegistirVar &&
        createPortal(
          <button type="button" className="aip-menu-dugme" onClick={rolDegistir}>
            Rol değiştir
          </button>,
          yuva,
        )}
    </span>
  );
}
