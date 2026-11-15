import type { ReactNode } from "react";
import { useIzin, useOturum, useOzellik } from "../auth";
import type { ProjeOzelligi } from "../api/types";
import { izinRolleri, ROL_ETIKETLERI, type Izin } from "../lib/yetki";
import { BosDurum, Kart, SayfaBasligi } from "./ui";

/** Gereken izinlerden birini taşıyan rollerin etiketleri ("Testçi / Analist"). */
export function gerekenRoller(izinler: readonly Izin[]): string {
  return [...new Set(izinler.flatMap((i) => izinRolleri(i)))].map((r) => ROL_ETIKETLERI[r]).join(" / ");
}

/**
 * Sayfa koruması (ANALIZ 012 §4.3): oturum verilen izinlerden en az birine sahip değilse ekran
 * yerine "yetkiniz yok" kartı. Kontrol çekirdektedir; bu yalnızca boş/403'lü ekranı önler.
 */
export function IzinGerekli({ izin, children }: { izin: Izin | readonly Izin[]; children: ReactNode }) {
  const istenen: Izin[] = typeof izin === "string" ? [izin] : [...izin];
  const { kullanici } = useOturum();
  const izinli = useIzin(...istenen);
  if (!kullanici || !izinli) {
    // Rota koruması sayfanın yerine çizilir: sayfa başlığı (h1) da burada (erişilebilirlik; sayfanın h1'i yok).
    return (
      <>
        <SayfaBasligi baslik="Erişim yok" />
        <Kart>
          <BosDurum baslik="Bu ekran için yetkiniz yok.">Gereken rol: {gerekenRoller(istenen)}</BosDurum>
        </Kart>
      </>
    );
  }
  return <>{children}</>;
}

/** Projede kapalı özelliğin (`/auth/me` → `ozellikler`) ekranında gösterilen metin. */
export const OZELLIK_KAPALI_EKRANI = "Bu ekran bu projede kapalı.";

/**
 * Özellik koruması: projede kapalı özelliğin ekranı (ör. `ai_agent` → Ajan ürünleri) yerine "erişim yok"
 * kartı, `IzinGerekli` ile aynı biçimde. Alan yoksa (varsayılan kip) her şey açıktır. Kontrol core'dadır
 * (kapalı Agent Probe uçları 404); bu yalnızca boş/hatalı ekranı önler.
 */
export function OzellikGerekli({ ozellik, children }: { ozellik: ProjeOzelligi; children: ReactNode }) {
  const acik = useOzellik(ozellik);
  if (!acik) {
    return (
      <>
        <SayfaBasligi baslik="Erişim yok" />
        <Kart>
          <BosDurum baslik={OZELLIK_KAPALI_EKRANI}>Açılması için proje yöneticinize başvurun.</BosDurum>
        </Kart>
      </>
    );
  }
  return <>{children}</>;
}

