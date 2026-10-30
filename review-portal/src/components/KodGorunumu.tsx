import { useMemo } from "react";
import { belirtecle, dilBul, satirlaraBol } from "../lib/vurgula";

/**
 * Satır numaralı, renklendirilmiş salt okunur kod görünümü. Dil `dil` ya da dosya adından
 * (`dosya` / `kaynakYolu`) çıkarılır; `kaynakYolu` başlık göstermeden yalnızca dili belirler.
 */
export function KodGorunumu({
  kod,
  dosya,
  kaynakYolu,
  baslangicSatiri = 1,
  vurguSatiri,
}: {
  kod: string;
  dosya?: string;
  kaynakYolu?: string;
  baslangicSatiri?: number;
  vurguSatiri?: number;
}) {
  const dil = dilBul(kaynakYolu ?? dosya);
  const satirlar = useMemo(() => satirlaraBol(belirtecle(kod.replace(/\n$/, ""), dil)), [kod, dil]);
  return (
    <figure className="kod">
      {dosya && <figcaption className="kod-dosya">{dosya}</figcaption>}
      <pre tabIndex={0} aria-label={dosya ? `${dosya} içeriği` : "Kod"}>
        <code>
          {satirlar.map((satir, i) => {
            const no = baslangicSatiri + i;
            return (
              <span key={i} className={`kod-satir${no === vurguSatiri ? " kod-vurgu" : ""}`}>
                <span className="kod-no" aria-hidden="true">
                  {no}
                </span>
                {satir.map((b, j) => (
                  <span key={j} className={b.tur === "duz" ? undefined : `tk-${b.tur}`}>
                    {b.metin}
                  </span>
                ))}
                {"\n"}
              </span>
            );
          })}
        </code>
      </pre>
    </figure>
  );
}
