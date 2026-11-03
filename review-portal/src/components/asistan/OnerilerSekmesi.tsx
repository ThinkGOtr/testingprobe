// Asistan panelinin "Öneriler" sekmesi (AI-ASISTAN-PLANI §17.6). İçeriği Öneri şeridi (G)
// doldurur: kural önerileri, "Neden? Sor" (`acSekme("sohbet", {oneriKuralId, soru})`),
// "Yaptım"/"Gizle", "Başka ne yapabilirim?". Panel bu bileşeni sekme kabında çizer; imza
// sözleşmedir (panel değişmeden içerik değiştirilebilir).
import type { AsistanDurumu } from "../../api/asistan";
import type { EkranBaglami } from "../../lib/ekranBaglami";
import { BosDurum } from "../ui";

export interface OnerilerSekmesiOzellikleri {
  ekran: EkranBaglami;
  /** Asistan durumu (model kapalıyken "Başka ne yapabilirim?" gizlenir); asistan kapalıyken null. */
  asistan: AsistanDurumu | null;
  /** Öneri düğmesi/bağlantısıyla açıldıysa vurgulanacak kural. */
  oneriKuralId?: string | null;
  /** "Git" sonrası (mobilde panel kapanır). */
  onGit?: () => void;
}

export function OnerilerSekmesi({ ekran }: OnerilerSekmesiOzellikleri) {
  return (
    <div className="asistan-oneriler-sekmesi" data-testid="oneriler-sekmesi">
      <BosDurum baslik="Bu ekranda sizin için bekleyen bir iş yok.">
        {ekran.ekran}: kural tabanlı öneriler bu sekmede listelenir.
      </BosDurum>
    </div>
  );
}
