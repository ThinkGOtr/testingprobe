import { useState, type ReactNode } from "react";
import { yuzde } from "../lib/format";

interface Nokta {
  etiket: string;
  oran: number;
  ek?: string;
}

/**
 * Tek seri sütun grafiği (0–1 oranlar): ince sütunlar, tabana oturan yuvarlak uçlar, hedef çizgisi,
 * üzerine gelince/odaklanınca ipucu ve ekran okuyucu için tablo.
 */
export function OranSutunlari({ noktalar, baslik, hedef }: { noktalar: Nokta[]; baslik: string; hedef?: number }) {
  const [aktif, setAktif] = useState<number | null>(null);
  const G = 320;
  const Y = 120;
  const ust = 8;
  const alt = 22;
  const yukseklik = Y - ust - alt;
  const adim = noktalar.length ? G / noktalar.length : G;
  const genislik = Math.min(28, adim * 0.55);
  const y = (o: number) => ust + yukseklik * (1 - Math.max(0, Math.min(1, o)));

  return (
    <figure className="grafik">
      <svg viewBox={`0 0 ${G} ${Y}`} role="img" aria-label={`${baslik}. Ayrıntılar aşağıdaki tabloda.`} className="grafik-svg">
        {[0, 0.5, 1].map((o) => (
          <g key={o}>
            <line x1={0} x2={G} y1={y(o)} y2={y(o)} className="grafik-izgara" />
          </g>
        ))}
        {hedef !== undefined && <line x1={0} x2={G} y1={y(hedef)} y2={y(hedef)} className="grafik-hedef" />}
        {noktalar.map((n, i) => {
          const x = i * adim + (adim - genislik) / 2;
          const h = Math.max(2, yukseklik * Math.max(0, Math.min(1, n.oran)));
          const r = Math.min(4, genislik / 2);
          const ty = ust + yukseklik - h;
          // Üstte yuvarlak, tabanda düz sütun.
          const yol = `M${x},${ust + yukseklik} L${x},${ty + r} Q${x},${ty} ${x + r},${ty} L${x + genislik - r},${ty} Q${x + genislik},${ty} ${x + genislik},${ty + r} L${x + genislik},${ust + yukseklik} Z`;
          return (
            <g
              key={n.etiket}
              tabIndex={0}
              onMouseEnter={() => setAktif(i)}
              onMouseLeave={() => setAktif(null)}
              onFocus={() => setAktif(i)}
              onBlur={() => setAktif(null)}
              className="grafik-hedef-alan"
            >
              <rect x={i * adim} y={0} width={adim} height={Y} fill="transparent" />
              <path d={yol} className={`grafik-sutun${aktif === i ? " aktif" : ""}`} />
              <text x={x + genislik / 2} y={Y - 6} textAnchor="middle" className="grafik-eksen">
                {n.etiket}
              </text>
            </g>
          );
        })}
      </svg>
      {aktif !== null && noktalar[aktif] && (
        <div className="grafik-ipucu" role="status" style={{ left: `${((aktif + 0.5) / noktalar.length) * 100}%` }}>
          <strong>{noktalar[aktif].etiket}</strong> {yuzde(noktalar[aktif].oran)}
          {noktalar[aktif].ek && <span className="soluk"> · {noktalar[aktif].ek}</span>}
        </div>
      )}
      <table className="gorunmez">
        <caption>{baslik}</caption>
        <thead>
          <tr>
            <th>Gün</th>
            <th>Oran</th>
          </tr>
        </thead>
        <tbody>
          {noktalar.map((n) => (
            <tr key={n.etiket}>
              <td>{n.etiket}</td>
              <td>
                {yuzde(n.oran)} {n.ek}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

/** Hedefe göre ölçer: değer çubuğu + hedef işareti + metin (renk tek başına anlam taşımaz). */
/** `deger` null: henüz ölçülecek bir şey yok (ör. hiç karar verilmedi) — "hedefin altında" denmez. */
export function HedefOlcer({
  etiket,
  deger,
  hedef,
  bosMetin = "henüz ölçüm yok",
  ek,
}: {
  etiket: string;
  deger: number | null;
  hedef: number;
  bosMetin?: string;
  /** Etiketin yanında (ör. KPI kaynağı ipucu). */
  ek?: ReactNode;
}) {
  if (deger === null) {
    return (
      <div className="olcer">
        <div className="olcer-ust">
          <span>
            {etiket} {ek}
          </span>
          <strong>—</strong>
        </div>
        <div className="ilerleme" aria-hidden="true">
          <div className="ilerleme-hedef" style={{ left: `${hedef * 100}%` }} />
        </div>
        <div className="olcer-alt soluk">
          Hedef ≥ {yuzde(hedef)} · {bosMetin}
        </div>
      </div>
    );
  }
  const tuttu = deger >= hedef;
  return (
    <div className="olcer">
      <div className="olcer-ust">
        <span>
            {etiket} {ek}
          </span>
        <strong>{yuzde(deger)}</strong>
      </div>
      <div className="ilerleme" role="meter" aria-label={etiket} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(deger * 100)}>
        <div className={`ilerleme-dolgu ${tuttu ? "" : "ilerleme-dusuk"}`} style={{ width: `${Math.min(1, deger) * 100}%` }} />
        <div className="ilerleme-hedef" style={{ left: `${hedef * 100}%` }} />
      </div>
      <div className="olcer-alt soluk">
        Hedef ≥ {yuzde(hedef)} · {tuttu ? "✓ hedef tuttu" : "✗ hedefin altında"}
      </div>
    </div>
  );
}
