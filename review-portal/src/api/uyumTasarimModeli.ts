// core tasarım modeli yanıtı → portal tipleri (eksik alanlara dayanıklı; uyum.ts deseni).
import type { CiktiModu } from "./types";
import {
  modelTamamla,
  type DesignModel,
  type TasarimModeliDurumu,
  type TasarimModeliGecmisi,
  type TasarimModeliKaydi,
  type TasarimModeliOzeti,
  type TasarimModeliYaniti,
  TASARIM_MODELI_DURUMLARI,
} from "./tasarimModeliTipleri";

type Ham = Record<string, unknown>;
const nesne = (x: unknown): Ham => (x && typeof x === "object" && !Array.isArray(x) ? (x as Ham) : {});
const metin = (x: unknown, yedek = ""): string => (typeof x === "string" ? x : yedek);
const metinYaDaNull = (x: unknown): string | null => (typeof x === "string" ? x : null);
const dizi = (x: unknown): unknown[] => (Array.isArray(x) ? x : []);
const MODLAR: CiktiModu[] = ["live", "replay", "replay_miss"];
const mod = (x: unknown): CiktiModu | null => (MODLAR.includes(x as CiktiModu) ? (x as CiktiModu) : null);
const durum = (x: unknown): TasarimModeliDurumu =>
  TASARIM_MODELI_DURUMLARI.includes(x as TasarimModeliDurumu) ? (x as TasarimModeliDurumu) : "draft";

/** Özet çekirdekte yoksa içerikten hesaplanır (aynı sayımlar). */
export function modelOzeti(m: DesignModel): TasarimModeliOzeti {
  const teknik: Record<string, number> = {};
  for (const t of m.techniques) teknik[t.technique] = (teknik[t.technique] ?? 0) + 1;
  return {
    kosul: m.conditions.length,
    oge: m.coverage_items.length,
    gecersiz_oge: m.coverage_items.filter((o) => !o.valid).length,
    acik_soru: m.open_questions.length,
    varsayim: m.assumptions.length,
    model_sorunu: m.model_issues.length,
    teknik,
  };
}

export function tasarimModeliKaydiUyarla(ham: Ham): TasarimModeliKaydi {
  const icerik = modelTamamla(nesne(ham.icerik) as Partial<DesignModel>);
  const oz = nesne(ham.ozet);
  return {
    id: metin(ham.id),
    requirement_id: metin(ham.requirement_id),
    surum: typeof ham.surum === "number" ? ham.surum : 1,
    durum: durum(ham.durum),
    icerik,
    icerik_hash: metin(ham.icerik_hash),
    onaylanan_hash: metinYaDaNull(ham.onaylanan_hash),
    uretim_modu: mod(ham.uretim_modu),
    ai_call_id: metinYaDaNull(ham.ai_call_id),
    olusturma: metin(ham.olusturma),
    guncelleme: metin(ham.guncelleme, metin(ham.olusturma)),
    guncel: ham.guncel !== false,
    sorunlar: dizi(ham.sorunlar).filter((s): s is string => typeof s === "string"),
    onay_engeli: metinYaDaNull(ham.onay_engeli),
    ozet: Object.keys(oz).length ? ({ ...modelOzeti(icerik), ...oz } as TasarimModeliOzeti) : modelOzeti(icerik),
    kararlar: dizi(ham.kararlar).map((k) => {
      const n = nesne(k);
      return {
        karar: (["approve", "edit", "reject"].includes(n.karar as string) ? n.karar : "approve") as "approve" | "edit" | "reject",
        kullanici: metinYaDaNull(n.kullanici),
        zaman: metin(n.zaman),
        gerekce: metinYaDaNull(n.gerekce),
        ret_nedeni: (metinYaDaNull(n.ret_nedeni) as TasarimModeliKaydi["kararlar"][number]["ret_nedeni"]) ?? null,
      };
    }),
  };
}

export function tasarimModeliYanitiUyarla(ham: unknown): TasarimModeliYaniti {
  const n = nesne(ham);
  const m = nesne(n.model);
  return {
    requirement_id: metin(n.requirement_id),
    requirement_durum: metin(n.requirement_durum),
    model: Object.keys(m).length ? tasarimModeliKaydiUyarla(m) : null,
    gecmis: dizi(n.gecmis).map((x): TasarimModeliGecmisi => {
      const g = nesne(x);
      return { id: metin(g.id), surum: typeof g.surum === "number" ? g.surum : 1, durum: durum(g.durum), olusturma: metin(g.olusturma), uretim_modu: mod(g.uretim_modu) };
    }),
    case_uretimi_hazir: n.case_uretimi_hazir === true,
    engel: metinYaDaNull(n.engel),
  };
}
