import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { yuzde } from "../lib/format";

interface Nokta {
  etiket: string;
  oran: number;
  ek?: string;
}

/**
 * Tek seri sütun grafiği (0–1 oranlar): ince sütunlar, tabana oturan yuvarlak uçlar, hedef çizgisi,
 * üzerine gelince/odaklanınca ipucu ve tablo alternatifi ("Tablo olarak göster").
 *
 * ET-08: grafik tek Tab durağıdır (gezinen tabindex): yalnız seçili sütun tabIndex=0, ←/→/Home/End sütun
 * değiştirir, değer `role=status` ipucuyla okunur. Böylece 10 sütunlu grafik 10 durak değil 1 duraktır.
 */
export function OranSutunlari({ noktalar, baslik, hedef }: { noktalar: Nokta[]; baslik: string; hedef?: number }) {
  const [aktif, setAktif] = useState<number | null>(null);
  // Gezinen tabindex: son odaklanan sütun (yoksa sonuncusu: en güncel gün) tek durak.
  const [durak, setDurak] = useState(Math.max(0, noktalar.length - 1));
  const sutunlar = useRef<(SVGGElement | null)[]>([]);
  const tus = (e: KeyboardEvent<SVGGElement>, i: number) => {
    const n = noktalar.length;
    const h = e.key === "ArrowRight" ? Math.min(n - 1, i + 1) : e.key === "ArrowLeft" ? Math.max(0, i - 1) : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : -1;
    if (h < 0) return;
    e.preventDefault();
    setDurak(h);
    sutunlar.current[h]?.focus();
  };
  const secili = Math.min(durak, Math.max(0, noktalar.length - 1));
  // viewBox genişliği çizilen genişliğe eşitlenir (1:1): eksen yazısı ve sütun genişliği (en çok 28 px)
  // ekranda da CSS piksel olarak kalır, grafik kartı doldurur (§4.13). Ölçülemezse (jsdom) 320.
  const kap = useRef<HTMLElement>(null);
  const [G, setG] = useState(320);
  useEffect(() => {
    const el = kap.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const olc = () => {
      const w = Math.round(el.clientWidth);
      if (w > 0) setG(w);
    };
    olc();
    const ro = new ResizeObserver(olc);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const Y = 160;
  // Üst boşluk değer etiketine yer açar (okunurluk: değer sütunun üstünde, ipucuya gerek kalmadan).
  const ust = 22;
  const alt = 22;
  const yukseklik = Y - ust - alt;
  const adim = noktalar.length ? G / noktalar.length : G;
  const genislik = Math.min(28, adim * 0.55);
  const y = (o: number) => ust + yukseklik * (1 - Math.max(0, Math.min(1, o)));

  return (
    <figure className="grafik" ref={kap}>
      {/* Sütunlar klavyeyle odaklanır (ipucu): svg role="img" olsaydı alt öğeleri sunumsal olur, odak durağının
          adı/rolü kalmazdı (4.1.2). Kap "group", her sütun kendi adıyla "img". */}
      <svg viewBox={`0 0 ${G} ${Y}`} width={G} height={Y} role="group" aria-label={`${baslik}. Sütunlar arasında ← → ile gezinin; ayrıntılar aşağıdaki tabloda.`} className="grafik-svg">
        {[0, 0.5, 1].map((o) => (
          <g key={o} aria-hidden="true">
            <line x1={0} x2={G} y1={y(o)} y2={y(o)} className="grafik-izgara" />
            {o > 0 && (
              <text x={G - 2} y={y(o) - 3} textAnchor="end" className="grafik-eksen grafik-eksen-y">
                {yuzde(o)}
              </text>
            )}
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
              ref={(el) => {
                sutunlar.current[i] = el;
              }}
              tabIndex={i === secili ? 0 : -1}
              onKeyDown={(e) => tus(e, i)}
              role="img"
              aria-label={`${n.etiket}: ${yuzde(n.oran)}${n.ek ? ` · ${n.ek}` : ""}`}
              onMouseEnter={() => setAktif(i)}
              onMouseLeave={() => setAktif(null)}
              onFocus={() => {
                setAktif(i);
                setDurak(i);
              }}
              onBlur={() => setAktif(null)}
              className="grafik-hedef-alan"
            >
              {/* Hedef alan = odak halkası: 1 px içeride (svg kenarında kırpılmasın). */}
              <rect x={i * adim + 1} y={1} width={Math.max(0, adim - 2)} height={Y - 2} rx={6} fill="transparent" className="grafik-odak" />
              <path d={yol} className={`grafik-sutun${aktif === i ? " aktif" : ""}`} />
              {noktalar.length <= 14 && (
                <text x={x + genislik / 2} y={ty - 4} textAnchor="middle" className="grafik-deger" aria-hidden="true">
                  {yuzde(n.oran)}
                </text>
              )}
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
      {/* Tablo alternatifi: ekran okuyucu ve klavye kullanıcısı tüm değerleri tek yerde okur. */}
      <details className="grafik-tablo">
        <summary className="kucuk">Tablo olarak göster</summary>
        <table className="tablo tablo-sik">
          <caption className="gorunmez">{baslik}</caption>
          <thead>
            <tr>
              <th scope="col">Gün</th>
              <th scope="col" className="sutun-sayi">
                Oran
              </th>
              <th scope="col">Ayrıntı</th>
            </tr>
          </thead>
          <tbody>
            {noktalar.map((n) => (
              <tr key={n.etiket}>
                <td className="sutun-tarih">{n.etiket}</td>
                <td className="sutun-sayi">{yuzde(n.oran)}</td>
                <td>{n.ek ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
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
