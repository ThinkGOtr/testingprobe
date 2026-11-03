// Asistanın yetenek kapısı (AI-ASISTAN-PLANI §11):
// - core'un uç listesi okunurken (yüklenirken) düğme gizli;
// - uç listesi biliniyor ve `GET /assistant/status` yoksa gizli (canlı derlemede "bu fazda yok";
//   örnek veri derlemesinde de asistanın örnek cevabı her ekrana "ÖRNEK VERİ" bandı düşürmesin);
// - uç listesi bilinmiyorsa (`null`: örnek veri derlemesi / keşif kapalı) görünür;
// - status isteği `buFazdaYok` → gizli; `etkin=false` → pasif + neden ipucu.
// Kabuk'taki `useCanliYetenekler` yüklenirken de `null` döndürdüğü için ("hepsi etkin") burada
// yükleme durumunu ayıran ayrı bir kanca kullanılır.
import { useCallback, useEffect, useRef, useState } from "react";
import { asistanApi, kapaliNedeni, type AsistanDurumu } from "../../api/asistan";
import { buFazdaYok, cekirdekYetenekleri, hataMesaji, ucVar } from "../../api/http";

export type AsistanKapisi =
  | { tur: "yukleniyor" }
  | { tur: "gizli" }
  | { tur: "pasif"; neden: string; asistan: AsistanDurumu | null }
  | { tur: "hazir"; asistan: AsistanDurumu };

export function useAsistanKapisi(): { kapi: AsistanKapisi; yenile: () => Promise<void> } {
  const [kapi, setKapi] = useState<AsistanKapisi>({ tur: "yukleniyor" });
  const bagli = useRef(true);
  const ucVarMi = useRef<boolean | null>(null);

  const durumOku = useCallback(async () => {
    try {
      const d = await asistanApi.durum();
      if (!bagli.current) return;
      setKapi(d.etkin ? { tur: "hazir", asistan: d } : { tur: "pasif", neden: kapaliNedeni(d.neden), asistan: d });
    } catch (e) {
      if (!bagli.current) return;
      if (buFazdaYok(e)) setKapi({ tur: "gizli" });
      else setKapi({ tur: "pasif", neden: `Asistan durumu okunamadı: ${hataMesaji(e)}`, asistan: null });
    }
  }, []);

  useEffect(() => {
    bagli.current = true;
    void (async () => {
      const y = await cekirdekYetenekleri();
      if (!bagli.current) return;
      if (y && !ucVar(y, "GET", "/assistant/status")) {
        ucVarMi.current = false;
        setKapi({ tur: "gizli" });
        return;
      }
      ucVarMi.current = true;
      await durumOku();
    })();
    return () => {
      bagli.current = false;
    };
  }, [durumOku]);

  const yenile = useCallback(async () => {
    if (ucVarMi.current) await durumOku();
  }, [durumOku]);

  return { kapi, yenile };
}
