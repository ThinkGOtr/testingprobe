// Kanıt dosyasını (ör. Appium hata anı sayfa kaynağı XML'i) metin olarak okur.
//
// Güvenlik: yalnızca core'un artefakt ucu (`/api/artifacts/…`, aynı köken, oturum çerezi) okunur;
// başka adres ağa hiç çıkmaz. `data:` adresi (örnek veri) yerelde çözülür. İçerik güvenilmeyen
// veridir: çağıran yalnızca düz metin olarak (React kaçışıyla) gösterir, HTML/XML olarak yorumlamaz.
// Boyut sınırlıdır: en çok `sinir` bayt okunur, fazlası kesilir.

export const SAYFA_KAYNAGI_SINIRI = 256 * 1024;

export interface ArtefaktMetni {
  metin: string;
  /** Sınıra ulaşıldı: metin dosyanın başıdır. */
  kesildi: boolean;
  /** Okunan bayt (kesildiyse sınır). */
  bayt: number;
}

const ARTEFAKT_YOLU = /^\/api\/artifacts\/[^?#]*$/;

/** Okunabilir kanıt adresi mi: core artefakt ucu ya da `data:` (örnek veri). */
export function okunabilirArtefakt(url: string | null | undefined): boolean {
  if (!url) return false;
  return url.startsWith("data:") || (ARTEFAKT_YOLU.test(url) && !url.includes(".."));
}

function kes(baytlar: Uint8Array, sinir: number): ArtefaktMetni {
  const kesildi = baytlar.length > sinir;
  const parca = kesildi ? baytlar.subarray(0, sinir) : baytlar;
  // Yarım kalan çok baytlı karakter "�" olur (fatal değil); metin yalnız gösterim içindir.
  return { metin: new TextDecoder("utf-8").decode(parca), kesildi, bayt: parca.length };
}

function dataCoz(url: string, sinir: number): ArtefaktMetni {
  const virgul = url.indexOf(",");
  if (virgul < 0) throw new Error("Kanıt adresi çözülemedi.");
  const ust = url.slice(5, virgul);
  const govde = url.slice(virgul + 1);
  if (/;base64$/i.test(ust)) {
    const ikili = atob(govde);
    const b = new Uint8Array(ikili.length);
    for (let i = 0; i < ikili.length; i++) b[i] = ikili.charCodeAt(i);
    return kes(b, sinir);
  }
  return kes(new TextEncoder().encode(decodeURIComponent(govde)), sinir);
}

export async function artefaktMetniOku(
  url: string,
  { sinir = SAYFA_KAYNAGI_SINIRI, signal }: { sinir?: number; signal?: AbortSignal } = {},
): Promise<ArtefaktMetni> {
  if (!okunabilirArtefakt(url)) throw new Error("Bu kanıt portaldan okunamaz (core artefakt ucu değil).");
  if (url.startsWith("data:")) return dataCoz(url, sinir);
  let res: Response;
  try {
    res = await fetch(url, { credentials: "same-origin", signal, headers: { Accept: "application/xml, text/plain, */*" } });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new Error("Kanıt dosyasına ulaşılamadı (ağ hatası).");
  }
  if (!res.ok) {
    throw new Error(res.status === 404 ? "Kanıt dosyası bulunamadı (saklama süresi dolmuş olabilir)." : `Kanıt dosyası okunamadı (HTTP ${res.status}).`);
  }
  // Akış okunur, sınırda durulur: büyük dosya belleğe tümüyle alınmaz.
  const okuyucu = res.body?.getReader();
  if (!okuyucu) return kes(new Uint8Array(await res.arrayBuffer()), sinir);
  const parcalar: Uint8Array[] = [];
  let toplam = 0;
  while (toplam <= sinir) {
    const { done, value } = await okuyucu.read();
    if (done) break;
    parcalar.push(value);
    toplam += value.length;
  }
  if (toplam > sinir) void okuyucu.cancel().catch(() => undefined);
  const hepsi = new Uint8Array(toplam);
  let i = 0;
  for (const p of parcalar) {
    hepsi.set(p, i);
    i += p.length;
  }
  return kes(hepsi, sinir);
}
