import { useMemo } from "react";
import { kelimeFarki } from "../lib/diff";

/** Kelime düzeyinde fark: silinenler üstü çizili, eklenenler vurgulu. */
export function FarkGorunumu({ eski, yeni }: { eski: string; yeni: string }) {
  const parcalar = useMemo(() => kelimeFarki(eski, yeni), [eski, yeni]);
  const degisiklikYok = parcalar.every((p) => p.tur === "ayni");
  return (
    <div className="fark" aria-label="Önerilen değişiklik farkı">
      {degisiklikYok ? (
        <span className="soluk">Metinde değişiklik yok.</span>
      ) : (
        parcalar.map((p, i) =>
          p.tur === "ayni" ? (
            <span key={i}>{p.metin}</span>
          ) : p.tur === "silindi" ? (
            <del key={i}>
              <span className="gorunmez">[silindi: </span>
              {p.metin}
              <span className="gorunmez">]</span>
            </del>
          ) : (
            <ins key={i}>
              <span className="gorunmez">[eklendi: </span>
              {p.metin}
              <span className="gorunmez">]</span>
            </ins>
          ),
        )
      )}
    </div>
  );
}
