// Çok proje: portal tarafı ince katman (TP-COK-PROJE-PLANI §6.3, Şerit 6).
//
// - Seçim sunucudadır (`PUT /api/proje` → oturum + kullanıcı kaydı); portal yalnız ister ve sonra
//   sekmeyi yeni projede **tam sayfa** yeniden yükler: modül düzeyindeki bütün önbellekler (uç listesi,
//   ekran verisi, SSE akışı, asistan depoları) böylece kesin boşalır. Kişiye ait istemci depoları
//   ayrıca `oturumVerileriniTemizle()` ile silinir (sessionStorage'daki sohbet vb. eski projeye aittir).
// - Nesne ayrıntı sayfasındaysa (ör. `/gereksinimler/<id>`) liste sayfasına dönülür: kimlik yeni
//   projede yoktur.
// - AI Probe ortak değiştiricisi (1.1.0) varsa proje menüsü onundur: portal `AIProbeSwitcher.setProjects`
//   ile listeyi verir ve `aiprobe:project-change` olayını dinleyip (iptal ederek) aynı yolu izler;
//   kendi seçicisini çizmez (çift seçici yok).
import { api } from "../api/client";
import type { ProjeListesi, ProjeOzeti } from "../api/types";
import type { AiprobeProjeVerisi } from "../vendor/aiprobe-switcher/switcher-1.2.0.js";
import { oturumVerileriniTemizle } from "./oturumTemizligi";
import { gezinti } from "./kimlikKipi";
import { rolEtiketi } from "./yetki";

/** Ortak değiştiricinin proje değişim olayı (`CustomEvent<{pid}>`, iptal edilebilir, window'a kabarır). */
export const PROJE_OLAYI = "aiprobe:project-change";

declare global {
  interface Window {
    AIProbeSwitcher?: { setProjects?: (data: AiprobeProjeVerisi | null) => void; projects?: unknown; VERSION?: string };
  }
}

// ---------------------------------------------------------------- i18n

export type ProjeDili = "tr" | "en";

const METINLER = {
  tr: {
    proje: "Proje",
    projeler: "Projeleriniz",
    projeSec: "Proje seçin",
    projeYok: "Atanmış proje yok",
    geciliyor: "Geçiliyor…",
    secili: "seçili",
    rol: "Rol",
    roller: "Roller",
    yukleniyor: "Yükleniyor…",
    degistirilemedi: "Proje değiştirilemedi.",
    degisti: "Proje değiştirildi:",
    baskaSekme: "Proje başka bir sekmede değiştirildi; sayfa yeni projeyle yenileniyor.",
    rolYokBaslik: "Bu projede rolünüz yok",
    rolYokMetin: "Seçili projede Testing Probe rolünüz bulunmuyor. Devam etmek için rolünüz olan bir proje seçin.",
    projeDegistir: "Proje değiştir",
    grup: "Organizasyon ve proje",
  },
  en: {
    proje: "Project",
    projeler: "Your projects",
    projeSec: "Choose a project",
    projeYok: "No project assigned",
    geciliyor: "Switching…",
    secili: "selected",
    rol: "Role",
    roller: "Roles",
    yukleniyor: "Loading…",
    degistirilemedi: "Could not switch project.",
    degisti: "Project switched:",
    baskaSekme: "The project was changed in another tab; reloading with the new project.",
    rolYokBaslik: "You have no role in this project",
    rolYokMetin: "You have no Testing Probe role in the selected project. Choose a project where you have a role.",
    projeDegistir: "Switch project",
    grup: "Organization and project",
  },
} as const;

export type ProjeMetinAnahtari = keyof (typeof METINLER)["tr"];

/** Sayfa dili (`<html lang>`); tanınmayan dil Türkçe. */
export function projeDili(): ProjeDili {
  const l = (typeof document !== "undefined" ? document.documentElement.lang : "").toLowerCase();
  return l.startsWith("en") ? "en" : "tr";
}

export function projeMetni(anahtar: ProjeMetinAnahtari, dil: ProjeDili = projeDili()): string {
  return METINLER[dil][anahtar] ?? METINLER.tr[anahtar];
}

// ---------------------------------------------------------------- gösterim

/** Rol kodunun görünen adı: sunucu etiketi (dil) → portal kataloğu → kod. */
export function projeRolEtiketi(kod: string, liste: Pick<ProjeListesi, "rolEtiketleri"> | null | undefined, dil: ProjeDili = projeDili()): string {
  const e = liste?.rolEtiketleri?.[kod];
  if (typeof e === "string" && e) return e;
  if (e && typeof e === "object") {
    const m = e[dil] ?? e.tr;
    if (m) return m;
  }
  return rolEtiketi(kod);
}

/** "Organizasyon · Proje" (biri yoksa yalnız diğeri). */
export function projeBasligi(p: Pick<ProjeOzeti, "ad" | "org_ad"> | null | undefined): string {
  if (!p) return "";
  return [p.org_ad, p.ad].filter(Boolean).join(" · ");
}

/** Ortak değiştiricinin `setProjects` verisi (CONTRACT "Proje seçici (1.1.0)"). */
export function degistiriciProjeVerisi(liste: ProjeListesi | null): AiprobeProjeVerisi | null {
  if (!liste) return null;
  const kodlar = new Set(liste.projeler.flatMap((p) => p.roller));
  const roleLabels: Record<string, { tr: string; en: string }> = {};
  for (const k of kodlar) roleLabels[k] = { tr: projeRolEtiketi(k, liste, "tr"), en: projeRolEtiketi(k, liste, "en") };
  return {
    enabled: true,
    projects: liste.projeler.map((p) => ({ pid: p.pid, name: p.ad, org_name: p.org_ad ?? "", roles: p.roller })),
    activeId: liste.secili,
    roleLabels,
  };
}

// ---------------------------------------------------------------- ortak değiştirici

/** Ortak değiştirici proje menüsünü destekliyor mu (1.1.0+, `AIProbeSwitcher.setProjects`). */
export function degistiriciProjeDestegi(): boolean {
  return typeof window !== "undefined" && typeof window.AIProbeSwitcher?.setProjects === "function";
}

/** Listeyi ortak değiştiriciye verir (sonradan bağlanan değiştiriciler de alır). */
export function degistiriciyeProjeleriVer(liste: ProjeListesi | null): boolean {
  const sw = typeof window !== "undefined" ? window.AIProbeSwitcher : undefined;
  if (typeof sw?.setProjects !== "function") return false;
  sw.setProjects(degistiriciProjeVerisi(liste));
  return true;
}

// ---------------------------------------------------------------- geçiş

/**
 * Proje değişince gidilecek yol: liste ekranında kalınır; ayrıntı (kimlikli) adresinden o bölümün
 * listesine dönülür. Liste olmayan ayrıntılar (`/hatalar/<id>`) ana sayfaya döner. Sorgu (süzgeç)
 * taşınmaz: değerleri eski projeye aittir.
 */
export function projeHedefYolu(pathname: string): string {
  const parcalar = pathname.split("/").filter(Boolean);
  if (parcalar.length === 0) return "/";
  if (parcalar.length === 1) return `/${parcalar[0]}`;
  const liste = `/${parcalar[0]}`;
  return LISTESIZ.has(liste) ? "/" : liste;
}

/** Kendi listesi olmayan ayrıntı bölümleri. */
const LISTESIZ = new Set<string>(); // TP UX IA-16: /hatalar artık liste ekranı

let geciyor = false;
/** Geçiş sürüyor mu (çift tıklama / olay + düğme yarışı tek istek göndersin). */
export function projeGecisiSuruyor(): boolean {
  return geciyor;
}

/** Testler için. */
export function projeGecisiniSifirla(): void {
  geciyor = false;
}

/**
 * Seçili projeyi değiştirir: `PUT /api/proje` → kişiye ait istemci depoları temizlenir → sekme yeni
 * projede tam sayfa yüklenir. Hata fırlatılırsa sayfa olduğu gibi kalır (çağıran iletiyi gösterir).
 */
export async function projeyiDegistir(pid: string, pathname: string = window.location.pathname): Promise<void> {
  if (geciyor) return;
  geciyor = true;
  try {
    await api.projeDegistir(pid);
  } catch (e) {
    geciyor = false;
    throw e;
  }
  oturumVerileriniTemizle();
  gezinti.git(projeHedefYolu(pathname));
}

/**
 * TP UX IA-05: başka projedeki kaydın bağlantısı — projeye geçip kaydın kendisini açar (`projeyiDegistir`
 * listeye döner; burada hedef aynı ayrıntı adresi, sorgu dahil).
 */
export async function projeyeGecVeAc(pid: string, yol: string): Promise<void> {
  if (geciyor) return;
  geciyor = true;
  try {
    await api.projeDegistir(pid);
  } catch (e) {
    geciyor = false;
    throw e;
  }
  oturumVerileriniTemizle();
  gezinti.git(yol);
}

/** Başka sekmede değişen proje (409 `proje_degisti`): bulunulan bölümün listesinde yeniden yüklenir. */
export function yeniProjedeYenile(pathname: string = window.location.pathname): void {
  if (geciyor) return;
  geciyor = true;
  oturumVerileriniTemizle();
  gezinti.git(projeHedefYolu(pathname));
}
