// core-api yanıtlarını portalın türlerine uyarlayan saf dönüştürücüler.
// core-api'nin gerçek şekli (platform şeridi) ile portalın beklediği şekil farklı olduğunda burada
// eşlenir; mock arka uç zaten portal şeklini döndürdüğü için iki şekil de kabul edilir.

import type { DenetimOlayi, DenetimYaniti, ZincirDogrulama } from "./types";

/** core-api GET /audit gövdesi (tp_core.api.routers.audit.AuditOut). */
interface CoreDenetimOlayi {
  id: number | string;
  zaman: string;
  aktor: string;
  eylem: string;
  nesne: string | null;
  ozet: unknown;
  prev_hash: string;
  hash: string;
}

interface CoreDenetimYaniti {
  events: CoreDenetimOlayi[];
  tip_hash: string;
  next_before_id: number | null;
  verify?: {
    ok: boolean;
    count: number;
    tip_hash: string;
    broken_at: number | null;
    reason: string | null;
  } | null;
}

function nesneMi(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

/** Denetim özeti (jsonb) tabloda tek satır metin olarak gösterilir; boş nesne → "". */
export function ozetMetni(ozet: unknown): string {
  if (ozet === null || ozet === undefined) return "";
  if (typeof ozet === "string") return ozet;
  if (nesneMi(ozet) && Object.keys(ozet).length === 0) return "";
  try {
    return JSON.stringify(ozet);
  } catch {
    return String(ozet);
  }
}

/** GET /audit yanıtını portal şekline çevirir (core-api veya mock şekli). */
export function denetimiUyarla(govde: unknown, simdi: () => Date = () => new Date()): DenetimYaniti {
  if (nesneMi(govde) && Array.isArray(govde.olaylar)) {
    return govde as unknown as DenetimYaniti; // zaten portal şekli (mock)
  }
  if (!nesneMi(govde) || !Array.isArray(govde.events)) {
    throw new Error("Beklenmeyen denetim yanıtı");
  }
  const core = govde as unknown as CoreDenetimYaniti;
  const olaylar: DenetimOlayi[] = core.events.map((e) => ({
    id: String(e.id),
    sira: Number(e.id),
    aktor: e.aktor,
    eylem: e.eylem,
    nesne: e.nesne ?? "",
    ozet: ozetMetni(e.ozet),
    zaman: e.zaman,
    prev_hash: e.prev_hash,
    hash: e.hash,
  }));
  const v = core.verify;
  const dogrulama: ZincirDogrulama | null = v
    ? {
        gecerli: v.ok,
        kontrol_edilen: v.count,
        ilk_kirik_id: v.broken_at === null ? null : String(v.broken_at),
        son_hash: v.tip_hash || null,
        zaman: simdi().toISOString(),
      }
    : null;
  return { olaylar, dogrulama };
}
