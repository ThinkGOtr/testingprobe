// Ekran bağlamı (AI-ASISTAN-PLANI §5.5, §17.6): asistan paneli ve Öneri düğmesi rotanın alt
// öğeleri dışında çizildiği için `useParams` kullanamaz; ekran ve varlık `useLocation` +
// `matchPath` ile `ROTA_DESENLERI` kalıplarından çıkarılır.
import { useMemo } from "react";
import { matchPath, useLocation } from "react-router-dom";
import { ROTA_DESENLERI } from "./rotalar";

/** Asistan/öneri sözleşmesindeki varlık türleri (§5.2 `probe_get.tur`). */
export type VarlikTuru = "requirement" | "case" | "script" | "run" | "failure" | "bug_draft";

export interface EkranVarligi {
  tur: VarlikTuru;
  id: string;
  /** Jira anahtarı (TPD-3); rotadan çıkarılamaz, bilen çağıran ekler. */
  anahtar?: string | null;
}

export interface EkranBaglami {
  /** Eşleşen desen (ör. `/gereksinimler/:id/caseler`); portal dışı yolda null. */
  rota_kalibi: string | null;
  /** Kullanıcıya gösterilen ekran adı (ör. "Case inceleme"). */
  ekran: string;
  varlik: EkranVarligi | null;
}

/** Desen → ekran adı (menüdeki adlarla aynı dil). */
export const EKRAN_ADLARI: Record<string, string> = {
  "/": "Ana sayfa",
  "/giris": "Giriş",
  "/gereksinimler": "Gereksinimler",
  "/gereksinimler/:id": "Gereksinim detayı",
  "/gereksinimler/:id/caseler": "Case inceleme",
  "/gereksinimler/:id/yayin": "Yayın",
  "/kod": "Kod üretimi",
  "/kod/:id": "Script detayı",
  "/kosular": "Koşular",
  "/kosular/:id": "Koşu detayı",
  "/hatalar/:id": "Hata analizi",
  "/bug-taslaklari": "Bug taslakları",
  "/bug-taslaklari/:id": "Bug taslağı",
  "/kontrol-kulesi": "Kontrol Kulesi",
  "/yol-haritasi": "Demo yol haritası",
  "/denetim": "Denetim",
  "/claude-code": "Claude Code kanalı",
  "/demo": "Demo kontrolleri",
};

/** `:id` taşıyan desenin varlık türü. */
const VARLIK_TURLERI: Record<string, VarlikTuru> = {
  "/gereksinimler/:id": "requirement",
  "/gereksinimler/:id/caseler": "requirement",
  "/gereksinimler/:id/yayin": "requirement",
  "/kod/:id": "script",
  "/kosular/:id": "run",
  "/hatalar/:id": "failure",
  "/bug-taslaklari/:id": "bug_draft",
};

/** Saf fonksiyon: yol adından ekran bağlamı (testlerde ve kanca dışında kullanılır). */
export function ekranBaglamiCikar(yolAdi: string): EkranBaglami {
  for (const desen of ROTA_DESENLERI) {
    const m = matchPath({ path: desen, end: true }, yolAdi);
    if (!m) continue;
    const tur = VARLIK_TURLERI[desen];
    const id = m.params.id;
    return {
      rota_kalibi: desen,
      ekran: EKRAN_ADLARI[desen] ?? desen,
      varlik: tur && id ? { tur, id } : null,
    };
  }
  return { rota_kalibi: null, ekran: "Bilinmeyen ekran", varlik: null };
}

/** Geçerli rotanın ekran bağlamı (rota değişince yenilenir). */
export function useEkranBaglami(): EkranBaglami {
  const { pathname } = useLocation();
  return useMemo(() => ekranBaglamiCikar(pathname), [pathname]);
}
