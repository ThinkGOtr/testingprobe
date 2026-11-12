// Asistan içerik kontrolü gösterimi (011 F7, K11; UX-9). Soru asistan modeline gitmeden, cevap
// kullanıcıya gösterilmeden önce Agent Probe portu arkasında puanlanır; kararı core'daki kod verir.
// Kullanıcıya puan gösterilmez: geçen cevapta işaret yok; uyarı/engelde kısa başlık + kategori,
// puan/gerekçe/kaynak <details> içindeki ayrıntıda (dokunmatik ve klavyeyle açılır). Engel ve uyarı
// açıklama metni backend'dedir (cevap bloğu / "Denetim uyarısı" notu); kutu aynı açıklamayı tekrar yazmaz.
import type { CevapDenetimi, DenetimOzeti } from "../../api/asistan";
import { DENETIM_KAYNAGI, kategoriEtiketi } from "../../lib/ajanProbe";
import { Cip } from "../ui";

/** Backend'in uyarı notu öneki (core assistant/denetim.py NOT_ONEKI). */
export const DENETIM_NOT_ONEKI = "Denetim uyarısı";

export function denetimNotuMu(n: string): boolean {
  return n.startsWith(DENETIM_NOT_ONEKI);
}

/** Gösterilecek kategoriler: "temiz" yalnız başınaysa anlamlıdır. */
function anlamliKategoriler(o: DenetimOzeti | null): string[] {
  const k = o?.kategoriler ?? [];
  return k.filter((x) => x !== "temiz");
}

const KARAR_METNI: Record<string, string> = { gec: "Geçti", uyar: "Uyarı", engelle: "Engel" };

/** İki yönün düşük puanı (en riskli olan); yalnız ayrıntı ve testler için. */
export function denetimPuani(d: CevapDenetimi): { puan: number } | null {
  const puanlar = [d.soru, d.cevap].filter((o): o is DenetimOzeti => !!o).map((o) => o.puan);
  return puanlar.length ? { puan: Math.min(...puanlar) } : null;
}

/** Kart üstü işaret: yalnız uyarıda (engelde kutu ve "İçerik kontrolü" kaynak notu zaten var; geçende işaret yok). */
export function DenetimRozeti({ denetim }: { denetim: CevapDenetimi }) {
  if (denetim.karar !== "uyar") return null;
  return (
    <span data-testid="denetim-rozeti">
      <Cip ton="uyari">İçerik kontrolü</Cip>
    </span>
  );
}

function Ayrinti({ denetim }: { denetim: CevapDenetimi }) {
  const yonler: [string, DenetimOzeti][] = [];
  if (denetim.soru) yonler.push(["Soru", denetim.soru]);
  if (denetim.cevap) yonler.push(["Cevap", denetim.cevap]);
  if (yonler.length === 0) return null;
  return (
    <details className="asistan-denetim-ayrinti" data-testid="denetim-ayrinti">
      <summary>Kontrol ayrıntısı</summary>
      <dl>
        {yonler.map(([yon, o]) => {
          const kat = anlamliKategoriler(o).map(kategoriEtiketi);
          return (
            <div key={yon}>
              <dt>{yon}</dt>
              <dd>
                {KARAR_METNI[o.karar] ?? o.karar} · puan {o.puan}/100 · {kat.length ? kat.join(", ") : "Temiz"}
                {o.gerekce && <div>Gerekçe: {o.gerekce}</div>}
                <div className="soluk">Kaynak: {DENETIM_KAYNAGI[o.kaynak] ?? o.kaynak}</div>
              </dd>
            </div>
          );
        })}
      </dl>
    </details>
  );
}

function Kategoriler({ etiketler }: { etiketler: string[] }) {
  if (etiketler.length === 0) return null;
  return (
    <span className="satir-ogeler" aria-label="Kategori">
      {etiketler.map((k) => (
        <Cip key={k} ton="uyari">
          {k}
        </Cip>
      ))}
    </span>
  );
}

/**
 * `notlar`: backend'in "Denetim uyarısı" notları. Verilirse uyarı kutusunun gövdesi bunlardır (CevapKarti
 * aynı notu ayrıca yazmaz); verilmezse kategori etiketleri gösterilir.
 */
export function DenetimKutusu({ denetim, notlar = [] }: { denetim: CevapDenetimi | null | undefined; notlar?: string[] }) {
  if (!denetim) return null;
  if (denetim.karar === "calismiyor") {
    return (
      <div className="uyari-kutusu uyari-hata asistan-denetim" role="alert" data-testid="denetim-kutusu">
        <strong>İçerik kontrolü çalışmıyor</strong>
        <div>İçerik kontrolü şu an erişilemiyor; güvenlik gereği cevap verilmedi. Biraz sonra yeniden deneyin.</div>
      </div>
    );
  }
  if (denetim.karar === "engelle") {
    const o = denetim.engellenen === "cevap" ? denetim.cevap : denetim.soru;
    // Açıklama cevap bloğunda (backend); kutu yalnız başlık, kategori ve ayrıntı taşır.
    return (
      <div className="uyari-kutusu uyari-uyari asistan-denetim" role="note" data-testid="denetim-kutusu">
        <strong>Bu soruyu yanıtlayamıyorum</strong>
        <Kategoriler etiketler={anlamliKategoriler(o).map(kategoriEtiketi)} />
        <Ayrinti denetim={denetim} />
      </div>
    );
  }
  if (denetim.karar === "uyar") {
    const kat = [...new Set([...anlamliKategoriler(denetim.soru), ...anlamliKategoriler(denetim.cevap)])].map(kategoriEtiketi);
    const govde = notlar.map((n) => n.replace(new RegExp(`^${DENETIM_NOT_ONEKI}:?\\s*`), "")).filter(Boolean);
    return (
      <div className="uyari-kutusu uyari-uyari asistan-denetim" role="note" data-testid="denetim-kutusu">
        <strong>İçerik kontrolü uyarısı</strong>
        {govde.length > 0 ? (
          govde.map((n, i) => <div key={i}>{n}</div>)
        ) : (
          <>
            <div>Bu cevabı dikkatle değerlendirin.</div>
            <Kategoriler etiketler={kat} />
          </>
        )}
        <Ayrinti denetim={denetim} />
      </div>
    );
  }
  return null;
}
