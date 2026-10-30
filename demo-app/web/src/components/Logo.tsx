/** Jenerik içecek dağıtıcısı logosu (marka yok). */
export function Logo() {
  return (
    <svg className="logo" viewBox="0 0 32 32" width="32" height="32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="currentColor" />
      <path
        d="M13 6h6v4.2c0 .9.4 1.7 1 2.3l.6.6c.9.9 1.4 2.1 1.4 3.4V24a2 2 0 0 1-2 2h-8a2 2 0 0 1-2-2v-7.5c0-1.3.5-2.5 1.4-3.4l.6-.6c.6-.6 1-1.4 1-2.3Z"
        fill="#fff"
      />
      <path d="M10.5 18h11v4h-11z" fill="var(--accent)" />
    </svg>
  );
}
