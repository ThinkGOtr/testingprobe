import { useCallback, useEffect, useState } from "react";

/**
 * Tema tercihi (tasarım planı §3.1).
 *
 * - Varsayılan **koyu** (marka yüzü). `index.html` `data-theme="dark"` ile gelir; `src/tema-on.js`
 *   (klasik betik, paketten önce) kayıtlı tercihi ilk boyamadan önce uygular (açık/sistem kullanıcıda koyu
 *   yanıp sönmez; kurallar burayla aynı, depolamaya yazmaz). `main.tsx` render'dan önce yine
 *   `temaUygula(temaOku())` çağırır (göç + yedek), böylece Kabuk dışındaki `/giris` de doğru temada açılır.
 * - `html` özniteliği sözleşmesi: koyu → `data-theme="dark"`, açık → `data-theme="light"`,
 *   sistem → öznitelik yok (stil dosyası `prefers-color-scheme` ile karar verir).
 * - Tercih yalnız kullanıcı temayı değiştirdiğinde yazılır; açılışta (mount) `tp-tema` yazılmaz.
 * - **Göç:** eski sürüm her açılışta `tp-tema=sistem` yazıyordu; o kayıt koyu varsayılanı gizlerdi.
 *   `tp-tema-v=2` işareti yoksa eski değer **silinir** (yalnız yok saymak ikinci açılışta `sistem`'i
 *   geri getirirdi) ve işaret yazılır.
 */
export type Tema = "sistem" | "acik" | "koyu";

export const TEMA_ANAHTARI = "tp-tema";
export const TEMA_SURUM_ANAHTARI = "tp-tema-v";
export const TEMA_SURUMU = "2";
export const VARSAYILAN_TEMA: Tema = "koyu";

/** Döngü: koyu → açık → sistem → koyu. */
const SONRAKI: Record<Tema, Tema> = { koyu: "acik", acik: "sistem", sistem: "koyu" };

export const TEMA_ETIKETI: Record<Tema, string> = { sistem: "Tema: sistem", acik: "Tema: açık", koyu: "Tema: koyu" };

function taninan(t: string | null): t is Tema {
  return t === "sistem" || t === "acik" || t === "koyu";
}

/** `tp-tema-v=2` yoksa eski `tp-tema` kaydını siler ve işareti yazar. */
function gocEt(depo: Storage): void {
  if (depo.getItem(TEMA_SURUM_ANAHTARI) === TEMA_SURUMU) return;
  depo.removeItem(TEMA_ANAHTARI);
  depo.setItem(TEMA_SURUM_ANAHTARI, TEMA_SURUMU);
}

/** Kayıtlı tercihi okur (gerekirse göç eder). Depolama yoksa/hata verirse ya da değer tanınmazsa koyu. */
export function temaOku(): Tema {
  try {
    const depo = window.localStorage;
    gocEt(depo);
    const t = depo.getItem(TEMA_ANAHTARI);
    if (taninan(t)) return t;
  } catch {
    /* depolama yok ya da erişim engelli */
  }
  return VARSAYILAN_TEMA;
}

/** Tercihi kalıcı yazar; yalnız kullanıcı temayı değiştirdiğinde çağrılır. */
export function temaKaydet(tema: Tema): void {
  try {
    const depo = window.localStorage;
    depo.setItem(TEMA_SURUM_ANAHTARI, TEMA_SURUMU);
    depo.setItem(TEMA_ANAHTARI, tema);
  } catch {
    /* yoksay: tercih yalnız bu oturumda geçerli olur */
  }
}

/** `html` öğesine temayı uygular (koyu → dark, açık → light, sistem → öznitelik yok). */
export function temaUygula(tema: Tema): void {
  try {
    const kok = document.documentElement;
    if (tema === "sistem") kok.removeAttribute("data-theme");
    else kok.setAttribute("data-theme", tema === "acik" ? "light" : "dark");
  } catch {
    /* DOM yok (SSR/test dışı ortam) */
  }
}

export function sonrakiTema(tema: Tema): Tema {
  return SONRAKI[tema];
}

/** Kabuk'taki tema düğmesi için durum. Efekt yalnız uygular; yazma yalnız `degistir` içinde. */
export function useTema(): [Tema, () => void] {
  const [tema, setTema] = useState<Tema>(temaOku);
  useEffect(() => {
    temaUygula(tema);
  }, [tema]);
  const degistir = useCallback(() => {
    const yeni = sonrakiTema(tema);
    temaKaydet(yeni);
    setTema(yeni);
  }, [tema]);
  return [tema, degistir];
}
