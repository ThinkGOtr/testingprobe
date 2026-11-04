// Kabuk ile asistan paneli arasında paylaşılan yerleşim durumu (AI-ASISTAN-PLANI §11 "Kabuk adımı").
// Yan menü 860 px ve altında üst çubuğun altından açılan çekmecedir; bu genişlikte asistan paneli
// açılınca çekmece kapanır (760–860 px'de 420 px'lik panel ile çekmece ekrana birlikte sığmaz,
// < 760 px'de panel zaten tam ekran modaldır). Panelin açık/kapalı bilgisi `asistan/kontrol` deposundan
// okunur; bu bağlam yalnız Kabuk'a ait durumu (yan menü) taşır ve panelin durumunu yansıtır.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";
import { useAsistanKontrol } from "./asistan/kontrol";

/** Bu genişlikte ve altında yan menü çekmecedir (styles.css `@media (max-width: 860px)` ile aynı). */
export const YAN_MENU_CEKMECE_PX = 860;

export interface KabukDurumu {
  /** Dar ekranda yan menü çekmecesi açık mı. */
  menuAcik: boolean;
  menuAyarla: Dispatch<SetStateAction<boolean>>;
  /** Asistan paneli açık mı (kontrol deposunun yansıması). */
  panelAcik: boolean;
}

const Baglam = createContext<KabukDurumu | null>(null);

function cekmeceGenisligi(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(`(max-width: ${YAN_MENU_CEKMECE_PX}px)`).matches
  );
}

export function KabukDurumuSaglayici({ children }: { children: ReactNode }) {
  const [menuAcik, setMenuAcik] = useState(false);
  const { acik: panelAcik } = useAsistanKontrol();
  const oncekiPanel = useRef(panelAcik);

  // Panel kapalıdan açığa geçince (yalnız geçişte) çekmece genişliğinde yan menüyü kapat.
  useEffect(() => {
    const acildi = panelAcik && !oncekiPanel.current;
    oncekiPanel.current = panelAcik;
    if (acildi && cekmeceGenisligi()) setMenuAcik(false);
  }, [panelAcik]);

  const menuAyarla = useCallback<Dispatch<SetStateAction<boolean>>>((v) => setMenuAcik(v), []);
  const deger = useMemo(() => ({ menuAcik, menuAyarla, panelAcik }), [menuAcik, menuAyarla, panelAcik]);
  return <Baglam.Provider value={deger}>{children}</Baglam.Provider>;
}

/** Paylaşılan Kabuk durumu; sağlayıcı dışında `null`. */
export function useKabukDurumu(): KabukDurumu | null {
  return useContext(Baglam);
}
