import { useEffect, useRef } from "react";
import { adimAdi } from "../lib/akis";
import { AKIS_ADIMLARI } from "../lib/etiketler";

const TUR_ETIKETI = { sistem: "Sistem", ai: "AI adımı", insan: "İnsan kapısı", ai_insan: "AI + insan kapısı" } as const;

/**
 * 14 adımlı akış göstergesi (TEKNIK-TASARIM §2). `adim` = güncel adım (1–14).
 * `kompakt` (detay sayfası şeridi, DS-1): kartsız ince şerit; dar kapta satıra sarmak yerine yatay kayar
 * (kaydırılabilir bölge klavyeyle odaklanır), şimdiki adım görünür alana getirilir.
 */
export function AkisAdimlari({ adim, kaynak = "jira", kompakt }: { adim: number; kaynak?: "jira" | "free_text"; kompakt?: boolean }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const kap = ref.current;
    const el = kap?.querySelector<HTMLElement>('[aria-current="step"]');
    if (!kompakt || !kap || !el || kap.scrollWidth <= kap.clientWidth) return;
    kap.scrollLeft = Math.max(0, el.offsetLeft - kap.clientWidth / 2 + el.offsetWidth / 2);
  }, [adim, kompakt]);
  return (
    <nav ref={ref} aria-label="14 adımlı akıştaki ilerleme" className={kompakt ? "akis akis-kompakt" : "akis"} tabIndex={kompakt ? 0 : undefined}>
      <ol>
        {AKIS_ADIMLARI.map((a, i) => {
          const no = i + 1;
          const durum = no < adim ? "tamam" : no === adim ? "simdi" : "sonra";
          return (
            <li key={a.ad} className={`akis-adim akis-${durum} akis-tur-${a.tur}`} aria-current={durum === "simdi" ? "step" : undefined}>
              <span className="akis-no" aria-hidden="true">
                {durum === "tamam" ? "✓" : no}
              </span>
              <span className="akis-ad">{adimAdi(no, kaynak)}</span>
              <span className="gorunmez">
                {` — ${TUR_ETIKETI[a.tur]}, ${durum === "tamam" ? "tamamlandı" : durum === "simdi" ? "şu anki adım" : "bekliyor"}`}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="akis-lejant soluk" aria-hidden="true">
        <span className="lejant lejant-ai" /> AI adımı <span className="lejant lejant-insan" /> İnsan kapısı{" "}
        <span className="lejant lejant-ai-insan" /> AI + insan kapısı{" "}
        <span className="lejant lejant-sistem" /> Sistem
      </p>
    </nav>
  );
}
