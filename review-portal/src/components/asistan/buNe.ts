// "? Bu ne?" (AI-ASISTAN-PLANI §5.5): kip açıkken saydam bindirme tıklamayı alır, alttaki öğe
// `document.elementsFromPoint` ile bulunur (disabled düğmeler dahil — tarayıcıların disabled
// öğeye işaretçi olayı göndermemesine bağımlı değil) ve kısa bir tanım çıkarılır.
//
// Yakalanmaz: form alanları, `contenteditable`, `pre`/`code` (kod ve token blokları),
// `aria-hidden="true"` ve `[data-asistan-gizli]` altındaki her şey. Metin çıkarılırken de bu
// alt ağaçlar atlanır: kartın boş yerine tıklamak içindeki token'ı bağlama taşımaz.

/** Bağlamdaki `secili_eleman` (§5.5). */
export interface SeciliEleman {
  ad: string;
  rol: string;
  devre_disi: boolean;
  ipucu: string | null;
  kart_basligi: string | null;
  test_id: string | null;
}

export const YAKALANMAZ =
  'input, textarea, select, [contenteditable]:not([contenteditable="false"]), pre, code, [aria-hidden="true"], [data-asistan-gizli]';

/** Tanımın bağlanacağı anlamlı öğe (tıklanan iç `span` yerine düğme/bağlantı/başlık). */
const ANLAMLI =
  'button, a[href], [role="button"], [role="link"], [role="tab"], [role="menuitem"], [role="checkbox"], [role="switch"], label, summary, h1, h2, h3, h4, h5, h6, th, td, li, .cip, .rozet, .menu-oge, .metrik';

const AD_AZAMI = 80;

export function yakalanabilirMi(el: Element): boolean {
  return !el.closest(YAKALANMAZ);
}

/** Gizli alt ağaçları atlayarak görünür metin (≤ sinir karakter). */
export function guvenliMetin(el: Element, sinir = AD_AZAMI): string {
  const parcalar: string[] = [];
  const gez = (n: Node) => {
    if (n.nodeType === Node.TEXT_NODE) {
      parcalar.push(n.textContent ?? "");
      return;
    }
    if (n.nodeType !== Node.ELEMENT_NODE) return;
    const e = n as Element;
    if (e !== el && e.matches(YAKALANMAZ)) return;
    if (e.matches(".gorunmez, script, style, svg")) return;
    e.childNodes.forEach(gez);
  };
  gez(el);
  const metin = parcalar.join(" ").replace(/\s+/g, " ").trim();
  return metin.length > sinir ? `${metin.slice(0, sinir - 1)}…` : metin;
}

const ORTUK_ROL: Record<string, string> = {
  BUTTON: "button",
  A: "link",
  H1: "heading",
  H2: "heading",
  H3: "heading",
  H4: "heading",
  H5: "heading",
  H6: "heading",
  LI: "listitem",
  TH: "columnheader",
  TD: "cell",
  LABEL: "label",
  SUMMARY: "button",
  SECTION: "region",
  NAV: "navigation",
  IMG: "img",
};

function erisilebilirAd(el: Element): string {
  const etiket = el.getAttribute("aria-label");
  if (etiket?.trim()) return etiket.trim().slice(0, AD_AZAMI);
  const ids = el.getAttribute("aria-labelledby");
  if (ids) {
    const metin = ids
      .split(/\s+/)
      .map((id) => el.ownerDocument.getElementById(id))
      .filter((x): x is HTMLElement => !!x && yakalanabilirMi(x))
      .map((x) => guvenliMetin(x))
      .join(" ")
      .trim();
    if (metin) return metin.slice(0, AD_AZAMI);
  }
  if (el.tagName === "IMG") return (el.getAttribute("alt") ?? "").slice(0, AD_AZAMI);
  return guvenliMetin(el);
}

/** Öğenin üzerindeki ya da en yakın atasındaki `title` (pasif düğmeyi saran ipucu dahil). */
function ipucu(el: Element): string | null {
  const t = el.closest("[title]")?.getAttribute("title");
  return t ? t.slice(0, 200) : null;
}

function kartBasligi(el: Element): string | null {
  const kart = el.closest(".kart, section, [role=region], [role=dialog]");
  if (!kart) return null;
  const b = kart.querySelector(".kart-baslik h2, h2, h3");
  if (!b || !yakalanabilirMi(b)) return null;
  const m = guvenliMetin(b);
  return m || null;
}

/** Tıklanan öğeden tanım; yakalanamazsa (gizli/alan/kod) null. */
export function elemanTanimi(hedef: Element): SeciliEleman | null {
  if (!yakalanabilirMi(hedef)) return null;
  const el = hedef.closest(ANLAMLI) ?? hedef;
  if (!yakalanabilirMi(el)) return null;
  const ad = erisilebilirAd(el);
  const devreDisi =
    (el as HTMLButtonElement).disabled === true || el.getAttribute("aria-disabled") === "true" || el.hasAttribute("data-yetkisiz");
  const testId = el.closest("[data-testid]")?.getAttribute("data-testid") ?? null;
  const tanim: SeciliEleman = {
    ad,
    rol: el.getAttribute("role") ?? ORTUK_ROL[el.tagName] ?? el.tagName.toLowerCase(),
    devre_disi: devreDisi,
    ipucu: ipucu(el),
    kart_basligi: kartBasligi(el),
    test_id: testId,
  };
  if (!tanim.ad && !tanim.ipucu && !tanim.kart_basligi && !tanim.test_id) return null;
  return tanim;
}

/**
 * Noktadaki ilk yakalanabilir öğe: bindirmenin kendisi ve `atla` (asistan paneli) atlanır.
 * Dönen `null`: orada tanımlanabilir öğe yok; `"gizli"`: öğe yakalama dışı.
 */
export function noktadakiOge(x: number, y: number, atla: (el: Element) => boolean, doc: Document = document): Element | "gizli" | null {
  const liste = typeof doc.elementsFromPoint === "function" ? doc.elementsFromPoint(x, y) : [];
  for (const el of liste) {
    if (atla(el)) continue;
    if (el === doc.documentElement || el === doc.body) return null;
    return yakalanabilirMi(el) ? el : "gizli";
  }
  return null;
}
