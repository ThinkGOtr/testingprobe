// `{veri:anahtar}` atıflarının case metninde çip olarak gösterimi (013 §3.5). Değer case
// serileştirmesindeki `veri` alanından gelir; gizli kayıt değeri hiç gösterilmez.
import type { CaseVeriAtfi } from "../api/types";
import { atifParcalari } from "../api/uyumOtomasyon";

export const GIZLI_DEGER = "••• (gizli)";

export function VeriCipi({ anahtar, kayit }: { anahtar: string; kayit: CaseVeriAtfi | undefined }) {
  // `veri` alanı ya da içinde bu anahtar yoksa değer bilinmiyor: nötr çip, kırmızı değil.
  const durum = kayit === undefined ? "bilinmiyor" : !kayit.var ? "yok" : kayit.gizli ? "gizli" : "deger";
  const deger = durum === "gizli" ? GIZLI_DEGER : durum === "deger" ? (kayit?.deger ?? "") : durum === "yok" ? "katalogda yok" : null;
  const ipucu =
    durum === "yok"
      ? `Bilinmeyen test verisi anahtarı: ${anahtar} (katalogda yok ya da silinmiş)`
      : durum === "gizli"
        ? `Gizli test verisi: ${anahtar}; değer ortam sırrından okunur, gösterilmez`
        : durum === "bilinmiyor"
          ? `Test verisi atfı: ${anahtar}`
          : `Test verisi: ${anahtar}${kayit?.surum ? ` (sürüm ${kayit.surum})` : ""}`;
  return (
    <span className={`veri-atif veri-atif-${durum}`} title={ipucu} data-anahtar={anahtar} data-durum={durum}>
      <span className="gorunmez">{durum === "yok" ? "Bilinmeyen test verisi " : "Test verisi "}</span>
      <span className="veri-atif-anahtar mono">{anahtar}</span>
      {deger !== null && (
        <>
          <span className="gorunmez">: </span>
          <span className="veri-atif-deger">{deger}</span>
        </>
      )}
    </span>
  );
}

/** Metni düz parça + atıf çipi olarak çizer; atıf yoksa metni aynen döner. */
export function AtifliMetin({ metin, veri }: { metin: string | null | undefined; veri?: Record<string, CaseVeriAtfi> }) {
  const parcalar = atifParcalari(metin);
  if (!parcalar.some((p) => p.tur === "atif")) return <>{metin ?? ""}</>;
  return (
    <>
      {parcalar.map((p, i) =>
        p.tur === "metin" ? (
          <span key={i}>{p.metin}</span>
        ) : (
          // Kırmızı "katalogda yok" yalnız core anahtarı `var: false` döndürdüyse; `veri` gelmediyse
          // ya da anahtar içinde yoksa (ör. eski core'da başlık atfı) değer bilinmiyor: nötr çip.
          <VeriCipi key={i} anahtar={p.anahtar} kayit={veri?.[p.anahtar]} />
        ),
      )}
    </>
  );
}
