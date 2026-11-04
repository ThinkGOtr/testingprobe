/**
 * Portalın kendi ikon seti (tasarım planı §4.16): bağımlılık yok, 24×24 çizgi SVG, `currentColor`.
 * Her ikon dekoratiftir: `aria-hidden`, `focusable="false"`, `<title>` yok — yanındaki metin ya da
 * düğmenin erişilebilir adı anlamı taşır (ikon eklemek hiçbir erişilebilir adı değiştirmez).
 * ✓ ✗ ⚠ ○ ◌ → ← glifleri ikon değildir; testler onları metin olarak arar, metin kalır.
 */

const CIZIM = {
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  ay: <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />,
  gunes: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4" />
    </>
  ),
  sistem: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 3.5v17A8.5 8.5 0 0 0 12 3.5Z" fill="currentColor" stroke="none" />
    </>
  ),
  dis: <path d="M14 4h6v6M20 4l-9 9M18 14v4.5A1.5 1.5 0 0 1 16.5 20h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10" />,
  gereksinim: (
    <>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" />
      <path d="M14 3v5h5M9 13h6M9 17h4" />
    </>
  ),
  kod: <path d="m9 7-5 5 5 5M15 7l5 5-5 5" />,
  kosu: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="m10 8.5 5 3.5-5 3.5Z" />
    </>
  ),
  bug: (
    <>
      <rect x="7" y="8" width="10" height="12" rx="5" />
      <path d="M9.5 8V6.5a2.5 2.5 0 0 1 5 0V8M12 12v8M3.5 13H7M17 13h3.5M4.5 8.5 7 10M19.5 8.5 17 10M4.5 18.5 7 17M19.5 18.5 17 17" />
    </>
  ),
  harita: <path d="M9 4 3.5 6v14L9 18l6 2 5.5-2V4L15 6 9 4ZM9 4v14M15 6v14" />,
  kule: (
    <>
      <path d="M4 20h16M7 20v-6M12 20V9M17 20V4" />
    </>
  ),
  demo: (
    <>
      <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="10" cy="17" r="2" />
    </>
  ),
  denetim: (
    <>
      <path d="M12 3 5 6v5.5c0 4.3 2.9 8 7 9.5 4.1-1.5 7-5.2 7-9.5V6Z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  terminal: (
    <>
      <rect x="3" y="4.5" width="18" height="15" rx="2" />
      <path d="m7 9.5 3 2.5-3 2.5M12.5 15h4.5" />
    </>
  ),
  // ---- AI asistan (asistan paneli, başlatıcı, üst çubuk "Öneri"; Öneri kartları da kullanabilir)
  /** Asistan kimliği (AI): dört köşeli parıltı + küçük eş. Metin glifi ✦ yerine. */
  asistan: (
    <>
      <path d="M11 3.5c.6 3.9 2.6 5.9 6.5 6.5-3.9.6-5.9 2.6-6.5 6.5-.6-3.9-2.6-5.9-6.5-6.5 3.9-.6 5.9-2.6 6.5-6.5Z" />
      <path d="M18.5 15.5c.3 1.6 1 2.3 2.5 2.5-1.5.2-2.2.9-2.5 2.5-.3-1.6-1-2.3-2.5-2.5 1.5-.2 2.2-.9 2.5-2.5Z" />
    </>
  ),
  kapat: <path d="M6 6l12 12M18 6 6 18" />,
  soru: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M9.6 9.6a2.5 2.5 0 0 1 4.8.9c0 1.7-2.4 2.2-2.4 3.6M12 16.9v.1" />
    </>
  ),
  arti: <path d="M12 5v14M5 12h14" />,
  gecmis: (
    <>
      <path d="M4 12a8 8 0 1 0 2.3-5.6L4 8.6" />
      <path d="M4 4v4.6h4.6M12 8v4.2l2.8 1.8" />
    </>
  ),
  geri: <path d="m14.5 6-6 6 6 6" />,
  gonder: <path d="M5 12h12.5M12.5 6.5 18 12l-5.5 5.5" />,
  begen: (
    <>
      <path d="M7.5 10.5v9H4.5v-9Z" />
      <path d="M7.5 10.5 11 4a2 2 0 0 1 2.6 2.4L12.8 9.5h5.4a2 2 0 0 1 2 2.4l-1.3 6a2 2 0 0 1-2 1.6H7.5" />
    </>
  ),
  begenme: (
    <>
      <path d="M7.5 13.5v-9H4.5v9Z" />
      <path d="M7.5 13.5 11 20a2 2 0 0 0 2.6-2.4l-.8-3.1h5.4a2 2 0 0 0 2-2.4l-1.3-6a2 2 0 0 0-2-1.6H7.5" />
    </>
  ),
  /** Öneri (üst çubuk düğmesi, öneri kartları): ampul. */
  oneri: (
    <>
      <path d="M9 18h6M10 21h4" />
      <path d="M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.3 1.1 2.2v.5h5v-.5c0-.9.4-1.6 1.1-2.2A6 6 0 0 0 12 3Z" />
    </>
  ),
} as const;

export type IkonAdi = keyof typeof CIZIM;

export function Ikon({ ad, className }: { ad: IkonAdi; className?: string }) {
  return (
    <svg
      className={className ? `ikon ${className}` : "ikon"}
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {CIZIM[ad]}
    </svg>
  );
}
