// Bağımlılıksız küçük istemci yönlendiricisi (History API).
import { useEffect, useState } from "react";

const EVENT = "app:navigate";

export function navigate(path: string, replace = false): void {
  if (path === window.location.pathname) return;
  if (replace) window.history.replaceState(null, "", path);
  else window.history.pushState(null, "", path);
  window.dispatchEvent(new Event(EVENT));
  window.scrollTo(0, 0);
}

export function usePath(): string {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const update = () => setPath(window.location.pathname);
    window.addEventListener("popstate", update);
    window.addEventListener(EVENT, update);
    return () => {
      window.removeEventListener("popstate", update);
      window.removeEventListener(EVENT, update);
    };
  }, []);
  return path;
}

export const routes = {
  login: "/giris",
  catalog: "/katalog",
  cart: "/sepet",
  orders: "/siparisler",
  order: (numara: string) => `/siparis/${encodeURIComponent(numara)}`,
};
