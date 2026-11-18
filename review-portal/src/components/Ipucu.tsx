// Erişilebilir ipucu (ET-06): yalnız `title` ile verilen açıklamaların yerine. Fareyle, klavye odağıyla ya da
// dokunarak açılır; Escape kapatır (WCAG 1.4.13). Açıklama kapalıyken de ekran okuyucuya `aria-description`
// ile verilir; balon yalnız açıkken DOM'dadır (kapalıyken sayfa metnine ve `getByText` sorgularına karışmaz).
// Balon `position: fixed`: tablo/kart `overflow` kırpmasına takılmaz, ekran kenarına sıkıştırılır.
import { useCallback, useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from "react";

export function Ipucu({
  metin,
  children,
  className,
  testId,
}: {
  /** Açıklama metni (düz metin; kısa tutulur). Boşsa yalnız `children` çizilir. */
  metin: string | null | undefined;
  children: ReactNode;
  className?: string;
  testId?: string;
}) {
  const id = useId();
  const ref = useRef<HTMLSpanElement>(null);
  const [acik, setAcik] = useState(false);
  const [konum, setKonum] = useState<{ x: number; y: number } | null>(null);
  const yerlestir = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const kenar = 16;
    const en = Math.min(320, window.innerWidth - 2 * kenar);
    const x = Math.max(kenar, Math.min(r.left, window.innerWidth - kenar - en));
    setKonum({ x: Math.round(x), y: Math.round(r.bottom + 4) });
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
  if (!metin?.trim()) return <>{children}</>;
  return (
    <span
      ref={ref}
      className={`ipucu${className ? ` ${className}` : ""}`}
      tabIndex={0}
      aria-description={acik ? undefined : metin}
      aria-describedby={acik ? id : undefined}
      data-testid={testId}
      data-acik={acik ? "" : undefined}
      onMouseEnter={ac}
      onMouseLeave={() => setAcik(false)}
      onFocus={ac}
      onBlur={() => setAcik(false)}
      onClick={ac}
      onKeyDown={(e) => {
        if (e.key === "Escape" && acik) {
          e.stopPropagation();
          setAcik(false);
        }
      }}
    >
      {children}
      {acik && konum && (
        <span
          id={id}
          role="tooltip"
          className="ipucu-balon"
          style={{ "--ipucu-x": `${konum.x}px`, "--ipucu-y": `${konum.y}px` } as CSSProperties}
        >
          {metin}
        </span>
      )}
    </span>
  );
}
