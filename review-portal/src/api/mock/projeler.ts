// Çok proje örnek verisi (TP-COK-PROJE-PLANI §6.2): `GET /projeler`, `PUT /proje`, `/auth/me` proje
// alanları, `X-TP-Proje` tutarlılığı (409 `proje_degisti`) ve 403 `proje_rolu_yok`.
//
// Yalnız `cok-proje` senaryosunda etkindir (`sessionStorage["tp-mock-senaryo"] = "cok-proje"` ya da
// `ayar.senaryolar`); kapalıyken uçlar yoktur (404) ve `/auth/me` bugünkü gibi proje taşımaz.
// Seçim `localStorage`'dadır: sunucudaki oturum gibi sekmeler arasında ortaktır, iki sekme senaryosu
// (bir sekmede değiştir → ötekinde 409) örnek veriyle de denenebilir. Ekran verisi projeye göre
// ayrışmaz (örnek veri tek kümedir); amaç seçici ve bağlam akışıdır.
import { ApiError, PROJE_DEGISTI, PROJE_ROLU_YOK, sekmeninProjesi } from "../http";
import type { Kullanici, Rol } from "../types";
import { rolIzinleri } from "../../lib/yetki";

const SECIM_ANAHTARI = "tp-mock-proje";

interface MockProje {
  pid: string;
  kod: string;
  ad: string;
  org: string;
  /** Kullanıcının bu projedeki rolleri (etkin rolden türetilir). */
  roller: (k: Kullanici) => Rol[];
}

export const MOCK_ORG = { id: "org-ornek", ad: "Örnek Holding" };

export const MOCK_PROJELER: MockProje[] = [
  { pid: "prj-web", kod: "WEB", ad: "Web Portalı", org: MOCK_ORG.ad, roller: (k) => [k.rol] },
  { pid: "prj-mobil", kod: "MOB", ad: "Mobil Uygulama", org: MOCK_ORG.ad, roller: (k) => (k.rol === "viewer" ? [k.rol] : [k.rol, "viewer"]) },
  { pid: "prj-masaustu", kod: "DSK", ad: "Masaüstü İstemci", org: MOCK_ORG.ad, roller: (k) => [k.rol] },
];

/** Testler: rolü kaldırılmış projeler (seçiliyse uçlar 403 `proje_rolu_yok`). */
const rolsuzProjeler = new Set<string>();

export function mockProjeRolunuKaldir(pid: string): void {
  rolsuzProjeler.add(pid);
}

export function mockProjeSifirla(): void {
  rolsuzProjeler.clear();
  try {
    localStorage.removeItem(SECIM_ANAHTARI);
  } catch {
    /* yoksay */
  }
}

export function mockSeciliProje(): string {
  try {
    const v = localStorage.getItem(SECIM_ANAHTARI);
    if (v && MOCK_PROJELER.some((p) => p.pid === v)) return v;
  } catch {
    /* yoksay */
  }
  return MOCK_PROJELER[0].pid;
}

/** Başka sekmenin seçimini taklit eder (testler ve ekran denetimi). */
export function mockProjeSec(pid: string): void {
  try {
    localStorage.setItem(SECIM_ANAHTARI, pid);
  } catch {
    /* yoksay */
  }
}

function projeRolleri(p: MockProje, k: Kullanici): Rol[] {
  return rolsuzProjeler.has(p.pid) ? [] : p.roller(k);
}

/** `/auth/me` (ve giriş yanıtı) proje alanlarıyla (§6.2). */
export function projeliKullanici(k: Kullanici): Kullanici {
  const p = MOCK_PROJELER.find((x) => x.pid === mockSeciliProje())!;
  const roller = projeRolleri(p, k);
  return {
    ...k,
    izinler: roller.includes(k.rol) ? rolIzinleri(k.rol) : [],
    organizasyon: MOCK_ORG,
    proje: { pid: p.pid, kod: p.kod, ad: p.ad },
    roller,
    projeler_sayisi: MOCK_PROJELER.length,
  };
}

/** `GET /projeler` (sözleşme biçimi; ortak değiştiricinin `setProjects` verisiyle aynı). */
export function projeListesi(k: Kullanici): unknown {
  return {
    enabled: true,
    projects: MOCK_PROJELER.map((p) => ({ pid: p.pid, name: p.ad, org_name: p.org, roles: projeRolleri(p, k) })),
    active: { pid: mockSeciliProje() },
    role_labels: { viewer: { tr: "Görüntüleyici", en: "Viewer" } },
  };
}

/** `PUT /proje {pid}`: üyelik + ≥1 rol; yanıt yeni `/auth/me`. */
export function projeDegistir(k: Kullanici, govde: unknown): Kullanici {
  const pid = govde && typeof govde === "object" ? (govde as { pid?: unknown }).pid : undefined;
  const p = MOCK_PROJELER.find((x) => x.pid === pid);
  if (!p) throw new ApiError(404, "Proje bulunamadı.", { kod: "proje_yok" });
  if (projeRolleri(p, k).length === 0) throw new ApiError(403, PROJE_ROLU_YOK, { kod: "proje_rolu_yok" });
  mockProjeSec(p.pid);
  return projeliKullanici(k);
}

/** Proje kapsamlı her uçtan önce: sekmenin projesi ≠ oturumun projesi → 409; rol yok → 403. */
export function projeBaglamiDenetle(path: string): void {
  if (path.startsWith("/auth/") || path === "/projeler" || path === "/proje") return;
  const sekme = sekmeninProjesi();
  const secili = mockSeciliProje();
  if (sekme && sekme !== secili) throw new ApiError(409, PROJE_DEGISTI, { kod: "proje_degisti" });
  if (rolsuzProjeler.has(secili)) throw new ApiError(403, PROJE_ROLU_YOK, { kod: "proje_rolu_yok" });
}
