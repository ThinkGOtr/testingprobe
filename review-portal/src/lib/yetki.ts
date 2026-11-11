// Rol ve izin kataloğu — portal kopyası (tek kaynak: core `tp_core/auth/yetki.py`, ANALIZ 012 §4).
//
// Portal izinleri `GET /auth/me` → `izinler` alanından okur. Alan yoksa (eski core, örnek veri)
// aynı katalogdan rolün izinleri türetilir. UI gizlemesi kontrol değildir; kontrol çekirdektedir.
import type { Rol } from "../api/types";

export const ROLLER = ["admin", "auditor", "analyst", "po", "tester", "engineer", "developer", "viewer"] as const satisfies readonly Rol[];

/** core `ROL_ETIKETLERI` ile birebir. */
export const ROL_ETIKETLERI: Record<Rol, string> = {
  admin: "Sistem Yöneticisi",
  auditor: "Denetçi",
  analyst: "Analist",
  po: "PO",
  tester: "Testçi",
  engineer: "Automation Engineer",
  developer: "Developer",
  viewer: "Görüntüleyici",
};

/** Kaldırılan rol → yerine geçen (core `ESKI_ROLLER`). */
export const ESKI_ROLLER: Record<string, Rol> = { presenter: "admin" };

export function normalizeRol(rol: string | null | undefined): Rol | null {
  if (!rol) return null;
  const r = ESKI_ROLLER[rol] ?? rol;
  return (ROLLER as readonly string[]).includes(r) ? (r as Rol) : null;
}

/** Rol etiketi; bilinmeyen rol aynen döner. */
export function rolEtiketi(rol: string | null | undefined): string {
  const r = normalizeRol(rol);
  return r ? ROL_ETIKETLERI[r] : (rol ?? "");
}

const HEPSI: readonly Rol[] = ROLLER;
const IS_ROLLERI: readonly Rol[] = ["admin", "analyst", "po", "tester", "engineer", "developer"];

/** core `IZINLER` kopyası (ANALIZ §4.1, §4.2). Katalog değişirse ikisi birlikte değişir (yetki.test.ts). */
export const IZINLER = {
  // aksiyonlar
  "requirement.import": ["analyst"],
  "requirement.review": ["analyst"],
  "requirement.doc_fix": ["po"],
  "baseline.manage": ["po"],
  "case.generate": ["tester"],
  "case.decide": ["tester"],
  "case.approve": ["analyst"],
  "case.publish": ["tester"],
  "token.issue": ["tester"],
  "code.generate": ["engineer"],
  "code.break_verify": ["engineer"],
  "code.review": ["engineer"],
  "code.merge": ["engineer"],
  "code.repair": ["engineer"],
  "run.trigger_scheduled": ["engineer"],
  "run.trigger_manual": ["engineer", "developer"],
  "bug.decide": ["tester"],
  "demo.manage": ["admin", "engineer"],
  "audit.verify": ["admin", "auditor"],
  // okuma
  "dashboard.read": HEPSI,
  "requirement.read": IS_ROLLERI,
  "case.read": IS_ROLLERI,
  "code.read": ["admin", "analyst", "tester", "engineer"],
  "run.read": HEPSI,
  "run.artifacts": IS_ROLLERI,
  "failure.read": IS_ROLLERI,
  "bug.read": IS_ROLLERI,
  "audit.read_all": ["admin", "auditor"],
  "audit.read_own": ["analyst", "po", "tester", "engineer", "developer"],
  "events.read": IS_ROLLERI,
  "assistant.use": HEPSI,
  "token.read": HEPSI,
} as const satisfies Record<string, readonly Rol[]>;

export type Izin = keyof typeof IZINLER;

/**
 * Case'i kısıtlı gören roller (core `case.read` notu): yalnız onaylı/yayınlanmış case, karar
 * geçmişi ve sohbet yok. Katalogda ayrı bir izin olmadığı için sabit; core süzgeciyle aynı.
 */
export const KISITLI_CASE_ROLLERI: readonly Rol[] = ["developer"];

/** Rolün katalogdaki izinleri (core `rol_izinleri`; sıralı). */
export function rolIzinleri(rol: string | null | undefined): Izin[] {
  const r = normalizeRol(rol);
  if (!r) return [];
  return (Object.keys(IZINLER) as Izin[]).filter((k) => (IZINLER[k] as readonly Rol[]).includes(r)).sort();
}

/** İzni taşıyan roller (yetkisiz düğme nedeni için). */
export function izinRolleri(izin: Izin): readonly Rol[] {
  return IZINLER[izin];
}

/** Oturumun etkin izinleri: core `izinler` verdiyse o, yoksa katalogdan rolün izinleri. */
export function oturumIzinleri(k: { rol: string; izinler?: readonly string[] | null } | null | undefined): ReadonlySet<string> {
  if (!k) return new Set();
  return new Set(Array.isArray(k.izinler) ? k.izinler : rolIzinleri(k.rol));
}

/** Verilen izinlerden en az biri var mı. */
export function izinVar(izinler: ReadonlySet<string>, ...istenen: Izin[]): boolean {
  return istenen.some((i) => izinler.has(i));
}

/** Yetkisiz düğmenin nedeni: "Bu işlem için gereken rol: Testçi". */
export function izinNedeni(...istenen: Izin[]): string {
  const roller = [...new Set(istenen.flatMap((i) => IZINLER[i]))];
  return `Bu işlem için gereken rol: ${roller.map((r) => ROL_ETIKETLERI[r]).join(" / ")}`;
}

/**
 * Rota → izin (ANALIZ §4.2). Birden çok izin "herhangi biri" demektir. Menü, sayfa koruması ve
 * açılış ekranı aynı tabloyu kullanır.
 */
export const ROTA_IZINLERI: Record<string, readonly Izin[]> = {
  "/gereksinimler": ["requirement.read"],
  "/gereksinimler/:id": ["requirement.read"],
  "/gereksinimler/:id/caseler": ["case.read"],
  "/gereksinimler/:id/yayin": ["case.publish"],
  "/kod": ["code.read"],
  "/kod/:id": ["code.read"],
  "/kosular": ["run.read"],
  "/kosular/:id": ["run.read"],
  "/hatalar/:id": ["failure.read"],
  "/bug-taslaklari": ["bug.read"],
  "/bug-taslaklari/:id": ["bug.read"],
  "/kontrol-kulesi": ["dashboard.read"],
  "/yol-haritasi": ["demo.manage"],
  "/demo": ["demo.manage"],
  "/denetim": ["audit.read_all", "audit.read_own"],
  "/claude-code": ["token.issue"],
};
