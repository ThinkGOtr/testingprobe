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
  degistir({ acik: true, sekme, istek: { sekme, sira, ...secenek } });
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

/** Testler için. */
export function asistanKontrolSifirla(): void {
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
