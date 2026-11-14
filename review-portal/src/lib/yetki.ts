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
  "requirement.po_approve_free_text": ["po"],
  "requirement.po_reject_free_text": ["po"],
  "baseline.manage": ["po"],
  "case.generate": ["tester"],
  "case.decide": ["tester"],
  "case.approve": ["analyst"],
  "case.publish": ["tester"],
  // 2026-11-14: Developer da kendi IDE token'ını üretir (yalnız `submit`; `publish` `case.publish` ister).
  "token.issue": ["tester", "developer"],
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
  // 013 sprint otomasyonu: otomasyon ayarları ve test verisi kataloğu.
  "automation.manage": ["analyst", "engineer"],
  "automation.jira_status": ["engineer"],
  "testdata.manage": ["analyst", "tester", "engineer"],
  // 011 test üretimi v3 (dev birleştirmesi): tasarım modeli kararı, açık soruları PO'ya gönderme,
  // Agent Probe ajan testi. Üretim seçenekleri/derinleştirme/model üretimi/P8 `case.generate`,
  // "Varsayım doğrulandı" `case.decide`, P9'a gönderme `case.approve`.
  "design_model.decide": ["tester"],
  "case.ask_po": ["analyst"],
  "agent_test.run": ["tester"],
  // 012 test kalite doğrulama: karar tablosu / ilişki (Analist yazar, PO onaylar), kontrolü
  // yeniden isteme (Testçi, Analist), ekilmiş hata koşusu (engineer, admin — eski presenter).
  "decision_table.edit": ["analyst"],
  "decision_table.approve": ["po"],
  "case.oracle_check": ["analyst", "tester"],
  "fault_run.manage": ["admin", "engineer"],
  // okuma
  "dashboard.read": HEPSI,
  "requirement.read": IS_ROLLERI,
  "case.read": IS_ROLLERI,
  // 011: case çalışma ayrıntıları (üretim özeti, açık sorular, tasarım modeli, P8, P9, derinleştirme,
  // üretim seçenekleri). Taslak bilgisi taşır: developer hariç.
  "case.analysis_read": ["admin", "analyst", "po", "tester", "engineer"],
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
  "publish.preview": ["admin", "analyst", "po", "tester", "engineer"],
  "claude_code.read": ["admin", "analyst", "tester", "engineer", "developer"],
  "demo.read": ["admin", "analyst", "po", "tester", "engineer"],
  // 012 test kalite doğrulama: tablolar gereksinim düzeyi (developer görür); case kontrol sonucu
  // ve istisna gerekçesi karar geçmişidir (developer, auditor, viewer görmez).
  "decision_table.read": IS_ROLLERI,
  "case.oracle_read": ["admin", "analyst", "po", "tester", "engineer"],
} as const satisfies Record<string, readonly Rol[]>;

export type Izin = keyof typeof IZINLER;

/**
 * Case'i kısıtlı gören roller (core `case.read` notu): yalnız onaylı/yayınlanmış case, karar
 * geçmişi ve sohbet yok. Katalogda ayrı bir izin olmadığı için sabit; core süzgeciyle aynı.
 */
export const KISITLI_CASE_ROLLERI: readonly Rol[] = ["developer"];

/**
 * Bug taslağını kısıtlı gören roller (core `bugs/serialize.py` `DEVELOPER_BUG_DURUMLARI`): yalnız
 * yayınlanmış (`published`) taslak; diğerlerinde detay 404 döner.
 */
export const KISITLI_BUG_ROLLERI: readonly Rol[] = ["developer"];
export const KISITLI_BUG_DURUMLARI: readonly string[] = ["published"];
export const BUG_KISITLI_METNI = "Bu rol yayınlanmamış bug taslaklarını göremez.";

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

/** İzni taşıyan iş rollerinin etiketleri, okunur liste: "Analist ve Automation Engineer". */
export function izinRolleriMetni(...istenen: Izin[]): string {
  const ad = [...new Set(istenen.flatMap((i) => IZINLER[i]))].filter((r) => r !== "admin").map((r) => ROL_ETIKETLERI[r]);
  if (ad.length <= 1) return ad.join("");
  return `${ad.slice(0, -1).join(", ")} ve ${ad[ad.length - 1]}`;
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
  "/caseler": ["case.read"],
  "/gereksinimler/:id/yayin": ["publish.preview"],
  "/gereksinimler/:id/karar-tablolari": ["decision_table.read"],
  "/kod": ["code.read"],
  "/kod/:id": ["code.read"],
  "/kosular": ["run.read"],
  "/kosular/:id": ["run.read"],
  "/hatalar/:id": ["failure.read"],
  "/bug-taslaklari": ["bug.read"],
  "/bug-taslaklari/:id": ["bug.read"],
  "/kontrol-kulesi": ["dashboard.read"],
  "/yol-haritasi": ["demo.read"],
  // 2026-11-14 kararı: Demo kontrolleri ekranı `demo.read` ile salt-okur açılır; ekrandaki eylemler
  // (buton kimliğini değiştir, sıfırla, Jira durumu) `demo.manage` (Sistem Yöneticisi, Automation
  // Engineer) ister ve diğer rollerde pasiftir. core asistan rota/izin eşlemesi aynıdır.
  "/demo": ["demo.read"],
  "/denetim": ["audit.read_all", "audit.read_own"],
  // `token.read` (kendi token'larını listele/iptal et) API düzeyinde tüm rollerdedir; ekran ise token
  // üretme kanalını anlatır ve ANALIZ 012 §4.2'de `claude_code.read` ile sınırlıdır (PO, Denetçi,
  // Görüntüleyici token üretemez; Developer 2026-11-14'ten beri görür ve kendi token'ını üretir).
  "/claude-code": ["claude_code.read"],
  "/test-verisi": ["case.read"],
  "/otomasyon": ["requirement.read"],
  // 011 F6: Agent Probe ajan ürünleri (okuma; bağlama gereksinim detayında `requirement.review`).
  "/ajan-urunleri": ["requirement.read"],
};

/**
 * Adresin `ROTA_IZINLERI` deseni ("/kod/abc?x=1" → "/kod/:id"); tabloda yoksa null (korumasız rota).
 */
export function rotaDeseni(yol: string): string | null {
  const temiz = (yol.split(/[?#]/)[0] || "/").replace(/\/+$/, "") || "/";
  for (const desen of Object.keys(ROTA_IZINLERI)) {
    const re = new RegExp(`^${desen.replace(/:[^/]+/g, "[^/]+")}$`);
    if (re.test(temiz)) return desen;
  }
  return null;
}

/** Adrese gitmek için gereken izinler (herhangi biri); korumasız rotada boş dizi. */
export function rotaIzinleri(yol: string): readonly Izin[] {
  const d = rotaDeseni(yol);
  return d ? ROTA_IZINLERI[d] : [];
}
