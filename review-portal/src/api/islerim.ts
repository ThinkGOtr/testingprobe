// İşlerim (TP UX denetimi IA-01/IA-02), kayıt yeri (IA-05) ve insan sınıflandırması (IA-16) uçları.
//
// Sözleşme (core `features/islerim/api.py`, `features/triage/api.py`):
//   GET  /work-queue → {rol, rol_etiketi, toplam, ekip_toplam, benim: [Grup], ekip: [Grup + kisiler], menu: {rota: sayı}}
//        Grup {anahtar, tur, rol, roller, rol_etiketi, baslik, sonraki_adim, sayi, oge_sayisi, ogeler: [Oge]}
//        Oge  {id, tur, etiket, neden, rota, zaman, jira_key, sayi}
//   GET  /locate?tur=&id= → {bulundu, ayni_proje, proje: {pid, name} | null}
//   POST /failures/{id}/classify {sinif, gerekce} → triage kaydı + acilan_bug_draft_id
import { istek } from "./http";
import { nesneMi } from "./uyum";
import { hataAnaliziUyarla } from "./uyumTriage";
import type { HataAnalizi, HataSinifi } from "./types";

export type IsTuru = "requirement" | "case" | "script" | "run" | "failure" | "bug_draft";

export interface IsOgesi {
  id: string;
  tur: IsTuru;
  etiket: string;
  /** Neden bekliyor (kapının açıklaması). */
  neden: string;
  /** Öğenin ekranı (iç rota). */
  rota: string;
  zaman: string | null;
  jira_key: string | null;
  /** Öğenin temsil ettiği iş sayısı (ör. bir gereksinimin 3 case'i). */
  sayi: number;
}

export interface IsGrubu {
  anahtar: string;
  tur: IsTuru;
  /** Birincil rol (iş akışı sırasında ilk). */
  rol: string;
  /** İşi yapabilen tüm roller (grubun izni taşıyanlar; YD-06). Yoksa `[rol]`. */
  roller?: string[];
  /** "Test Uzmanı ya da Otomasyon Mühendisi". */
  rol_etiketi: string;
  baslik: string;
  /** Bu gruptaki işler için sıradaki adım (kullanıcı eylemi). */
  sonraki_adim: string;
  sayi: number;
  oge_sayisi: number;
  /** Rolün okuyamadığı türde boş (yalnız sayı). */
  ogeler: IsOgesi[];
  /** Yalnız ekip grubunda: rolün kişileri (kullanıcı adı; `useKisiAdi` ile görünen ada çevrilir). */
  kisiler?: string[];
}

export interface IsKuyrugu {
  rol: string;
  rol_etiketi: string;
  toplam: number;
  ekip_toplam: number;
  benim: IsGrubu[];
  ekip: IsGrubu[];
  /** Menü rozetleri: rota → çağıranın bekleyen iş sayısı. */
  menu: Record<string, number>;
}

export interface KayitYeri {
  bulundu: boolean;
  ayni_proje: boolean;
  proje: { pid: string; ad: string } | null;
}

const metin = (v: unknown): string => (typeof v === "string" ? v : typeof v === "number" ? String(v) : "");
const sayi = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : 0);

function ogeUyarla(h: unknown): IsOgesi | null {
  if (!nesneMi(h) || !metin(h.id)) return null;
  return {
    id: metin(h.id),
    tur: metin(h.tur) as IsTuru,
    etiket: metin(h.etiket),
    neden: metin(h.neden),
    rota: metin(h.rota),
    zaman: metin(h.zaman) || null,
    jira_key: metin(h.jira_key) || null,
    sayi: sayi(h.sayi) || 1,
  };
}

function grupUyarla(h: unknown): IsGrubu | null {
  if (!nesneMi(h)) return null;
  const ogeler = (Array.isArray(h.ogeler) ? h.ogeler : []).map(ogeUyarla).filter((o): o is IsOgesi => o !== null);
  return {
    anahtar: metin(h.anahtar),
    tur: metin(h.tur) as IsTuru,
    rol: metin(h.rol),
    ...(Array.isArray(h.roller) ? { roller: h.roller.filter((r): r is string => typeof r === "string") } : {}),
    rol_etiketi: metin(h.rol_etiketi) || metin(h.rol),
    baslik: metin(h.baslik),
    sonraki_adim: metin(h.sonraki_adim),
    sayi: sayi(h.sayi),
    oge_sayisi: sayi(h.oge_sayisi) || ogeler.length,
    ogeler,
    ...(Array.isArray(h.kisiler) ? { kisiler: h.kisiler.filter((k): k is string => typeof k === "string") } : {}),
  };
}

export function isKuyruguUyarla(ham: unknown): IsKuyrugu {
  const h = nesneMi(ham) ? ham : {};
  const grup = (v: unknown) => (Array.isArray(v) ? v : []).map(grupUyarla).filter((g): g is IsGrubu => g !== null && g.sayi > 0);
  const menu: Record<string, number> = {};
  if (nesneMi(h.menu)) for (const [k, v] of Object.entries(h.menu)) menu[k] = sayi(v);
  const benim = grup(h.benim);
  const ekip = grup(h.ekip);
  return {
    rol: metin(h.rol),
    rol_etiketi: metin(h.rol_etiketi) || metin(h.rol),
    toplam: typeof h.toplam === "number" ? h.toplam : benim.reduce((t, g) => t + g.sayi, 0),
    ekip_toplam: typeof h.ekip_toplam === "number" ? h.ekip_toplam : ekip.reduce((t, g) => t + g.sayi, 0),
    benim,
    ekip,
    menu,
  };
}

export function kayitYeriUyarla(ham: unknown): KayitYeri {
  if (!nesneMi(ham) || ham.bulundu !== true) return { bulundu: false, ayni_proje: false, proje: null };
  const p = nesneMi(ham.proje) ? ham.proje : null;
  const pid = p ? metin(p.pid) : "";
  return {
    bulundu: !!pid,
    ayni_proje: ham.ayni_proje === true,
    proje: pid && p ? { pid, ad: metin(p.name ?? p.ad) || pid } : null,
  };
}

/** İnsanın verebileceği sınıflar (`unknown` hariç; core `INSAN_SINIFLARI`). */
export const INSAN_SINIFLARI: Exclude<HataSinifi, "unknown">[] = ["product_defect", "test_maintenance", "test_data", "flaky", "environment"];

export const islerimApi = {
  isKuyrugu: async (): Promise<IsKuyrugu> => isKuyruguUyarla(await istek<unknown>("GET", "/work-queue")),
  kayitYeri: async (tur: IsTuru, id: string): Promise<KayitYeri> =>
    kayitYeriUyarla(await istek<unknown>("GET", "/locate", { sorgu: { tur, id } })),
  /** İnsan sınıflandırması (Test Uzmanı, Otomasyon Mühendisi); ürün hatasında bug taslağı açılır. */
  hataSiniflandir: async (
    id: string,
    g: { sinif: Exclude<HataSinifi, "unknown">; gerekce: string },
  ): Promise<{ hata: HataAnalizi; bugTaslagiId: string | null }> => {
    const ham = await istek<unknown>("POST", `/failures/${encodeURIComponent(id)}/classify`, { govde: g, kaynak: ["GET", "/failures/1"] });
    const n = nesneMi(ham) ? ham : {};
    return { hata: hataAnaliziUyarla(n), bugTaslagiId: metin(n.acilan_bug_draft_id) || null };
  },
};
