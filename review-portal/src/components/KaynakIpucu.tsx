// KPI kaynak ipucu: Kontrol Kulesi kartları ve asistan ölçüm kartı (OnerilerOlcumKarti) ortak kullanır.
// Kule sayfasından taşındı (asistan bileşeni sayfayı içe aktarıp döngü kurmasın); davranış ve DOM aynı.
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";

/**
 * KPI'nın kaynağı (core `kaynaklar`): ekran okuyucuda etiket (role=img + aria-label); görenler için fareyle,
 * klavye odağıyla ya da dokunarak açılan ipucu (WCAG 1.4.13: üstüne gelinebilir, Escape ile kapanır).
 * İpucu metni CSS `attr(aria-label)` ile çizilir (DOM'a yeni metin girmez); `position: fixed` olduğu için
 * şeridin `overflow: hidden` kırpmasına takılmaz, ekran kenarına sıkıştırılır.
 */
export function KaynakIpucu({ kaynak, testId = "kaynak-ipucu" }: { kaynak: string | undefined; testId?: string }) {
  const metin = kaynak ? `Kaynak: ${kaynak}` : "Kaynak: core bu ölçünün kaynağını bildirmedi";
  const ref = useRef<HTMLSpanElement>(null);
  const [acik, setAcik] = useState(false);
  const [konum, setKonum] = useState<{ x: number; y: number } | null>(null);
  const yerlestir = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const kenar = 16;
    const en = Math.min(280, window.innerWidth - 2 * kenar);
    const x = Math.max(kenar, Math.min(r.left + r.width / 2 - en / 2, window.innerWidth - kenar - en));
    // Boşluksuz (24 px hedefin alt kenarı): imleç ipucuna geçerken ipucu kapanmaz (1.4.13 üstüne gelinebilir).
    setKonum({ x: Math.round(x), y: Math.round(r.bottom - 1) });
  }, []);
  const ac = () => {
    yerlestir();
    setAcik(true);
  };
  useEffect(() => {
    if (!acik) return;
    window.addEventListener("scroll", yerlestir, true);
    window.addEventListener("resize", yerlestir);
    return () => {
      window.removeEventListener("scroll", yerlestir, true);
      window.removeEventListener("resize", yerlestir);
    };
  }, [acik, yerlestir]);
  return (
    <span
      ref={ref}
      className="kaynak-ipucu"
      tabIndex={0}
      role="img"
      aria-label={metin}
      data-testid={testId}
      data-acik={acik ? "" : undefined}
      style={acik && konum ? ({ "--ipucu-x": `${konum.x}px`, "--ipucu-y": `${konum.y}px` } as CSSProperties) : undefined}
      onMouseEnter={ac}
      onMouseLeave={() => setAcik(false)}
      onFocus={ac}
      onBlur={() => setAcik(false)}
      onKeyDown={(e) => {
        if (e.key === "Escape" && acik) {
          e.stopPropagation();
          setAcik(false);
        }
      }}
    >
      i
    </span>
  );
}
