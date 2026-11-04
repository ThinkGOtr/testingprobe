// "Son hata" deposu (AI-ASISTAN-PLANI §5.5): asistanın "Az önceki hata ne demek?" sorusuna
// bağlam olarak taşınan, kullanıcının gerçekten karşılaştığı son API hatası.
//
// - `istek()` GET dışı hataları doğrudan yazar (`hataKaydet`).
// - GET hataları yalnızca ekranda gösterildiğinde yazılır: `istek()` onları aday olarak tutar
//   (`hataAdayi`), `HataKutusu` gösterince `hataGosterildi` ile kayda döner.
// - `/assistant/*` uçları, `/auth/*` (giriş parolası hatası bağlam değildir) ve 501 "bu fazda yok"
//   hiç yazılmaz. Kayıt 5 dk geçerlidir.
//
// Bu modül `api/http`'yi içe aktarmaz (döngü olmasın): hata nesnesini alan adlarıyla okur.
// Kayıtlar kullanıcıya aittir: çıkışta / kullanıcı değişince silinir (`oturumTemizligi`).
import { oturumDegisinceTemizle } from "./oturumTemizligi";

/** Asistan bağlamına giden kayıt (§5.5 `son_hata`; `yas_s` gönderirken hesaplanır). */
export interface SonHataKaydi {
  kayitId: string;
  /** "POST /cases/:id/review" biçiminde uç; kimliksiz (yalnız metin) kayıtta null. */
  uc: string | null;
  status: number | null;
  kod: string | null;
  detail: string;
  /** Ekranda kullanıcıya gösterilen metin (HataKutusu, çakışma mesajı). */
  gorunen_metin: string | null;
  /** Kaydın oluştuğu an (ms). */
  zaman: number;
}

/** Hata nesnesinin bu modülün okuduğu alanları (`ApiError` ile uyumlu). */
export interface HataBenzeri {
  kayitId: string;
  status: number;
  detail: string;
  kod?: string;
  method?: string;
  yol?: string;
}

export const SON_HATA_GECERLILIK_MS = 5 * 60 * 1000;
const AZAMI_KAYIT = 20;

let kayitlar: SonHataKaydi[] = [];
let adaylar: SonHataKaydi[] = [];
let sonYazilan: string | null = null;
const dinleyiciler = new Set<() => void>();
let surum = 0;

function bildir(): void {
  surum += 1;
  dinleyiciler.forEach((fn) => fn());
}

export function hataBenzeriMi(e: unknown): e is HataBenzeri {
  return (
    !!e &&
    typeof e === "object" &&
    typeof (e as { kayitId?: unknown }).kayitId === "string" &&
    typeof (e as { status?: unknown }).status === "number" &&
    typeof (e as { detail?: unknown }).detail === "string"
  );
}

/** Bu hata hiç kayda girmez: asistanın kendi uçları, giriş uçları ve 501 "bu fazda yok". */
export function kayitDisi(e: HataBenzeri): boolean {
  if (e.status === 501) return true;
  const yol = e.yol ?? "";
  return yol.startsWith("/assistant/") || yol === "/assistant" || yol.startsWith("/auth/");
}

function kayitUret(e: HataBenzeri, simdi: number): SonHataKaydi {
  return {
    kayitId: e.kayitId,
    uc: e.method && e.yol ? `${e.method.toUpperCase()} ${e.yol}` : null,
    status: e.status,
    kod: e.kod ?? null,
    detail: e.detail,
    gorunen_metin: null,
    zaman: simdi,
  };
}

function ekle(liste: SonHataKaydi[], k: SonHataKaydi): SonHataKaydi[] {
  return [k, ...liste.filter((x) => x.kayitId !== k.kayitId)].slice(0, AZAMI_KAYIT);
}

/** GET dışı bir isteğin hatası: hemen kayda yazılır. */
export function hataKaydet(e: HataBenzeri, simdi = Date.now()): void {
  if (kayitDisi(e)) return;
  const mevcut = kayitlar.find((k) => k.kayitId === e.kayitId);
  kayitlar = ekle(kayitlar, mevcut ? { ...mevcut, zaman: simdi } : kayitUret(e, simdi));
  sonYazilan = e.kayitId;
  bildir();
}

/** GET hatası: ekranda gösterilene kadar aday olarak bekler (gösterilmeyen hata bağlam değildir). */
export function hataAdayi(e: HataBenzeri, simdi = Date.now()): void {
  if (kayitDisi(e)) return;
  adaylar = ekle(adaylar, kayitUret(e, simdi));
}

let yerelSayac = 0;

/**
 * Hata ekranda gösterildi (HataKutusu `useEffect`, çakışma mesajı). `kaynak` bir `ApiError` ise
 * o kayıt (adaysa kayda alınarak) güncellenir; kimliksiz hatada aynı metinli aday/kayıt aranır,
 * bulunamazsa yalnız metinden yeni kayıt açılır. Dönen değer kaydın kimliğidir; kayıt dışı
 * hatalarda null.
 */
export function hataGosterildi(kaynak: unknown, gorunenMetin: string | null, simdi = Date.now()): string | null {
  let kayit: SonHataKaydi | undefined;
  if (hataBenzeriMi(kaynak)) {
    if (kayitDisi(kaynak)) return null;
    kayit =
      kayitlar.find((k) => k.kayitId === kaynak.kayitId) ??
      adaylar.find((k) => k.kayitId === kaynak.kayitId) ??
      kayitUret(kaynak, simdi);
  } else if (gorunenMetin) {
    kayit =
      kayitlar.find((k) => k.detail === gorunenMetin || k.gorunen_metin === gorunenMetin) ??
      adaylar.find((k) => k.detail === gorunenMetin);
    if (!kayit) {
      yerelSayac += 1;
      kayit = { kayitId: `yerel-${yerelSayac}-${simdi.toString(36)}`, uc: null, status: null, kod: null, detail: gorunenMetin, gorunen_metin: null, zaman: simdi };
    }
  } else {
    return null;
  }
  const yeni: SonHataKaydi = { ...kayit, gorunen_metin: gorunenMetin ?? kayit.gorunen_metin, zaman: kayit.zaman || simdi };
  // Değişmeyen kaydı yeniden yazmak gereksiz render üretir (HataKutusu her çizimde çağırabilir).
  const onceki = kayitlar.find((k) => k.kayitId === yeni.kayitId);
  adaylar = adaylar.filter((k) => k.kayitId !== yeni.kayitId);
  if (onceki && onceki.gorunen_metin === yeni.gorunen_metin && sonYazilan === yeni.kayitId) return yeni.kayitId;
  kayitlar = ekle(kayitlar, onceki ? { ...onceki, gorunen_metin: yeni.gorunen_metin } : yeni);
  sonYazilan = yeni.kayitId;
  bildir();
  return yeni.kayitId;
}

/** Kayıtlı bir hatanın gösterilen metnini ekler (ör. `cakismaMesaji`). */
export function gorunenMetinEkle(kayitId: string, metin: string): void {
  const k = kayitlar.find((x) => x.kayitId === kayitId) ?? adaylar.find((x) => x.kayitId === kayitId);
  if (!k || k.gorunen_metin === metin) return;
  const yeni = { ...k, gorunen_metin: metin };
  if (kayitlar.some((x) => x.kayitId === kayitId)) kayitlar = kayitlar.map((x) => (x.kayitId === kayitId ? yeni : x));
  else adaylar = adaylar.map((x) => (x.kayitId === kayitId ? yeni : x));
  bildir();
}

/**
 * "Asistana sor" tıklandı: hata hâlâ ekranda, kaydın 5 dk'lık süresi tıklama anından yeniden
 * başlar ve en son kayıt olur. Kayıt yoksa (20 kayıt sınırıyla düştüyse) false.
 */
export function hataTazele(kayitId: string, simdi = Date.now()): boolean {
  const k = kayitlar.find((x) => x.kayitId === kayitId);
  if (!k) return false;
  kayitlar = ekle(kayitlar, { ...k, zaman: simdi });
  sonYazilan = kayitId;
  bildir();
  return true;
}

function gecerli(k: SonHataKaydi, simdi: number): boolean {
  return simdi - k.zaman <= SON_HATA_GECERLILIK_MS;
}

/** En son yazılan, 5 dakikadan yeni kayıt. */
export function sonHata(simdi = Date.now()): SonHataKaydi | null {
  const k = sonYazilan ? kayitlar.find((x) => x.kayitId === sonYazilan) : kayitlar[0];
  return k && gecerli(k, simdi) ? k : null;
}

/** Belirli bir kayıt ("Asistana sor"); süresi geçmişse null. */
export function hataKaydi(kayitId: string, simdi = Date.now()): SonHataKaydi | null {
  const k = kayitlar.find((x) => x.kayitId === kayitId);
  return k && gecerli(k, simdi) ? k : null;
}

/** Asistan bağlamındaki `son_hata` nesnesi (§5.5). */
export function sonHataBaglami(k: SonHataKaydi, simdi = Date.now()) {
  return {
    uc: k.uc,
    status: k.status,
    kod: k.kod,
    detail: k.detail.slice(0, 300),
    gorunen_metin: k.gorunen_metin ? k.gorunen_metin.slice(0, 300) : null,
    yas_s: Math.max(0, Math.round((simdi - k.zaman) / 1000)),
  };
}

export function sonHataAbone(fn: () => void): () => void {
  dinleyiciler.add(fn);
  return () => {
    dinleyiciler.delete(fn);
  };
}

/** `useSyncExternalStore` anlık değeri: kayıt değiştikçe artar. */
export function sonHataSurumu(): number {
  return surum;
}

/** Çıkışta / kullanıcı değişince (önceki kullanıcının hatası sonrakinin bağlamına gitmesin) ve testlerde. */
export function sonHatayiSifirla(): void {
  kayitlar = [];
  adaylar = [];
  sonYazilan = null;
  bildir();
}

oturumDegisinceTemizle(sonHatayiSifirla);
