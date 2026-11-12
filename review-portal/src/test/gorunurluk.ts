// jsdom'da IntersectionObserver yok: testler görünürlüğü bu sahteyle elle sürer (K13 "görüldü" sayacı).
import { act } from "@testing-library/react";
import { vi } from "vitest";

type Geri = (kayitlar: IntersectionObserverEntry[], g: IntersectionObserver) => void;

class SahteGozlemci {
  static canli = new Set<SahteGozlemci>();
  readonly hedefler = new Set<Element>();
  constructor(
    readonly geri: Geri,
    readonly secenek?: IntersectionObserverInit,
  ) {
    SahteGozlemci.canli.add(this);
  }
  observe(el: Element) {
    this.hedefler.add(el);
  }
  unobserve(el: Element) {
    this.hedefler.delete(el);
  }
  disconnect() {
    this.hedefler.clear();
    SahteGozlemci.canli.delete(this);
  }
  takeRecords() {
    return [];
  }
}

export interface GorunurlukSecenegi {
  /** Kartın görünen yüksekliği (px). Varsayılan: kartın tamamı. */
  gorunen?: number;
  /** Kart yüksekliği (px). */
  kart?: number;
  /** Viewport yüksekliği (px). */
  ekran?: number;
}

/** Sahte gözlemciyi kurar; `vi.unstubAllGlobals()` ile kaldırılır. */
export function gozlemciKur() {
  SahteGozlemci.canli.clear();
  vi.stubGlobal("IntersectionObserver", SahteGozlemci);
  const bildir = (el: Element, s: GorunurlukSecenegi | null) => {
    const kart = s?.kart ?? 400;
    const ekran = s?.ekran ?? 800;
    const gorunen = s ? (s.gorunen ?? kart) : 0;
    const kayit = {
      target: el,
      isIntersecting: gorunen > 0,
      intersectionRatio: kart ? gorunen / kart : 0,
      intersectionRect: { height: gorunen } as DOMRectReadOnly,
      boundingClientRect: { height: kart } as DOMRectReadOnly,
      rootBounds: { height: ekran } as DOMRectReadOnly,
      time: 0,
    } as unknown as IntersectionObserverEntry;
    act(() => {
      for (const g of [...SahteGozlemci.canli]) if (g.hedefler.has(el)) g.geri([kayit], g as unknown as IntersectionObserver);
    });
  };
  return {
    /** Elemanı (ya da kapsayan case kartını) görünür yapar. */
    goster: (el: Element, s: GorunurlukSecenegi = {}) => bildir(el.closest("article") ?? el, s),
    gizle: (el: Element) => bildir(el.closest("article") ?? el, null),
    /** Şu an gözlenen tüm elemanlar. */
    gozlenenler: () => [...SahteGozlemci.canli].flatMap((g) => [...g.hedefler]),
  };
}
