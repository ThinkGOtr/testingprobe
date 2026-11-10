// Oturum düşünce form verisi korunur (specs/010-aiprobe-sso T040, yolculuk 14).
//
// AI Probe kipinde 401 tam sayfa yönlendirme demektir (AI Probe girişi → geri dönüş); React durumu
// kaybolur. Yönlendirmeden hemen önce ana içerikteki doldurulmuş alanlar `sessionStorage`'a yazılır,
// aynı adrese dönülünce alanlar çizildikçe geri konur (React'in denetimli alanları için yerel
// setter + `input`/`change` olayı). Parola, gizli ve dosya alanları hiç yazılmaz; yedek 15 dk geçerli
// ve tek kullanımlıktır; yalnız aynı kullanıcı (`app_user` kimliği) aynı adrese dönünce geri konur
// (başka kişiye/role form verisi taşınmaz). Asistan sohbet taslağının kendi kaydı vardır (asistan/oturumAnahtarlari).

const ANAHTAR = "tp-form-yedegi";
const GECERLILIK_MS = 15 * 60_000;
const BEKLEME_MS = 10_000;
const ATLANAN = new Set(["password", "hidden", "file", "submit", "button", "reset", "image"]);

type Alan = HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;

interface AlanYedegi {
  anahtar: string;
  deger: string;
  isaretli?: boolean;
}

interface Yedek {
  yol: string;
  sahip: string;
  zaman: number;
  alanlar: AlanYedegi[];
}

function alanlar(kok: ParentNode): Alan[] {
  return [...kok.querySelectorAll<Alan>("#ana-icerik input, #ana-icerik textarea, #ana-icerik select")];
}

/** Alanın kalıcı anahtarı: `#id`, yoksa `ad:<name>#<sıra>`; ikisi de yoksa null (yedeklenmez). */
function anahtarOf(el: Alan, tum: Alan[]): string | null {
  if (el.id) return `#${el.id}`;
  const ad = el.getAttribute("name");
  if (!ad) return null;
  const sira = tum.filter((x) => !x.id && x.getAttribute("name") === ad).indexOf(el);
  return `ad:${ad}#${sira}`;
}

function atlanir(el: Alan): boolean {
  if (el.disabled) return true;
  if (el instanceof HTMLInputElement) return ATLANAN.has(el.type) || el.readOnly || el.autocomplete === "current-password";
  return el instanceof HTMLTextAreaElement && el.readOnly;
}

export function formlariSakla(yol: string, sahip: string | null, kok: ParentNode = document): number {
  if (!sahip) return 0;
  const tum = alanlar(kok);
  const yedek: AlanYedegi[] = [];
  for (const el of tum) {
    if (atlanir(el)) continue;
    const anahtar = anahtarOf(el, tum);
    if (!anahtar) continue;
    // React denetimli alanlarda `defaultValue`/`defaultChecked`'i değerle eşitler; "değişti mi"
    // ayırt edilemez. Bu yüzden dolu metin alanları ve işaretli kutular yedeklenir.
    if (el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio")) {
      if (el.checked) yedek.push({ anahtar, deger: el.value, isaretli: true });
    } else if (el.value !== "") {
      yedek.push({ anahtar, deger: el.value });
    }
  }
  if (yedek.length === 0) return 0;
  try {
    sessionStorage.setItem(ANAHTAR, JSON.stringify({ yol, sahip, zaman: Date.now(), alanlar: yedek } satisfies Yedek));
  } catch {
    return 0;
  }
  return yedek.length;
}

function yedekOku(yol: string, sahip: string): Yedek | null {
  try {
    const ham = sessionStorage.getItem(ANAHTAR);
    if (!ham) return null;
    const y = JSON.parse(ham) as Yedek;
    if (!y || typeof y !== "object" || !Array.isArray(y.alanlar) || Date.now() - y.zaman > GECERLILIK_MS) {
      sessionStorage.removeItem(ANAHTAR);
      return null;
    }
    if (y.sahip !== sahip) {
      sessionStorage.removeItem(ANAHTAR);
      return null;
    }
    return y.yol === yol ? y : null;
  } catch {
    return null;
  }
}

function degerYaz(el: Alan, y: AlanYedegi): void {
  if (el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio")) {
    // React işaret kutularında `click` dinler; durum farklıysa tıklanır.
    if (y.isaretli !== undefined && el.checked !== y.isaretli) el.click();
    return;
  }
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value")?.set?.call(el, y.deger);
  el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
}

/**
 * Bu adres için yedek varsa alanları geri koyar; alanlar geç çizilebilir (veri yüklenince), bu
 * yüzden en çok 10 sn DOM izlenir. Her alan bir kez yazılır; hepsi yazılınca ya da süre dolunca yedek
 * silinir ve `bitti` geri konan alan sayısıyla çağrılır. Dönen işlev izlemeyi yalnızca durdurur
 * (yedek silinmez: StrictMode'un çift efekti ya da yeniden bağlanan ekran kaldığı yerden sürer).
 */
export function formlariGeriYukle(
  yol: string,
  sahip: string,
  bitti?: (sayi: number) => void,
  kok: ParentNode = document,
): () => void {
  const yedek = yedekOku(yol, sahip);
  if (!yedek) return () => {};
  const bekleyen = new Map(yedek.alanlar.map((a) => [a.anahtar, a]));
  let yazilan = 0;
  let durdu = false;
  const dene = () => {
    const tum = alanlar(kok);
    for (const el of tum) {
      const a = anahtarOf(el, tum);
      const y = a ? bekleyen.get(a) : undefined;
      if (!a || !y || atlanir(el)) continue;
      degerYaz(el, y);
      bekleyen.delete(a);
      yazilan += 1;
    }
    if (bekleyen.size === 0) durdur(true);
  };
  const gozlemci = typeof MutationObserver === "function" ? new MutationObserver(dene) : null;
  const zamanlayici = setTimeout(() => durdur(true), BEKLEME_MS);
  function durdur(sil: boolean) {
    if (durdu) return;
    durdu = true;
    gozlemci?.disconnect();
    clearTimeout(zamanlayici);
    if (!sil) return;
    try {
      sessionStorage.removeItem(ANAHTAR);
    } catch {
      /* yok say */
    }
    bitti?.(yazilan);
  }
  gozlemci?.observe(document.body, { childList: true, subtree: true });
  dene();
  return () => durdur(false);
}
