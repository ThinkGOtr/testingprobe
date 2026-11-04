// Kabuk ile asistan paneli arasında paylaşılan yerleşim durumu (AI-ASISTAN-PLANI §11 "Kabuk adımı").
// Yan menü 860 px ve altında üst çubuğun altından açılan kipsel çekmecedir (içerik inert, perde karartır).
// 760–860 px'de panel (420 px, z 40) perdenin (z 29) üstünde kalır; ikisi birlikte açık olsaydı kipsel menünün
// yanında karartılmamış, tıklanabilir ikinci bir bölge dururdu. Bu yüzden bu genişlikte ikisi birbirini dışlar:
// panel açılınca çekmece, çekmece açılınca panel kapanır (< 760 px'de panel tam ekran modaldır, menüye
// ulaşılamaz). Panelin açık/kapalı bilgisi `asistan/kontrol` deposundan okunur; bu bağlam yalnız Kabuk'a ait
// durumu (yan menü) taşır.
import { createContext, useContext, useEffect, useMemo, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";
import { paneliKapat, useAsistanKontrol } from "./asistan/kontrol";

/** Bu genişlikte ve altında yan menü çekmecedir (styles.css `@media (max-width: 860px)` ile aynı). */
export const YAN_MENU_CEKMECE_PX = 860;

export interface KabukDurumu {
  /** Dar ekranda yan menü çekmecesi açık mı. */
  menuAcik: boolean;
  menuAyarla: Dispatch<SetStateAction<boolean>>;
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
  const [menuAcik, menuAyarla] = useState(false);
  const { acik: panelAcik } = useAsistanKontrol();
  const oncekiPanel = useRef(panelAcik);
  const oncekiMenu = useRef(menuAcik);

  // Yalnız geçişlerde ve çekmece genişliğinde: panel açılınca menü, menü açılınca panel kapanır.
  useEffect(() => {
    const panelAcildi = panelAcik && !oncekiPanel.current;
    const menuAcildi = menuAcik && !oncekiMenu.current;
    oncekiPanel.current = panelAcik;
    oncekiMenu.current = menuAcik;
    if (!cekmeceGenisligi()) return;
    if (panelAcildi && menuAcik) menuAyarla(false);
    else if (menuAcildi && panelAcik) paneliKapat();
  }, [panelAcik, menuAcik]);

  const deger = useMemo(() => ({ menuAcik, menuAyarla }), [menuAcik]);
  return <Baglam.Provider value={deger}>{children}</Baglam.Provider>;
}

/** Paylaşılan Kabuk durumu; sağlayıcı dışında `null`. */
export function useKabukDurumu(): KabukDurumu | null {
  return useContext(Baglam);
}
