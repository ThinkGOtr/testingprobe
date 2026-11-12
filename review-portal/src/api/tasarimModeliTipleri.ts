// Test tasarım modeli (011 F3, iki tur): rules/schemas/design_model.schema.json + core uçları
// (GET /requirements/{id}/design-model, POST /design-models/{id}/decision).
// Model case yazmaz; koşulları, teknikleri, kapsam öğelerini ve tekniğe göre ayrıntılı modelleri
// verir. Analist onaylayınca case üretimi (tur 2) yalnızca bu modelden yapılır.
import type { CiktiModu, RetNedeni } from "./types";

export type Teknik = "EP" | "BVA" | "DT" | "ST" | "PW" | "UC" | "EG";
export type Risk = "high" | "medium" | "low";
export type SoruSahibi = "PO" | "analyst" | "developer" | "";

export interface TestKosulu {
  id: string; // TCOND-n
  ac_refs: string[];
  statement: string;
  risk: Risk;
  rationale: string;
}

export interface TeknikSecimi {
  condition_id: string;
  technique: Teknik;
  rationale: string;
}

/** case-generation v3 `coverage_items` öğesiyle aynı biçim. */
export interface ModelKapsamOgesi {
  id: string;
  ac_ref: string | null;
  definition: string;
  valid: boolean;
}

export interface Bolum {
  field: string;
  item_id: string;
  definition: string;
  representative: string;
  valid: boolean;
}

export type SinirTarafi = "on" | "below" | "above";
export type SinirBeklenen = "accept" | "reject" | "open_question";

export interface SinirDegeri {
  field: string;
  item_id: string;
  value: string;
  side: SinirTarafi;
  expected: SinirBeklenen;
  inclusive_source: string | null;
}

export interface KararTablosu {
  id: string;
  conditions: string[];
  actions: string[];
  rules: { item_id: string; condition_values: { condition: string; value: string }[]; actions: string[] }[];
  undefined_combinations: string[];
}

export interface DurumModeli {
  id: string;
  states: string[];
  valid_transitions: { item_id: string; from: string; event: string; to: string }[];
  invalid_transitions: { item_id: string; from: string; event: string }[];
  undefined_transitions: string[];
}

export interface Akis {
  item_id: string;
  kind: "MF" | "AF" | "EF";
  steps: string[];
  condition: string;
}

export interface PairwiseModeli {
  parameters: { name: string; values: string[] }[];
  constraints: string[];
}

export type ModelSorunuTuru = "overlap" | "missing_boundary" | "unreachable" | "undefined_combination" | "other";

export interface ModelSorunu {
  kind: ModelSorunuTuru;
  detail: string;
}

export interface AcikSoru {
  id: string;
  question: string;
  owner: SoruSahibi;
}

export interface Varsayim {
  id: string;
  statement: string;
  owner: SoruSahibi;
}

export interface DesignModel {
  conditions: TestKosulu[];
  techniques: TeknikSecimi[];
  coverage_items: ModelKapsamOgesi[];
  partitions: Bolum[];
  boundaries: SinirDegeri[];
  decision_tables: KararTablosu[];
  state_models: DurumModeli[];
  flows: Akis[];
  pairwise: PairwiseModeli;
  model_issues: ModelSorunu[];
  open_questions: AcikSoru[];
  assumptions: Varsayim[];
}

export type TasarimModeliDurumu = "draft" | "approved" | "rejected" | "superseded";
export const TASARIM_MODELI_DURUMLARI: readonly TasarimModeliDurumu[] = ["draft", "approved", "rejected", "superseded"];

export interface TasarimModeliKarari {
  karar: "approve" | "edit" | "reject";
  kullanici: string | null;
  zaman: string;
  gerekce: string | null;
  ret_nedeni: ModelRetNedeni | RetNedeni | null;
}

export interface TasarimModeliOzeti {
  kosul: number;
  oge: number;
  gecersiz_oge: number;
  acik_soru: number;
  varsayim: number;
  model_sorunu: number;
  teknik: Record<string, number>;
}

export interface TasarimModeliKaydi {
  id: string;
  requirement_id: string;
  surum: number;
  durum: TasarimModeliDurumu;
  icerik: DesignModel;
  icerik_hash: string;
  onaylanan_hash: string | null;
  uretim_modu: CiktiModu | null;
  ai_call_id: string | null;
  olusturma: string;
  guncelleme: string;
  /** Model gereksinimin güncel PO onaylı içeriğine ait mi (false: story değişti, model eski). */
  guncel: boolean;
  /** Deterministik model kontrolü ihlalleri; doluysa onay reddedilir ("Düzelt" gerekir). */
  sorunlar: string[];
  onay_engeli: string | null;
  ozet: TasarimModeliOzeti;
  kararlar: TasarimModeliKarari[];
}

export interface TasarimModeliGecmisi {
  id: string;
  surum: number;
  durum: TasarimModeliDurumu;
  olusturma: string;
  uretim_modu: CiktiModu | null;
}

export interface TasarimModeliYaniti {
  requirement_id: string;
  requirement_durum: string;
  model: TasarimModeliKaydi | null;
  gecmis: TasarimModeliGecmisi[];
  /** Onaylı, güncel model var ve gereksinim model_ready: "Case'leri üret" açık. */
  case_uretimi_hazir: boolean;
  engel: string | null;
}

export interface TasarimModeliKararGirdisi {
  karar: "approve" | "edit" | "reject";
  icerik_hash: string;
  icerik?: DesignModel;
  ret_nedeni?: ModelRetNedeni;
  gerekce?: string;
}

/** D1: tasarım modeli ret nedenleri (case ret nedenlerinden ayrı; core case nedenine 422 döner). */
export type ModelRetNedeni =
  | "wrong_technique"
  | "missing_condition"
  | "wrong_coverage_item"
  | "wrong_boundary"
  | "invented_rule"
  | "missing_ac"
  | "out_of_scope";

/** Üretim kipi (011 K1): iki tur varsayılan; tek tur hızlı yol. */
export type UretimKipi = "iki_tur" | "tek_tur";

export interface UretimBaslatGirdisi {
  kip: UretimKipi;
}

/** Eksik/bozuk alanları boş değerle tamamlar (eski ya da kısmi çekirdek yanıtına dayanıklılık). */
export function modelTamamla(ham: Partial<DesignModel> | null | undefined): DesignModel {
  const m = ham ?? {};
  return {
    conditions: m.conditions ?? [],
    techniques: m.techniques ?? [],
    coverage_items: m.coverage_items ?? [],
    partitions: m.partitions ?? [],
    boundaries: m.boundaries ?? [],
    decision_tables: m.decision_tables ?? [],
    state_models: m.state_models ?? [],
    flows: m.flows ?? [],
    pairwise: { parameters: m.pairwise?.parameters ?? [], constraints: m.pairwise?.constraints ?? [] },
    model_issues: m.model_issues ?? [],
    open_questions: m.open_questions ?? [],
    assumptions: m.assumptions ?? [],
  };
}
