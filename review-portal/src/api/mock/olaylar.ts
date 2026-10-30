// Mock modunda SSE yerine geçen süreç içi olay yolu.
import type { PortalOlayi } from "../types";

type Dinleyici = (o: PortalOlayi) => void;
const dinleyiciler = new Set<Dinleyici>();

export function mockOlayYayinla(o: PortalOlayi): void {
  dinleyiciler.forEach((fn) => fn(o));
}

export function mockOlaylaraAbone(fn: Dinleyici): () => void {
  dinleyiciler.add(fn);
  return () => {
    dinleyiciler.delete(fn);
  };
}
