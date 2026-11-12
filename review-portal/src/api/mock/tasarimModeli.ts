// Mock arka uç: test tasarım modeli (011 F3, iki tur). Core sözleşmesi:
//   GET  /requirements/{id}/design-model      son model + geçmiş özeti
//   POST /requirements/{id}/design-model      modeli (yeniden) üret (202, asama "model")
//   POST /design-models/{id}/decision         approve | edit | reject (görülen hash zorunlu)
// İki turun ilk adımı `generate-cases {kip:"iki_tur"}` ile de başlar (handlers.ts → modelUretimiBaslat).
// Model içeriği golden kaydından (rules/replay/design_model/golden; kaynaklar.json `design_model`)
// gelir; o yoksa aynı story'nin case_generation golden'ının üst listelerinden türetilir
// (coverage_items / open_questions / assumptions birebir aynı kalır: tur-2 eşitlik kuralı).
import { ApiError } from "../http";
import type { CaseUretimOzeti, GereksinimDetay, IsYaniti, Kullanici, RetNedeni, Rol } from "../types";
import {
  modelTamamla,
  type DesignModel,
  type ModelKapsamOgesi,
  type TasarimModeliKaydi,
  type TasarimModeliKararGirdisi,
  type TasarimModeliYaniti,
  type Teknik,
} from "../tasarimModeliTipleri";
import { modelOzeti } from "../uyumTasarimModeli";
import { kanonikJson, sha256Hex } from "../../lib/sha256";
import { modelSorunlari, TEKNIK_ONEKI } from "../../lib/tasarimModeli";
import { goldenCaseKaydi, KAYNAK, type MockVeri } from "./fixtures";

type Rota = [string, RegExp, (m: RegExpMatchArray, q: URLSearchParams, govde: unknown) => unknown];

/** handlers.ts'in iç yardımcıları (durum makinesi, roller, arka plan işi) — tek kaynaktan. */
export interface ModelBaglami {
  veri: () => MockVeri;
  girisGerekli: () => Kullanici;
  rolGerekli: (...roller: Rol[]) => Kullanici;
  gecir: (g: GereksinimDetay, ...yol: GereksinimDetay["durum"][]) => void;
  arkaPlan: (adimlar: (() => void)[]) => void;
  yeniId: (onek: string) => string;
  simdi: () => string;
  denetimEkle: (eylem: string, nesne: string, ozet: string, aktor?: string) => void;
  gereksinimOlayi: (g: GereksinimDetay) => void;
  is: (durum: string, mesaj?: string) => IsYaniti;
  /** D1/K20: onaydan sonra tur 2'yi (onaylı modelden case üretimi) başlatır; yoksa tur 2 elle başlar. */
  turIkiBaslat?: (g: GereksinimDetay) => IsYaniti;
}

/** D1 onay yanıtının tur 2 bilgisi (approve/edit sonrası; ret ve eski core'da alan yok). */
export interface Tur2Yaniti {
  basladi: boolean;
  job_id?: string;
  uretim_no?: number;
  mesaj?: string;
}

export const MODEL_ISI = "model.generate";
/** Model üretimi başlatılabilen gereksinim durumları (core: po_approved | cases_ready | failed | model_ready). */
export const MODEL_BASLANGIC = ["po_approved", "cases_ready", "failed", "model_ready"] as const;

export function modelHash(m: DesignModel): string {
  return `sha256:${sha256Hex(kanonikJson(m)).slice(0, 16)}`;
}

const kopyala = <T>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

type GoldenModel = { girdi_ac?: string[]; output: DesignModel };
function goldenModeller(): Record<string, GoldenModel> {
  return ((KAYNAK as unknown as { design_model?: Record<string, GoldenModel> }).design_model ?? {});
}

const AC_RE = /^AC\d+$/;

/** case_generation golden'ının üst listelerinden asgari bir tasarım modeli (golden yoksa). */
export function ozettenModel(ozet: Partial<CaseUretimOzeti> | Record<string, unknown>): DesignModel {
  const o = ozet as { coverage_items?: ModelKapsamOgesi[]; open_questions?: DesignModel["open_questions"]; assumptions?: DesignModel["assumptions"] };
  const ogeler = kopyala(o.coverage_items ?? []);
  const acler = [...new Set(ogeler.map((x) => x.ac_ref).filter((a): a is string => !!a && AC_RE.test(a)))];
  const conditions = acler.map((ac, i) => ({
    id: `TCOND-${i + 1}`,
    ac_refs: [ac],
    statement: ogeler.find((x) => x.ac_ref === ac)?.definition ?? ac,
    risk: "medium" as const,
    rationale: `${ac} kabul kriterinden türetildi.`,
  }));
  const kosulu = (ac: string | null) => conditions.find((c) => c.ac_refs[0] === ac)?.id ?? conditions[0]?.id ?? "TCOND-1";
  const techniques: DesignModel["techniques"] = [];
  for (const x of ogeler) {
    const t = (Object.keys(TEKNIK_ONEKI) as Teknik[]).find((k) => x.id.startsWith(TEKNIK_ONEKI[k]));
    if (!t) continue;
    const condition_id = kosulu(x.ac_ref);
    if (!techniques.some((y) => y.condition_id === condition_id && y.technique === t)) {
      techniques.push({ condition_id, technique: t, rationale: `${x.ac_ref ?? "Kaynak"} için ${t} uygun.` });
    }
  }
  const dt = ogeler.filter((x) => x.id.startsWith("DT-"));
  return modelTamamla({
    conditions,
    techniques,
    coverage_items: ogeler,
    partitions: ogeler
      .filter((x) => x.id.startsWith("EP-"))
      .map((x) => ({ field: x.ac_ref ?? "girdi", item_id: x.id, definition: x.definition, representative: "", valid: x.valid })),
    boundaries: ogeler
      .filter((x) => x.id.startsWith("BV-"))
      .map((x) => ({ field: x.ac_ref ?? "girdi", item_id: x.id, value: x.definition, side: "on" as const, expected: x.valid ? ("accept" as const) : ("reject" as const), inclusive_source: x.ac_ref })),
    decision_tables: dt.length
      ? [{ id: "DT1", conditions: ["Koşul"], actions: ["Sonuç"], rules: dt.map((x) => ({ item_id: x.id, condition_values: [{ condition: "Koşul", value: x.definition.slice(0, 40) }], actions: [x.valid ? "kabul" : "ret"] })), undefined_combinations: [] }]
      : [],
    flows: ogeler.filter((x) => x.id.startsWith("UC-")).map((x) => ({ item_id: x.id, kind: x.id === "UC-MF" ? ("MF" as const) : x.id.startsWith("UC-AF") ? ("AF" as const) : ("EF" as const), steps: [x.definition], condition: "" })),
    open_questions: kopyala(o.open_questions ?? []),
    assumptions: kopyala(o.assumptions ?? []),
  });
}

/** Gereksinimin golden modeli (önce design_model golden'ı, yoksa case_generation özetinden). */
export function goldenModel(g: GereksinimDetay): { model: DesignModel; mod: "replay" | "replay_miss" } {
  const ad = goldenCaseKaydi(g);
  if (ad) {
    const dm = goldenModeller()[ad];
    if (dm) return { model: modelTamamla(kopyala(dm.output)), mod: "replay" };
    const ozet = KAYNAK.case_generation[ad]?.ozet;
    if (ozet) return { model: ozettenModel(ozet), mod: "replay" };
  }
  // core: REPLAY-MISS politikası raise → model yazılmaz. Örnek veri asgari, işaretli bir model gösterir.
  return {
    model: modelTamamla({
      conditions: g.kabul_kriterleri.map((ac, i) => ({ id: `TCOND-${i + 1}`, ac_refs: [ac.ref], statement: ac.metin, risk: "medium" as const, rationale: "Kayıtlı çıktı yok (REPLAY-MISS)." })),
      techniques: g.kabul_kriterleri.map((_ac, i) => ({ condition_id: `TCOND-${i + 1}`, technique: "EP" as const, rationale: "Kayıtlı çıktı yok (REPLAY-MISS)." })),
      coverage_items: g.kabul_kriterleri.map((ac, i) => ({ id: `EP-V${i + 1}`, ac_ref: ac.ref, definition: ac.metin.slice(0, 300), valid: true })),
    }),
    mod: "replay_miss",
  };
}

function modeller(v: MockVeri, rid: string): TasarimModeliKaydi[] {
  return ((v.tasarimModelleri ??= {})[rid] ??= []);
}

/** Model kaydı yanıt biçiminde: hash, sorunlar, özet, onay engeli güncel içerikten. */
function kayitGuncelle(m: TasarimModeliKaydi, g: GereksinimDetay | undefined): TasarimModeliKaydi {
  m.icerik_hash = modelHash(m.icerik);
  m.sorunlar = modelSorunlari(m.icerik);
  m.ozet = modelOzeti(m.icerik);
  m.guncel = !!g && (!g.po.onaylanan_hash || !g.icerik_hash || g.po.onaylanan_hash === g.icerik_hash);
  m.onay_engeli = m.sorunlar.length ? "Model kontrolleri ihlal ediliyor; 'Düzelt' ile düzeltin ya da reddedin." : null;
  return m;
}

export function sonModel(v: MockVeri, rid: string): TasarimModeliKaydi | undefined {
  const l = modeller(v, rid).filter((m) => m.durum !== "superseded");
  return l[l.length - 1];
}

/** Onaylı ve güncel model (tur 2 girdisi) — yoksa undefined. */
export function onayliModel(v: MockVeri, g: GereksinimDetay): TasarimModeliKaydi | undefined {
  const m = sonModel(v, g.id);
  if (!m || m.durum !== "approved") return undefined;
  kayitGuncelle(m, g);
  return m.guncel && m.onaylanan_hash === m.icerik_hash ? m : undefined;
}

/** İki turun ilk adımı: gereksinim → modeling → (arka plan) model_ready + taslak model. */
export function modelUretimiBaslat(ctx: ModelBaglami, g: GereksinimDetay): IsYaniti {
  if (g.ac_missing) throw new ApiError(422, "Kabul kriteri olmayan gereksinimden tasarım modeli üretilemez.");
  if (g.po.durum !== "approved") throw new ApiError(409, "PO teyidi olmadan tasarım modeli üretilemez.");
  if (!(MODEL_BASLANGIC as readonly string[]).includes(g.durum)) {
    throw new ApiError(409, `Bu durumda tasarım modeli üretilemez (durum: ${g.durum}).`);
  }
  if (g.po.onaylanan_hash && g.icerik_hash && g.po.onaylanan_hash !== g.icerik_hash) {
    throw new ApiError(409, "İçerik PO onayından sonra değişmiş; yeniden PO teyidi gerekir.");
  }
  const v = ctx.veri();
  ctx.gecir(g, "modeling");
  delete g.son_hata;
  // Önceki taslak/ret modeller yeni üretimle geçersizleşir (onaylı model de: yeni model onay ister).
  for (const m of modeller(v, g.id)) if (m.durum !== "superseded") m.durum = "superseded";
  ctx.gereksinimOlayi(g);
  ctx.arkaPlan([
    () => {
      const { model, mod } = goldenModel(g);
      const simdi = ctx.simdi();
      const liste = modeller(v, g.id);
      const kayit: TasarimModeliKaydi = kayitGuncelle(
        {
          id: ctx.yeniId("model"),
          requirement_id: g.id,
          surum: liste.length + 1,
          durum: "draft",
          icerik: model,
          icerik_hash: "",
          onaylanan_hash: null,
          uretim_modu: mod,
          ai_call_id: null,
          olusturma: simdi,
          guncelleme: simdi,
          guncel: true,
          sorunlar: [],
          onay_engeli: null,
          ozet: modelOzeti(model),
          kararlar: [],
        },
        g,
      );
      liste.push(kayit);
      ctx.gecir(g, "model_ready");
      ctx.denetimEkle("ai_call", g.id, `Tasarım modeli üretimi: ${kayit.ozet.oge} kapsam öğesi (${mod})`, "core-worker");
      ctx.gereksinimOlayi(g);
    },
  ]);
  return { ...ctx.is("started", "Tasarım modeli üretimi başlatıldı (iki tur: önce model, onayınızdan sonra case)."), kip: "iki_tur", asama: "model", uretim_no: null };
}

function yanit(v: MockVeri, g: GereksinimDetay): TasarimModeliYaniti {
  const liste = modeller(v, g.id);
  const son = sonModel(v, g.id) ?? liste[liste.length - 1];
  if (son) kayitGuncelle(son, g);
  const hazir = g.durum === "model_ready" && !!onayliModel(v, g);
  return {
    requirement_id: g.id,
    requirement_durum: g.durum,
    model: son ?? null,
    gecmis: [...liste].reverse().map((m) => ({ id: m.id, surum: m.surum, durum: m.durum, olusturma: m.olusturma, uretim_modu: m.uretim_modu })),
    case_uretimi_hazir: hazir,
    engel: hazir
      ? null
      : g.durum === "modeling"
        ? "Tasarım modeli üretiliyor."
        : !son
          ? "Henüz tasarım modeli yok."
          : son.durum === "draft"
            ? "Model analist onayı bekliyor."
            : son.durum === "rejected"
              ? "Model reddedildi; yeniden üretin."
              : g.durum !== "model_ready"
                ? `Gereksinim model onayı aşamasında değil (durum: ${g.durum}).`
                : "Onaylı model güncel içeriğe ait değil.",
  };
}

const RET_NEDENLERI: RetNedeni[] = ["hallucinated_step", "missing_ac", "wrong_test_data", "out_of_scope", "duplicate", "wrong_element"];

function karar(ctx: ModelBaglami, modelId: string, govde: unknown): TasarimModeliKaydi & { tur2?: Tur2Yaniti | null } {
  const k = ctx.rolGerekli("analyst");
  const v = ctx.veri();
  let m: TasarimModeliKaydi | undefined;
  let g: GereksinimDetay | undefined;
  for (const [rid, liste] of Object.entries(v.tasarimModelleri ?? {})) {
    const bulunan = liste.find((x) => x.id === modelId);
    if (bulunan) {
      m = bulunan;
      g = v.gereksinimler.find((x) => x.id === rid);
    }
  }
  if (!m || !g) throw new ApiError(404, `Tasarım modeli bulunamadı: ${modelId}`);
  const b = (govde ?? {}) as Partial<TasarimModeliKararGirdisi>;
  if (!b.karar || !["approve", "edit", "reject"].includes(b.karar)) throw new ApiError(422, "Karar approve, edit veya reject olmalı.");
  kayitGuncelle(m, g);
  if (typeof b.icerik_hash !== "string" || !b.icerik_hash) throw new ApiError(422, "Karar, görüntülenen içeriğin hash'ini (icerik_hash) taşımalı.");
  if (b.icerik_hash !== m.icerik_hash) throw new ApiError(409, "İçerik siz görüntüledikten sonra değişmiş; yenileyip tekrar karar verin.");
  if (m.durum !== "draft") throw new ApiError(409, `Karar yalnızca taslak modelde verilir (durum: ${m.durum}).`);
  if (g.durum !== "model_ready" || !m.guncel) throw new ApiError(409, "Gereksinim model onayı aşamasında değil ya da model eski içeriğe ait.");
  if (b.karar === "approve" && m.sorunlar.length) {
    throw new ApiError(422, `Model kontrolleri ihlal ediliyor; 'Düzelt' ile düzeltin ya da reddedin — ${JSON.stringify(m.sorunlar)}`);
  }
  if (b.karar === "edit") {
    if (!b.icerik) throw new ApiError(422, "Düzeltme kararı düzenlenmiş içerikle verilir.");
    const yeni = modelTamamla(b.icerik);
    const sorunlar = modelSorunlari(yeni);
    if (sorunlar.length) throw new ApiError(422, `Düzenlenen model kontrollerden geçmiyor — ${JSON.stringify(sorunlar)}`);
    if (modelHash(yeni) === m.icerik_hash) throw new ApiError(422, "Düzenlenen içerik mevcut içerikle aynı; 'Onayla' kullanın.");
    m.icerik = yeni;
  } else if (b.icerik !== undefined) {
    throw new ApiError(422, "İçerik yalnızca 'edit' kararında gönderilir.");
  }
  if (b.karar === "reject" && (!b.ret_nedeni || !RET_NEDENLERI.includes(b.ret_nedeni))) {
    throw new ApiError(422, "Ret için neden seçilmelidir.");
  }
  kayitGuncelle(m, g);
  m.durum = b.karar === "reject" ? "rejected" : "approved";
  m.onaylanan_hash = m.durum === "approved" ? m.icerik_hash : null;
  m.guncelleme = ctx.simdi();
  m.kararlar.push({ karar: b.karar, kullanici: k.kullanici_adi, zaman: m.guncelleme, gerekce: b.gerekce ?? null, ret_nedeni: b.karar === "reject" ? (b.ret_nedeni ?? null) : null });
  ctx.denetimEkle(`review.${b.karar}`, `design_model:${m.id}`, `Tasarım modeli kararı · ${m.icerik_hash}`);
  ctx.gereksinimOlayi(g);
  if (m.durum !== "approved" || !ctx.turIkiBaslat) return m;
  // D1/K20: onay tur 2'yi otomatik başlatır (gereksinim generating → cases_ready). Başlatılamazsa
  // onay geçerli kalır; yanıt nedeni taşır ve tur 2 elle başlatılır.
  let tur2: Tur2Yaniti;
  try {
    const y = ctx.turIkiBaslat(g);
    tur2 = { basladi: true, ...(y.job_id ? { job_id: y.job_id } : {}), ...(typeof y.uretim_no === "number" ? { uretim_no: y.uretim_no } : {}), mesaj: y.mesaj };
  } catch (e) {
    tur2 = { basladi: false, mesaj: e instanceof Error ? e.message : String(e) };
  }
  return { ...m, tur2 };
}

export function tasarimModeliRotalari(ctx: ModelBaglami): Rota[] {
  const gereksinim = (id: string) => {
    const g = ctx.veri().gereksinimler.find((x) => x.id === id);
    if (!g) throw new ApiError(404, `Gereksinim bulunamadı: ${id}`);
    return g;
  };
  return [
    [
      "GET",
      /^\/requirements\/([^/]+)\/design-model$/,
      (m) => {
        ctx.girisGerekli();
        return yanit(ctx.veri(), gereksinim(decodeURIComponent(m[1])));
      },
    ],
    [
      "POST",
      /^\/requirements\/([^/]+)\/design-model$/,
      (m) => {
        ctx.rolGerekli("analyst");
        return modelUretimiBaslat(ctx, gereksinim(decodeURIComponent(m[1])));
      },
    ],
    ["POST", /^\/design-models\/([^/]+)\/decision$/, (m, _q, govde) => karar(ctx, decodeURIComponent(m[1]), govde)],
  ];
}
