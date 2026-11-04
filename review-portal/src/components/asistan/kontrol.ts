// Asistan panelinin dışarıdan kontrolü: "Asistana sor" (HataKutusu), Öneri düğmesi ve
// "Neden? Sor" paneli belirli sekme ve bağlamla açar. Panel tek örnektir (App.tsx); durum
// modül düzeyinde tutulur, bileşenler `useSyncExternalStore` ile okur.
import { useSyncExternalStore } from "react";
import { oturumDegisinceTemizle } from "../../lib/oturumTemizligi";

export type AsistanSekmesi = "sohbet" | "oneriler";

export interface AcmaSecenegi {
  /** Öneriler sekmesinde vurgulanacak / sohbete taşınacak öneri kuralı. */
  oneriKuralId?: string;
  /** "Asistana sor": bu son hata kaydının bağlamıyla aç. */
  kayitId?: string;
  /** Sohbet sekmesinde yeni sohbette hemen gönderilecek soru (ör. "Neden? Sor"). */
  soru?: string;
  /** Soru bu sohbette sorulur (AI öneri kartının "Bunu sor"u: ek öneri sohbeti). */
  sohbetId?: string;
}

export interface AcmaIstegi extends AcmaSecenegi {
  sekme: AsistanSekmesi;
  /** Aynı isteğin iki kez işlenmemesi için artan sıra. */
  sira: number;
  /** İsteğin yazıldığı an (ms); bayat istek gönderilmez (`istekGecerli`). */
  zaman: number;
}

/** Dış isteğin geçerlilik süresi: Sohbet bu süre içinde çizilmezse istek gönderilmeden düşer. */
export const ISTEK_GECERLILIK_MS = 30_000;

export function istekGecerli(istek: Pick<AcmaIstegi, "zaman">, simdi = Date.now()): boolean {
  return simdi - istek.zaman <= ISTEK_GECERLILIK_MS;
}

interface Durum {
  acik: boolean;
  sekme: AsistanSekmesi;
  istek: AcmaIstegi | null;
  /** Panel çizildi ve asistan kullanılabilir ("Asistana sor" yalnız o zaman görünür). */
  hazir: boolean;
}

const OTURUM_ANAHTARI = "tp-asistan-panel";

function ilkDurum(): Durum {
  let acik = false;
  let sekme: AsistanSekmesi = "sohbet";
  try {
    const ham = sessionStorage.getItem(OTURUM_ANAHTARI);
    if (ham) {
      const p = JSON.parse(ham) as Partial<Durum>;
      acik = p.acik === true;
      if (p.sekme === "oneriler") sekme = "oneriler";
    }
  } catch {
    /* depolama yok */
  }
  return { acik, sekme, istek: null, hazir: false };
}

let durum: Durum = ilkDurum();
let sira = 0;
const dinleyiciler = new Set<() => void>();

function degistir(d: Partial<Durum>): void {
  durum = { ...durum, ...d };
  try {
    sessionStorage.setItem(OTURUM_ANAHTARI, JSON.stringify({ acik: durum.acik, sekme: durum.sekme }));
  } catch {
    /* yoksay */
  }
  dinleyiciler.forEach((fn) => fn());
}

function abone(fn: () => void): () => void {
  dinleyiciler.add(fn);
  return () => {
    dinleyiciler.delete(fn);
  };
}

/** Paneli belirtilen sekmede açar (Öneri düğmesi: `acSekme("oneriler")`). */
export function acSekme(sekme: AsistanSekmesi, secenek: AcmaSecenegi = {}): void {
  sira += 1;
  degistir({ acik: true, sekme, istek: { sekme, sira, zaman: Date.now(), ...secenek } });
}

/** "Asistana sor": paneli sohbet sekmesinde o hata kaydının bağlamıyla açar. */
export function asistanaSor(kayitId: string): void {
  acSekme("sohbet", { kayitId });
}

export function sekmeSec(sekme: AsistanSekmesi): void {
  degistir({ sekme });
}

export function paneliAc(): void {
  degistir({ acik: true });
}

export function paneliKapat(): void {
  degistir({ acik: false });
}

/** Panel işlediği isteği temizler. */
export function istegiTuket(isSira: number): void {
  if (durum.istek?.sira === isSira) degistir({ istek: null });
}

export function panelHazirAyarla(hazir: boolean): void {
  if (durum.hazir !== hazir) degistir({ hazir });
}

export function useAsistanKontrol(): Durum {
  return useSyncExternalStore(abone, () => durum);
}

/** Asistan kullanılabilir mi ("Asistana sor" düğmesi için). */
export function useAsistanHazir(): boolean {
  return useSyncExternalStore(abone, () => durum.hazir);
}

/**
 * "Neden? Sor" ile açılan öneri sohbetleri: (kural, varlık) → sohbet. Kartın hazır soru çipleri
 * aynı kural için ikinci kez yeni sohbet açmaz, takip sorusu olarak o sohbete gider (§17.6:
 * öneri bağlamı sohbetin takip sorularında sunucuda taşınır).
 */
const oneriSohbetleri = new Map<string, string>();
const oneriSohbetAnahtari = (kuralId: string, varlikId: string | null | undefined) => `${kuralId}|${varlikId ?? ""}`;

export function oneriSohbetiYaz(kuralId: string, varlikId: string | null | undefined, sohbetId: string): void {
  oneriSohbetleri.set(oneriSohbetAnahtari(kuralId, varlikId), sohbetId);
}

export function oneriSohbeti(kuralId: string, varlikId: string | null | undefined): string | null {
  return oneriSohbetleri.get(oneriSohbetAnahtari(kuralId, varlikId)) ?? null;
}

/** Sohbet silinince (ya da sunucuda bulunamayınca) eşleme düşer. */
export function oneriSohbetiUnut(sohbetId: string): void {
  for (const [k, v] of oneriSohbetleri) if (v === sohbetId) oneriSohbetleri.delete(k);
}

/**
 * Sohbet sekmesinin taslağı: girdi, bağlam çipi tercihleri, bekletilen soru, iptal notları ve
 * bekleme başlangıçları. Yalnız seçili sekme çizilir ve dar ekranda "Bu ne?" kipi paneli DOM'dan
 * kaldırır; bu değerler bileşen state'inde tutulsaydı sekme geçişinde / öğe seçiminde sıfırlanır,
 * kaldırılan çipler geri gelir ve yazılan soru silinirdi. Oturum değişince temizlenir.
 */
export interface SohbetTaslagi {
  girdi: string;
  /** Ekran çipinin kaldırıldığı ekranın anahtarı (rota kalıbı + varlık); başka ekranda çip yine eklenir. */
  ekranKaldirilan: string | null;
  /** Hata çipinin kaldırıldığı kaydın kimliği; yeni hata kaydında çip yine eklenir. */
  hataKaldirilan: string | null;
  secilenHataId: string | null;
  hataNotu: string | null;
  bekletilen: { metin: string; secenek: { yeniSohbet?: boolean; oneriKuralId?: string | null; sohbetId?: string | null } } | null;
  /** Mesaj kimliği → "Beklemeyi bırak" sonrası ücret notu. */
  notlar: Record<string, string>;
  /** Mesaj kimliği → son adım kodu (SSE `assistant.step`). */
  adimlar: Record<string, string>;
}

function bosTaslak(): SohbetTaslagi {
  return { girdi: "", ekranKaldirilan: null, hataKaldirilan: null, secilenHataId: null, hataNotu: null, bekletilen: null, notlar: {}, adimlar: {} };
}

/** Tek panel örneği okur/yazar (SohbetSekmesi); değişiklik bileşenin kendi state'iyle de çizilir. */
export const sohbetTaslagi: SohbetTaslagi = bosTaslak();

/** Bekleme başlangıcı: mesajın bu sekmede ilk görüldüğü an (istemci saati); sekme geçişinde korunur. */
export const ilkGorulmeler = new Map<string, number>();

function taslagiSifirla(): void {
  Object.assign(sohbetTaslagi, bosTaslak());
  ilkGorulmeler.clear();
}

/** Testler için. */
export function asistanKontrolSifirla(): void {
  oneriSohbetleri.clear();
  taslagiSifirla();
  try {
    sessionStorage.removeItem(OTURUM_ANAHTARI);
  } catch {
    /* yoksay */
  }
  durum = { acik: false, sekme: "sohbet", istek: null, hazir: false };
  dinleyiciler.forEach((fn) => fn());
}

// Çıkışta / kullanıcı değişince: panel kapanır, bekleyen dış istek düşer. `hazir` panelin
// çizimine bağlıdır (panel kendisi yazar); burada korunur.
oturumDegisinceTemizle(() => {
  const hazir = durum.hazir;
  asistanKontrolSifirla();
  if (hazir) panelHazirAyarla(true);
});
