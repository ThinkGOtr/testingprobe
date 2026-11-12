// Jira tetiğiyle alınan story'nin otomatik akış rozeti (013 §9, K15). "Durdu" ise neden görünür
// metin olarak yazılır (yalnız title'da kalmaz): analist akışı elle sürdürmesi gerektiğini görür.
import type { OtomatikAkis } from "../api/types";
import type { Ton } from "../lib/etiketler";
import { tarih } from "../lib/format";
import { Cip } from "./ui";

export const OTOMATIK_AKIS: Record<OtomatikAkis["durum"], { etiket: string; ton: Ton }> = {
  suruyor: { etiket: "Otomatik akış sürüyor", ton: "bilgi" },
  durdu: { etiket: "Otomatik akış durdu", ton: "uyari" },
  tamam: { etiket: "Otomatik akış tamam", ton: "basari" },
};

export function OtomatikAkisRozeti({ akis }: { akis: OtomatikAkis | null | undefined }) {
  if (!akis) return null;
  const e = OTOMATIK_AKIS[akis.durum];
  const ipucu = `Jira tetiğiyle alındı${akis.tetik_zamani ? `: ${tarih(akis.tetik_zamani)}` : ""}`;
  return (
    <span className="otomatik-akis" data-testid="otomatik-akis" data-durum={akis.durum}>
      <Cip ton={e.ton} title={ipucu}>
        {e.etiket}
      </Cip>
      {akis.durum === "durdu" && (
        <span className="soluk kucuk otomatik-akis-neden">{akis.neden ? ` ${akis.neden}; elle sürdürün.` : " Neden bildirilmedi; elle sürdürün."}</span>
      )}
    </span>
  );
}
