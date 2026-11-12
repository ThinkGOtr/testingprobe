// Üretim seçenekleri (011 §4.4, K5): "Üretimi başlat" formunun saf durum yardımcıları ve
// `GET /requirements/{id}/generation-options` yanıt uyarlaması. Form (UretimFormu) ve örnek veri
// (mock generate-cases doğrulaması) aynı kuralları buradan kullanır; sınırlar core ile aynıdır
// (aşılırsa core 422 döner — form göndermeden önce aynı metni gösterir).
import type { DerinlestirmeTeknigi, EkBilgiAlani, EkBilgiTuru, UretimGovdesi, UretimSecenekleri, UretimSecenekleriYaniti } from "../api/types";
import type { UretimKipi } from "../api/tasarimModeliTipleri";
import { gereksinimDurumu } from "./etiketler";

export const URETIM_PLATFORMLARI = ["Web", "Mobil-iOS", "Mobil-Android", "Desktop-Win", "Desktop-macOS", "Desktop-Linux", "API", "Data"] as const;
export const URETIM_TEST_SEVIYELERI = ["UNIT", "COMPONENT", "INTEGRATION", "SYSTEM", "E2E", "UAT"] as const;

/** core sınırları (aşılırsa 422). */
export const SECENEK_SINIRI = {
  standartSayisi: 10,
  standartUzunluk: 40,
  kapsamDisi: 2000,
  roller: 1000,
  metin: 500,
  uzunMetin: 8000,
} as const;

const MOBIL = ["Mobil-iOS", "Mobil-Android"];
const DESKTOP = ["Desktop-Win", "Desktop-macOS", "Desktop-Linux"];

/**
 * Ek bilgi alanları kataloğu (core `ek_bilgi_alanlari` ile aynı). Yanıt kendi kataloğunu taşır;
 * bu kopya yalnız örnek veri ve yanıtta katalog yokken (eski core) kullanılır.
 */
export const EK_BILGI_ALANLARI: Record<string, EkBilgiAlani> = {
  otomasyon_araci: { etiket: "Otomasyon aracı", tur: "metin", platformlar: [...URETIM_PLATFORMLARI] },
  tarayicilar: { etiket: "Tarayıcılar", tur: "metin", platformlar: ["Web"] },
  cozunurlukler: { etiket: "Çözünürlükler", tur: "metin", platformlar: ["Web"] },
  os_matrisi: { etiket: "İşletim sistemi / sürüm matrisi", tur: "metin", platformlar: [...MOBIL, ...DESKTOP] },
  cihazlar: { etiket: "Cihaz sınıfları", tur: "metin", platformlar: MOBIL },
  uygulama_tipi: { etiket: "Uygulama tipi", tur: "secim", secenekler: ["native", "hybrid", "flutter", "react-native", "mobil-web"], platformlar: MOBIL },
  teknoloji: { etiket: "Teknoloji", tur: "metin", platformlar: DESKTOP },
  mimari: { etiket: "Mimari", tur: "secim", secenekler: ["x64", "ARM64"], platformlar: DESKTOP },
  dagitim: { etiket: "Dağıtım (MSI, DMG…)", tur: "metin", platformlar: DESKTOP },
  yol_limiti: { etiket: "Yol uzunluğu sınırı", tur: "metin", platformlar: DESKTOP },
  soak_suresi: { etiket: "Uzun süre açık kalma süresi", tur: "metin", platformlar: DESKTOP },
  api_sozlesmesi_var: { etiket: "API sözleşmesi var", tur: "evet_hayir", platformlar: ["API"] },
  api_sozlesmesi: { etiket: "API sözleşmesi (OpenAPI/endpoint tanımı)", tur: "uzun_metin", platformlar: ["API"] },
  auth_tipi: { etiket: "Kimlik doğrulama tipi", tur: "metin", platformlar: ["API"] },
  sistemler: { etiket: "Sistemler", tur: "metin", platformlar: ["Data"] },
  mesaj_semasi: { etiket: "Mesaj şeması", tur: "uzun_metin", platformlar: ["Data"] },
  donusum_kurallari: { etiket: "Dönüşüm kuralları", tur: "uzun_metin", platformlar: ["Data"] },
  teslim_garantisi: { etiket: "Teslim garantisi", tur: "secim", secenekler: ["at-most-once", "at-least-once", "exactly-once"], platformlar: ["Data"] },
};

/**
 * Yalnız başka bir alan "evet" iken anlamlı olan alanlar (alan → koşul alanı). Koşul alanı
 * kayıtlı değilse (eski kayıt: sözleşme metni var, bayrak yok) metin yine görünür.
 */
const KOSULLU_ALANLAR: Record<string, string> = { api_sozlesmesi: "api_sozlesmesi_var" };

export function varsayilanSecenekler(): UretimSecenekleri {
  return { platformlar: [], test_seviyesi: "SYSTEM", benimsenen_standartlar: [], kapsam_disi: "", roller: "", ek_bilgi: {} };
}

const nesneMi = (x: unknown): x is Record<string, unknown> => !!x && typeof x === "object" && !Array.isArray(x);
const metinler = (x: unknown): string[] => (Array.isArray(x) ? x.filter((v): v is string => typeof v === "string") : []);
const EK_TURLER: EkBilgiTuru[] = ["metin", "secim", "evet_hayir", "uzun_metin"];

/** Ham seçenekleri (yanıt ya da kayıt) tam nesneye tamamlar; eksik/yanlış tipli alan varsayılana düşer. */
export function seceneklerUyarla(ham: unknown, taban: UretimSecenekleri = varsayilanSecenekler()): UretimSecenekleri {
  if (!nesneMi(ham)) return { ...taban, ek_bilgi: { ...taban.ek_bilgi } };
  const ek: Record<string, string | boolean> = {};
  if (nesneMi(ham.ek_bilgi)) {
    for (const [k, v] of Object.entries(ham.ek_bilgi)) if (typeof v === "string" || typeof v === "boolean") ek[k] = v;
  }
  return {
    platformlar: Array.isArray(ham.platformlar) ? [...new Set(metinler(ham.platformlar))] : [...taban.platformlar],
    test_seviyesi: typeof ham.test_seviyesi === "string" && ham.test_seviyesi ? ham.test_seviyesi : taban.test_seviyesi,
    benimsenen_standartlar: Array.isArray(ham.benimsenen_standartlar) ? metinler(ham.benimsenen_standartlar) : [...taban.benimsenen_standartlar],
    kapsam_disi: typeof ham.kapsam_disi === "string" ? ham.kapsam_disi : taban.kapsam_disi,
    roller: typeof ham.roller === "string" ? ham.roller : taban.roller,
    ek_bilgi: nesneMi(ham.ek_bilgi) ? ek : { ...taban.ek_bilgi },
  };
}

function alanUyarla(ham: unknown): EkBilgiAlani | null {
  if (!nesneMi(ham) || typeof ham.etiket !== "string") return null;
  const tur = EK_TURLER.includes(ham.tur as EkBilgiTuru) ? (ham.tur as EkBilgiTuru) : "metin";
  return {
    etiket: ham.etiket,
    tur,
    ...(Array.isArray(ham.secenekler) ? { secenekler: metinler(ham.secenekler) } : {}),
    platformlar: metinler(ham.platformlar),
  };
}

/** `GET generation-options` yanıtı; eksik katalog alanları yerel kopyayla tamamlanır. */
export function uretimSecenekleriYanitiUyarla(ham: unknown): UretimSecenekleriYaniti {
  const h = nesneMi(ham) ? ham : {};
  const varsayilan = seceneklerUyarla(h.varsayilan);
  const alanlar: Record<string, EkBilgiAlani> = {};
  if (nesneMi(h.ek_bilgi_alanlari)) {
    for (const [ad, a] of Object.entries(h.ek_bilgi_alanlari)) {
      const u = alanUyarla(a);
      if (u) alanlar[ad] = u;
    }
  }
  const platformlar = metinler(h.platformlar);
  const seviyeler = metinler(h.test_seviyeleri);
  // D1: kayıtlı üretim kipi `kayitli.kip` ya da `secenekler.kip` olarak gelebilir (yoksa alan yok).
  const kip = kipUyarla(nesneMi(h.kayitli) ? h.kayitli.kip : undefined) ?? kipUyarla(nesneMi(h.secenekler) ? h.secenekler.kip : undefined);
  return {
    ...(kip ? { kip } : {}),
    secenekler: nesneMi(h.secenekler) ? seceneklerUyarla(h.secenekler, varsayilan) : null,
    varsayilan,
    platformlar: platformlar.length ? platformlar : [...URETIM_PLATFORMLARI],
    test_seviyeleri: seviyeler.length ? seviyeler : [...URETIM_TEST_SEVIYELERI],
    ek_bilgi_alanlari: nesneMi(h.ek_bilgi_alanlari) ? alanlar : { ...EK_BILGI_ALANLARI },
  };
}

/** Formun ilk değeri: gereksinimde kayıtlı son seçenekler, yoksa varsayılan (K5). */
export function baslangicSecenekleri(y: UretimSecenekleriYaniti): UretimSecenekleri {
  return seceneklerUyarla(y.secenekler ?? y.varsayilan, y.varsayilan);
}

/** Alan seçili platformlardan birine ait mi ve (koşullu alansa) koşulu sağlanıyor mu. */
export function alanGorunur(ad: string, alan: EkBilgiAlani, s: Pick<UretimSecenekleri, "platformlar" | "ek_bilgi">): boolean {
  if (!alan.platformlar.some((p) => s.platformlar.includes(p))) return false;
  const kosul = KOSULLU_ALANLAR[ad];
  if (kosul && s.ek_bilgi[kosul] === false) return false;
  if (kosul && s.ek_bilgi[kosul] === undefined && !s.ek_bilgi[ad]) return false;
  return true;
}

/** Seçili platformlara göre görünen ek bilgi alanları (katalog sırasıyla). */
export function gorunurAlanlar(alanlar: Record<string, EkBilgiAlani>, s: Pick<UretimSecenekleri, "platformlar" | "ek_bilgi">): [string, EkBilgiAlani][] {
  return Object.entries(alanlar).filter(([ad, a]) => alanGorunur(ad, a, s));
}

/** Platform seçimini değiştirir (sıra katalogdaki sıra olur). */
export function platformDegistir(s: UretimSecenekleri, platform: string, secili: boolean, sira: readonly string[] = URETIM_PLATFORMLARI): UretimSecenekleri {
  const kume = new Set(s.platformlar);
  if (secili) kume.add(platform);
  else kume.delete(platform);
  const bilinen = sira.filter((p) => kume.has(p));
  return { ...s, platformlar: [...bilinen, ...[...kume].filter((p) => !sira.includes(p))] };
}

/**
 * Etiket girişinden standart ekler: virgülle ayrılmış birden çok kod, kırpılır, tekrarlar atılır.
 * Sınır aşımında liste değişmez ve hata metni döner.
 */
export function standartEkle(liste: string[], girdi: string): { liste: string[]; hata: string | null } {
  const adaylar = girdi
    .split(",")
    .map((x) => x.trim().replace(/\s+/g, " "))
    .filter(Boolean);
  if (adaylar.length === 0) return { liste, hata: null };
  const uzun = adaylar.find((x) => x.length > SECENEK_SINIRI.standartUzunluk);
  if (uzun) return { liste, hata: `Standart kodu en fazla ${SECENEK_SINIRI.standartUzunluk} karakter olabilir: "${uzun.slice(0, 50)}"` };
  const yeni = [...liste];
  for (const a of adaylar) if (!yeni.some((x) => x.toLocaleLowerCase("tr") === a.toLocaleLowerCase("tr"))) yeni.push(a);
  if (yeni.length > SECENEK_SINIRI.standartSayisi) return { liste, hata: `En fazla ${SECENEK_SINIRI.standartSayisi} standart eklenebilir.` };
  return { liste: yeni, hata: null };
}

export function standartSil(liste: string[], kod: string): string[] {
  return liste.filter((x) => x !== kod);
}

const ekSiniri = (tur: EkBilgiTuru) => (tur === "uzun_metin" ? SECENEK_SINIRI.uzunMetin : SECENEK_SINIRI.metin);

/**
 * core doğrulamasının (422) karşılığı: sınır ve değer hataları (boşsa gönderilebilir). Bilinmeyen
 * platform/seviye/alan da hata sayılır. `alanlar`: yanıttaki katalog.
 */
export function secenekHatalari(
  s: UretimGovdesi,
  alanlar: Record<string, EkBilgiAlani> = EK_BILGI_ALANLARI,
  platformlar: readonly string[] = URETIM_PLATFORMLARI,
  seviyeler: readonly string[] = URETIM_TEST_SEVIYELERI,
): string[] {
  const h: string[] = [];
  for (const p of s.platformlar ?? []) if (!platformlar.includes(p)) h.push(`Bilinmeyen platform: ${p}`);
  if (s.test_seviyesi !== undefined && !seviyeler.includes(s.test_seviyesi)) h.push(`Bilinmeyen test seviyesi: ${s.test_seviyesi}`);
  const std = s.benimsenen_standartlar ?? [];
  if (std.length > SECENEK_SINIRI.standartSayisi) h.push(`En fazla ${SECENEK_SINIRI.standartSayisi} standart eklenebilir.`);
  for (const k of std) {
    if (k.trim().length < 1 || k.length > SECENEK_SINIRI.standartUzunluk) h.push(`Standart kodu 1–${SECENEK_SINIRI.standartUzunluk} karakter olmalı: "${k.slice(0, 50)}"`);
  }
  if ((s.kapsam_disi ?? "").length > SECENEK_SINIRI.kapsamDisi) h.push(`Kapsam dışı en fazla ${SECENEK_SINIRI.kapsamDisi} karakter olabilir.`);
  if ((s.roller ?? "").length > SECENEK_SINIRI.roller) h.push(`Roller en fazla ${SECENEK_SINIRI.roller} karakter olabilir.`);
  for (const [ad, v] of Object.entries(s.ek_bilgi ?? {})) {
    const a = alanlar[ad];
    if (!a) {
      h.push(`Bilinmeyen ek bilgi alanı: ${ad}`);
      continue;
    }
    if (a.tur === "evet_hayir") {
      if (typeof v !== "boolean") h.push(`${a.etiket}: evet/hayır olmalı.`);
    } else if (typeof v !== "string") {
      h.push(`${a.etiket}: metin olmalı.`);
    } else if (a.tur === "secim" && v && !(a.secenekler ?? []).includes(v)) {
      h.push(`${a.etiket}: geçersiz seçim (${v}).`);
    } else if (v.length > ekSiniri(a.tur)) {
      h.push(`${a.etiket} en fazla ${ekSiniri(a.tur)} karakter olabilir.`);
    }
  }
  return h;
}

/**
 * Formdan `generate-cases` gövdesi: metinler kırpılır; ek bilgiden yalnız görünen (seçili
 * platforma ait) ve dolu alanlar gönderilir ("hayır" yanıtı gönderilmez: boş = belirtilmedi).
 */
export function uretimGovdesi(s: UretimSecenekleri, alanlar: Record<string, EkBilgiAlani> = EK_BILGI_ALANLARI): UretimGovdesi {
  const ek: Record<string, string | boolean> = {};
  for (const [ad, a] of gorunurAlanlar(alanlar, s)) {
    const v = s.ek_bilgi[ad];
    if (a.tur === "evet_hayir") {
      if (v === true) ek[ad] = true;
    } else if (typeof v === "string" && v.trim()) {
      ek[ad] = a.tur === "uzun_metin" ? v.replace(/\s+$/, "") : v.trim();
    }
  }
  return {
    platformlar: [...s.platformlar],
    test_seviyesi: s.test_seviyesi,
    benimsenen_standartlar: s.benimsenen_standartlar.map((x) => x.trim()).filter(Boolean),
    kapsam_disi: s.kapsam_disi.trim(),
    roller: s.roller.trim(),
    ek_bilgi: ek,
  };
}

/** Gövde üretim seçeneklerinden en az birini taşıyor mu (yalnız `kip` gibi başka alan değil). */
export function secenekGovdesiMi(govde: unknown): govde is UretimGovdesi {
  return nesneMi(govde) && ["platformlar", "test_seviyesi", "benimsenen_standartlar", "kapsam_disi", "roller", "ek_bilgi"].some((k) => k in govde);
}

/** core replay adı: platform eki (Web→web, Mobil-*→mobile, Desktop-*→desktop, API→api, Data→data). */
export function platformEki(p: string): string {
  if (p === "Web") return "web";
  if (p.startsWith("Mobil-")) return "mobile";
  if (p.startsWith("Desktop-")) return "desktop";
  if (p === "API") return "api";
  if (p === "Data") return "data";
  return p.toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

/** `platform-<ekler>/<kök>`: ekler tekil, sıralı ve `-` ile birleşik (ör. `platform-api-web/TPD-4`). Platform yoksa null. */
export function platformReplayAdi(platformlar: string[], kok: string): string | null {
  if (platformlar.length === 0) return null;
  return `platform-${[...new Set(platformlar.map(platformEki))].sort().join("-")}/${kok}`;
}

/** Derinleştirme teknikleri (P6) ve Türkçe adları. */
export const DERINLESTIRME_TEKNIKLERI: { kod: DerinlestirmeTeknigi; ad: string }[] = [
  { kod: "EP", ad: "Eşdeğerlik bölümleme" },
  { kod: "BVA", ad: "Sınır değer analizi" },
  { kod: "DT", ad: "Karar tablosu" },
  { kod: "ST", ad: "Durum geçişi" },
  { kod: "PW", ad: "Pairwise" },
  { kod: "UC", ad: "Kullanım senaryosu" },
  { kod: "EG", ad: "Hata tahmini" },
];

/** Derinleştirme golden anahtarı: `negatif/<kök>` ya da `teknik-<teknik küçük harf>/<kök>`. */
export function derinlestirmeReplayAdi(tur: "negatif" | "teknik", teknik: string | null | undefined, kok: string): string {
  return tur === "negatif" ? `negatif/${kok}` : `teknik-${(teknik ?? "").toLowerCase()}/${kok}`;
}

// ------------------------------------------------------------------ üretim kipi (011 K1, D1)

/** Kip tercihi kayıtlı değilse varsayılan: iki tur (önerilen). */
export const VARSAYILAN_URETIM_KIPI: UretimKipi = "iki_tur";

/** Ham kip değeri → kip (tanınmayan değer null). */
export function kipUyarla(x: unknown): UretimKipi | null {
  return x === "iki_tur" || x === "tek_tur" ? x : null;
}

/** Formun ve üst düğmenin ilk kipi: gereksinimde kayıtlı tercih, yoksa iki tur. */
export function baslangicKipi(y: Pick<UretimSecenekleriYaniti, "kip"> | null | undefined): UretimKipi {
  return y?.kip ?? VARSAYILAN_URETIM_KIPI;
}

/** Üretimi başlatan düğmenin metni seçili kipi söyler (UX-4). */
export function kipDugmeMetni(kip: UretimKipi): string {
  return kip === "iki_tur" ? "Tasarım modelini üret (iki tur)" : "Case üret (tek tur)";
}

/** Gereksinimin üretim işi sürerken bulunduğu durumlar ("Üretim zaten başladı"). */
const URETIM_SURUYOR: ReadonlySet<string> = new Set(["modeling", "generating"]);

/**
 * core üretim uçlarının 409 mesajı ham durum kodu taşır ("… (durum: modeling)"). Kullanıcıya
 * durum etiketiyle gösterilir: üretim zaten sürüyorsa "Üretim zaten başladı (Tasarım modeli
 * üretiliyor)", başka durumda kod yerine etiket. Mesajda durum yoksa null (olduğu gibi gösterilir).
 */
export function uretimCakismaMesaji(detay: string): string | null {
  const m = /\(durum:\s*([A-Za-z_]+)\s*\)/.exec(detay);
  if (!m) return null;
  const etiket = gereksinimDurumu(m[1]).etiket;
  if (URETIM_SURUYOR.has(m[1])) return `Üretim zaten başladı (${etiket})`;
  return detay.replace(m[0], `(${etiket})`);
}
