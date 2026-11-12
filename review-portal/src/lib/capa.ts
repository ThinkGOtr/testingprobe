// Rota çapası (`/gereksinimler/:id#bulgular`): öneri kartındaki "Git" aynı ekranın bir bölümüne
// götürür (AI-ASISTAN-PLANI §17.4). Router hash'e kaydırmaz; sayfalar veriyi sonradan yüklediği
// için hedef öğe birkaç yüz ms içinde gelir — o süre boyunca aranır, bulununca kaydırılıp odaklanır.
import { useEffect } from "react";
import { useLocation } from "react-router-dom";

/** Aramanın aralığı ve deneme sayısı (testler kısaltabilir). */
export const capaAyar = { aralikMs: 100, deneme: 30 };

/** Öğeye kaydırır ve odak verir (odaklanamıyorsa geçici `tabIndex=-1` ile). */
export function capayaGit(el: HTMLElement): void {
  if (typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "start" });
  if (el.tabIndex < 0 && !el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
  el.focus({ preventScroll: true });
}

/**
 * Konumdaki hash'i izler; aynı adrese yeniden "Git" de (yeni konum anahtarı) yeniden kaydırır.
 * Bulunamayan çapa sessizce yok sayılır (sayfa yukarıda kalır). `hazir`: verisi geç gelen sayfa
 * (ör. ScriptDetay `#pr`) hedefi veri gelince çizer; arama o an (yeniden) başlar — kabuğun genel
 * araması süre dolup vazgeçmiş olsa da kart çizilince kaydırılır.
 */
export function useCapayaKaydir(hazir = true): void {
  const konum = useLocation();
  useEffect(() => {
    const ham = konum.hash.replace(/^#/, "");
    if (!ham || !hazir) return;
    let id: string;
    try {
      id = decodeURIComponent(ham);
    } catch {
      return;
    }
    let kalan = capaAyar.deneme;
    let zamanlayici: ReturnType<typeof setTimeout> | undefined;
    const dene = () => {
      const el = document.getElementById(id);
      if (el) {
        capayaGit(el);
        return;
      }
      if (--kalan > 0) zamanlayici = setTimeout(dene, capaAyar.aralikMs);
    };
    dene();
    return () => clearTimeout(zamanlayici);
  }, [konum.key, konum.pathname, konum.hash, hazir]);
}
