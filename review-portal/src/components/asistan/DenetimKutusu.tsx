// Asistan denetimi gösterimi (011 F7, K11). Soru asistan modeline gitmeden, cevap kullanıcıya
// gösterilmeden önce Agent Probe portu arkasında puanlanır; kararı core'daki kod verir. Kart
// kullanıcıya kısa ve anlaşılır bir özet gösterir ("Denetim 92/100"); kategoriler, gerekçe ve
// kaynak ayrıntı ipucundadır. Engellenen soru/cevapta ve denetim çalışmıyorken açıklama kutusu.
import type { CevapDenetimi, DenetimOzeti } from "../../api/asistan";
import { DENETIM_KAYNAGI, kategoriEtiketi } from "../../lib/ajanProbe";
import { Cip } from "../ui";

/** Gösterilecek kategoriler: "temiz" yalnız başınaysa anlamlıdır. */
function anlamliKategoriler(o: DenetimOzeti | null): string[] {
  const k = o?.kategoriler ?? [];
  return k.filter((x) => x !== "temiz");
}

function ipucu(yon: string, o: DenetimOzeti): string {
  const kat = anlamliKategoriler(o).map(kategoriEtiketi);
  return [
    `${yon}: ${o.puan}/100`,
    `Kategoriler: ${kat.length ? kat.join(", ") : "Temiz"}`,
    o.gerekce ? `Gerekçe: ${o.gerekce}` : null,
    `Kaynak: ${DENETIM_KAYNAGI[o.kaynak] ?? o.kaynak}`,
  ]
    .filter(Boolean)
    .join("\n");
}

/** Kart üstündeki kısa puan: iki yönün düşüğü (en riskli olan). */
export function denetimPuani(d: CevapDenetimi): { puan: number; ipucu: string } | null {
  const parcalar: [string, DenetimOzeti][] = [];
  if (d.soru) parcalar.push(["Soru", d.soru]);
  if (d.cevap) parcalar.push(["Cevap", d.cevap]);
  if (parcalar.length === 0) return null;
  return {
    puan: Math.min(...parcalar.map(([, o]) => o.puan)),
    ipucu: parcalar.map(([y, o]) => ipucu(y, o)).join("\n\n"),
  };
}

export function DenetimRozeti({ denetim }: { denetim: CevapDenetimi }) {
  const p = denetimPuani(denetim);
  if (!p) return null;
  const ton = denetim.karar === "engelle" ? "hata" : denetim.karar === "uyar" ? "uyari" : "notr";
  return (
    <span data-testid="denetim-rozeti">
      <Cip ton={ton} title={p.ipucu}>
        Denetim {p.puan}/100
      </Cip>
    </span>
  );
}

export function DenetimKutusu({ denetim }: { denetim: CevapDenetimi | null | undefined }) {
  if (!denetim) return null;
  if (denetim.karar === "calismiyor") {
    return (
      <div className="uyari-kutusu uyari-hata asistan-denetim" role="alert" data-testid="denetim-kutusu">
        <strong>Denetim çalışmıyor</strong>
        <div>Asistan denetimi şu an erişilemiyor; güvenlik gereği cevap verilmedi. Biraz sonra yeniden deneyin.</div>
      </div>
    );
  }
  if (denetim.karar === "engelle") {
    const o = denetim.engellenen === "cevap" ? denetim.cevap : denetim.soru;
    const kat = anlamliKategoriler(o).map(kategoriEtiketi);
    const baslik = denetim.engellenen === "cevap" ? "Cevap gösterilmedi" : "Soru engellendi";
    return (
      <div className="uyari-kutusu uyari-hata asistan-denetim" role="alert" data-testid="denetim-kutusu">
        <strong>{baslik}</strong>
        <div>
          {denetim.engellenen === "cevap"
            ? "Asistanın cevabı denetimden geçmedi ve size gösterilmedi."
            : "Soru denetimden geçmedi; asistana iletilmedi."}
          {kat.length > 0 && (
            <span className="satir-ogeler">
              {kat.map((k) => (
                <Cip key={k} ton="hata">
                  {k}
                </Cip>
              ))}
            </span>
          )}
        </div>
      </div>
    );
  }
  if (denetim.karar === "uyar") {
    const kat = [...new Set([...anlamliKategoriler(denetim.soru), ...anlamliKategoriler(denetim.cevap)])].map(kategoriEtiketi);
    return (
      <div className="uyari-kutusu uyari-uyari asistan-denetim" role="note" data-testid="denetim-kutusu">
        <strong>Denetim uyarısı</strong>
        <div>
          Bu içerik dikkatle değerlendirilmeli{kat.length ? `: ${kat.join(", ")}` : ""}.
        </div>
      </div>
    );
  }
  return null;
}
