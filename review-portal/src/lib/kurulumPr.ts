/**
 * 014 müşteri CI kurulum PR'ı eylemi: metinler (TR + EN, `<html lang>`; `lib/proje.ts` kalıbı), platform
 * başına parametre alanları ve sonucun kullanıcı iletisi. Sunucu her alanı ayrıca doğrular
 * (`musteri_ci.parametre_hatalari`); buradaki zorunluluk yalnız erken uyarıdır.
 */
import type { KurulumParametreleri, KurulumPrSonucu } from "../api/types";

export type KurulumDili = "tr" | "en";
export type KurulumPlatformu = "android" | "ios";

const METINLER = {
  tr: {
    ac: "Kurulum PR'ı aç",
    yeniden: "Kurulum PR'ını yeniden aç",
    formBaslik: "Kurulum PR'ı parametreleri",
    formAciklama:
      "TP, deponun varsayılan dalına tek seferlik bir PR açar: CI iş akışı ve test iskeleti. PR'ı GitHub'da siz birleştirirsiniz. Onaylayan olarak adınız PR gövdesine yazılır.",
    zorunlu: "zorunlu",
    istegeBagli: "İsteğe bağlı (Expo / React Native gibi yerel projesi depoda olmayan uygulamalar)",
    onizle: "Önizle",
    gonder: "PR'ı aç",
    vazgec: "Vazgeç",
    onizlemeBaslik: "Önizleme: PR'a girecek dosyalar",
    dosyaYok: "PR'a girecek dosya yok.",
    eksikler: "Depoda eksik olanlar",
    elle: "Elle yapılacak",
    acildi: "Kurulum PR'ı açıldı",
    mevcut: "Bu dil için kurulum PR'ı zaten açık; yenisi açılmadı",
    gereksiz: "Depoda kurulum dosyaları zaten var; PR açılmadı",
    suruyor: "Kurulum PR'ı hazırlanıyor; birkaç saniye sonra ekranı yenileyin.",
    hazirDegil: "Parametreler eksik ya da geçersiz; PR açılamaz.",
    zorunluEksik: "Zorunlu alanları doldurun",
    parametreHatasi: "Kurulum parametreleri geçersiz",
    acilamadi: "Kurulum PR'ı açılamadı",
    taban: "Hedef dal",
  },
  en: {
    ac: "Open setup PR",
    yeniden: "Reopen setup PR",
    formBaslik: "Setup PR parameters",
    formAciklama:
      "TP opens a one-time PR against the repository's default branch: the CI workflow and the test scaffold. You merge it on GitHub. Your name is written into the PR body as the approver.",
    zorunlu: "required",
    istegeBagli: "Optional (apps whose native project is not in the repository, e.g. Expo / React Native)",
    onizle: "Preview",
    gonder: "Open PR",
    vazgec: "Cancel",
    onizlemeBaslik: "Preview: files the PR will add",
    dosyaYok: "No files to add.",
    eksikler: "Missing in the repository",
    elle: "Manual steps",
    acildi: "Setup PR opened",
    mevcut: "A setup PR for this language is already open; no new PR was opened",
    gereksiz: "The setup files already exist; no PR was opened",
    suruyor: "The setup PR is being prepared; refresh the page in a few seconds.",
    hazirDegil: "Parameters are missing or invalid; the PR cannot be opened.",
    zorunluEksik: "Fill in the required fields",
    parametreHatasi: "Invalid setup parameters",
    acilamadi: "Could not open the setup PR",
    taban: "Target branch",
  },
} as const;

export type KurulumMetinAnahtari = keyof (typeof METINLER)["tr"];

export function kurulumDili(): KurulumDili {
  const l = (typeof document !== "undefined" ? document.documentElement.lang : "").toLowerCase();
  return l.startsWith("en") ? "en" : "tr";
}

export function kurulumMetni(anahtar: KurulumMetinAnahtari, dil: KurulumDili = kurulumDili()): string {
  return METINLER[dil][anahtar] ?? METINLER.tr[anahtar];
}

export interface KurulumAlani {
  ad: keyof KurulumParametreleri;
  etiket: { tr: string; en: string };
  ornek: string;
  zorunlu?: boolean;
  sayi?: boolean;
  /** Hazırlık betiği grubu (isteğe bağlı, Expo/RN). */
  hazirlik?: boolean;
}

const ORTAK: KurulumAlani[] = [
  { ad: "uygulama_koku", etiket: { tr: "Uygulama kökü", en: "App root" }, ornek: "." },
  { ad: "varsayilan_dal", etiket: { tr: "İş akışı tetik dalı", en: "Workflow trigger branch" }, ornek: "main" },
];

const HAZIRLIK: KurulumAlani[] = [
  { ad: "hazirlik_betigi", etiket: { tr: "Hazırlık betiği", en: "Preparation script" }, ornek: ".github/tp/hazirlik.sh", hazirlik: true },
  { ad: "node_surumu", etiket: { tr: "Node sürümü", en: "Node version" }, ornek: "22", hazirlik: true },
  { ad: "izlenen_kok", etiket: { tr: "İzlenen kök (PR'da değişince testler koşar)", en: "Watched root (tests run when it changes)" }, ornek: "src", hazirlik: true },
];

export const KURULUM_ALANLARI: Record<KurulumPlatformu, KurulumAlani[]> = {
  android: [
    { ad: "test_paketi", etiket: { tr: "Test paketi", en: "Test package" }, ornek: "com.acme.bayi.tp", zorunlu: true },
    { ad: "gradle_modulu", etiket: { tr: "Gradle modülü", en: "Gradle module" }, ornek: "app" },
    { ad: "emulator_api", etiket: { tr: "Emülatör API düzeyi", en: "Emulator API level" }, ornek: "34", sayi: true },
    ...ORTAK,
    ...HAZIRLIK,
  ],
  ios: [
    { ad: "xcode_proje", etiket: { tr: "Xcode projesi (.xcodeproj / .xcworkspace)", en: "Xcode project (.xcodeproj / .xcworkspace)" }, ornek: "ios/BayiSiparis.xcworkspace", zorunlu: true },
    { ad: "sema", etiket: { tr: "Şema (scheme)", en: "Scheme" }, ornek: "BayiSiparis", zorunlu: true },
    { ad: "ui_test_hedefi", etiket: { tr: "UI test hedefi", en: "UI test target" }, ornek: "BayiSiparisUITests", zorunlu: true },
    { ad: "yapilandirma", etiket: { tr: "Yapılandırma", en: "Configuration" }, ornek: "Release" },
    { ad: "simulator", etiket: { tr: "Simülatör", en: "Simulator" }, ornek: "iPhone 16" },
    { ad: "runs_on", etiket: { tr: "GitHub runner", en: "GitHub runner" }, ornek: "macos-15" },
    ...ORTAK,
    ...HAZIRLIK,
  ],
};

export type KurulumFormu = Partial<Record<keyof KurulumParametreleri, string>>;

/** Boş zorunlu alanların etiketleri (sunucuya gitmeden erken uyarı). */
export function eksikZorunlular(platform: KurulumPlatformu, form: KurulumFormu, dil: KurulumDili = kurulumDili()): string[] {
  return KURULUM_ALANLARI[platform].filter((a) => a.zorunlu && !(form[a.ad] ?? "").trim()).map((a) => a.etiket[dil]);
}

/** Form → istek parametreleri (boşlar atılır; sayı alanı sayıya çevrilir, çevrilemezse sunucu 422 verir). */
export function formParametreleri(platform: KurulumPlatformu, form: KurulumFormu): KurulumParametreleri {
  const out: Record<string, string | number> = {};
  for (const a of KURULUM_ALANLARI[platform]) {
    const v = (form[a.ad] ?? "").trim();
    if (!v) continue;
    out[a.ad] = a.sayi && /^\d+$/.test(v) ? Number(v) : v;
  }
  return out as KurulumParametreleri;
}

/** Sonucun başlık iletisi (önizleme hariç). */
export function sonucIletisi(s: KurulumPrSonucu, dil: KurulumDili = kurulumDili()): string {
  if (s.durum === "acildi") return kurulumMetni("acildi", dil);
  if (s.durum === "mevcut") return kurulumMetni("mevcut", dil);
  if (s.durum === "gereksiz") return kurulumMetni("gereksiz", dil);
  if (s.durum === "suruyor") return s.mesaj ?? kurulumMetni("suruyor", dil);
  return kurulumMetni("onizlemeBaslik", dil);
}
