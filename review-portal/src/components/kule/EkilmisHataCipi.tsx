// 012/Ş8: koşu listelerinde ekilmiş hata adımı etiketi ("Ekilmiş hata: <ad>", core `run.ortam.hata_kodu`).
// Başka koşuda hiçbir şey çizmez (var olan metinler değişmez). Ton "uyari": kasıtlı kırma çipiyle aynı çizgi.
import { ekilmisHataEtiketi } from "../../lib/etiketler";
import { Cip } from "../ui";

export function EkilmisHataCipi({ kosu }: { kosu: { hata_kodu?: string | null } }) {
  const etiket = ekilmisHataEtiketi(kosu);
  if (!etiket) return null;
  return (
    <Cip ton="uyari" title="Uygulama bu koşuda bilerek bozuldu (ekilmiş hata koşusu); kırmızı beklenir.">
      {etiket}
    </Cip>
  );
}
