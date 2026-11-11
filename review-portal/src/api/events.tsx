// /api/events SSE akışı: tek paylaşılan bağlantı, üstel geri çekilmeyle yeniden bağlanma,
// mock modunda süreç içi olay yolu.
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { cekirdekYetenekleri, mockZorunlu, oturumBitti, ucVar } from "./http";
import { mockOlaylaraAbone } from "./mock/olaylar";
import type { PortalOlayi } from "./types";

/** core-api'nin SSE akışını kapatırken gönderdiği son olay (MIMARI-SOZLESME §5). */
export const OTURUM_BITTI = "session.ended";

export type BaglantiDurumu = "baglaniyor" | "bagli" | "yeniden" | "mock" | "kapali";

/**
 * Özellik şeritlerinin yayımladığı ayrıntılı olay adları (Demo-A: gereksinim, bulgu doğrulama, PO
 * onayı, case üretimi, yayın) ve mock arka ucun aynı adları. EventSource joker kabul etmez; `publish.*`
 * ailesi burada tek tek sayılır (yeni bir alt ad eklenirse buraya da eklenmeli).
 */
export const BILINEN_OLAYLAR = [
  "case.generated",
  "agent.step",
  "pr.opened",
  "ci.status",
  "failure.classified",
  "requirement.updated",
  "finding.updated",
  "finding.verified",
  "po.approved",
  "publish.started",
  "publish.progress",
  "publish.item",
  "publish.completed",
  "publish.done",
  "publish.failed",
  "bug.published",
  // Demo-B (core codegen + ci şeritleri): yerel kontrol, kırarak doğrulama, merge.
  "codegen.check",
  "codegen.break_verify",
  // Adım 5 gecikme bütçesi aşıldı (core öneri: REPLAY'e geç); script ekranı yenilenir.
  "codegen.latency_budget",
  "codegen.branch",
  "codegen.reviewed",
  "pr.merged",
  // Faz 4 (triage, onarım, bug, demo): core adları sözleşmede sabitlenince burada kalır; mock aynı adları üretir.
  "failure.updated",
  "repair.started",
  "repair.step",
  "repair.proposed",
  "repair.checked",
  "repair.pr_opened",
  "repair.blocked",
  "repair.ci_failed",
  "repair.merged",
  "bug.draft_created",
  "bug.draft_ready",
  "bug.draft_edited",
  "bug.prepare_failed",
  "bug.publish_failed",
  "bug.dismissed",
  "bug.reopened",
  "demo.break",
  "demo.break_failed",
  "demo.web_waiting",
  "demo.web_ready",
  "demo.web_timeout",
  "demo.ci_enqueued",
  "demo.ci_skipped",
  "demo.reset",
  "demo.progress",
  // Portal asistanı (AI-ASISTAN-PLANI §9): core yalnız oturum kullanıcısının olaylarını teslim eder;
  // veri `{mesaj_id, kullanici_id, adim_kodu}` / `{mesaj_id, kullanici_id, durum}`.
  "assistant.step",
  "assistant.answered",
] as const;

/** Ayrıntılı olayın ek konuları (sayfalar konuya abone olur, olay adına değil). */
const EK_KONULAR: Record<string, string[]> = {
  "finding.verified": ["finding.updated", "requirement.updated"],
  "po.approved": ["requirement.updated"],
  "case.generated": ["case.updated"],
  "codegen.check": ["script.updated", "ci.status"],
  "codegen.break_verify": ["script.updated", "ci.status"],
  "codegen.latency_budget": ["script.updated"],
  "codegen.branch": ["script.updated"],
  "codegen.reviewed": ["script.updated"],
  "pr.opened": ["script.updated"],
  "pr.merged": ["script.updated", "ci.status"],
  "agent.step": ["script.updated"],
  "failure.classified": ["failure.updated"],
  "bug.published": ["bug.updated"],
};

/** Ailenin her olayı aynı konuya gider (repair.* → failure.updated, bug.* → bug.updated, demo.* → demo.updated). */
const AILE_KONUSU: [string, string][] = [
  ["repair.", "failure.updated"],
  ["bug.", "bug.updated"],
  ["demo.", "demo.updated"],
];

/**
 * core-api'nin bugün gerçekten yayımladığı olay adları (MIMARI-SOZLESME §5 `GET /events`):
 * `tp_core.workflow.service.transition()` her durum geçişinde `<varlık>.state`, onay kaydında
 * `review.recorded` yayımlar. SSE'de her biri adlı olaydır (`event: <ad>`); EventSource adlı
 * olayları yalnızca `addEventListener(ad)` ile teslim eder, `onmessage` almaz. Liste core'un
 * durum makinelerinden (states.py MACHINES) türetilir; events.test.ts kaynakla karşılaştırır.
 */
export const CORE_OLAYLARI = [
  "requirement.state",
  "requirement_review.state",
  "consistency_finding.state",
  "test_case.state",
  "script.state",
  "bug_draft.state",
  "karar_tablosu.state",
  "metamorfik_iliski.state",
  "workflow_instance.state",
  "review.recorded",
] as const;

/** core varlık türü → sayfaların abone olduğu portal konusu. */
const VARLIK_KONUSU: Record<string, string> = {
  requirement: "requirement.updated",
  requirement_review: "requirement.updated",
  consistency_finding: "finding.updated",
  test_case: "case.updated",
  script: "script.updated",
  bug_draft: "bug.updated",
  // 012: karar tablosu ve ilişki aynı sayfadadır (Karar tabloları); tek konu.
  karar_tablosu: "karar_tablosu.updated",
  metamorfik_iliski: "karar_tablosu.updated",
  workflow_instance: "workflow.updated",
};

/**
 * Olayın eşleştiği konular: kendi adı + core adlarının portal karşılığı. Sayfalar konu adına
 * abone olur; böylece hem mock'un ayrıntılı olayları hem core'un `<varlık>.state` olayları aynı
 * dinleyiciye ulaşır.
 */
export function olayKonulari(o: PortalOlayi): string[] {
  const konular = [o.type];
  const durum = /^([a-z_]+)\.state$/.exec(o.type);
  if (durum && VARLIK_KONUSU[durum[1]]) konular.push(VARLIK_KONUSU[durum[1]]);
  if (o.type === "review.recorded") {
    const tur = typeof o.data.nesne_turu === "string" ? VARLIK_KONUSU[o.data.nesne_turu] : undefined;
    if (tur) konular.push(tur);
  }
  konular.push(...(EK_KONULAR[o.type] ?? []));
  for (const [onek, konu] of AILE_KONUSU) if (o.type.startsWith(onek)) konular.push(konu);
  // Onarım PR'ı olayları (pr.opened / pr.merged) `failure_id` taşıyorsa triage ekranı da yenilenir.
  if (o.type.startsWith("pr.") && typeof o.data.failure_id === "string") konular.push("failure.updated");
  // Yayın ailesi (publish.started/progress/completed/failed …): case ve gereksinim ekranları yenilenir.
  if (o.type.startsWith("publish.")) konular.push("publish.updated", "case.updated", "requirement.updated");
  return [...new Set(konular)];
}

/**
 * `useOlay` süzgeci: konu listesi (boşsa hepsi) ve isteğe bağlı nesne kimliği. Kimlik olayın kendi
 * nesnesi ya da bağlı olduğu gereksinim (`data.requirement_id`) olabilir: bulgu/case olayları
 * gereksinim ekranını da yeniler.
 */
export function olayEslesir(o: PortalOlayi, konular: ReadonlySet<string> | null, id?: string): boolean {
  if (konular && !olayKonulari(o).some((k) => konular.has(k))) return false;
  // Demo-B olayları nesnesini `script_id` / `run_id` alanında taşır (ajan adımı, koşu, kırma aşaması).
  // Faz 4: triage/onarım olayları `failure_id`, bug olayları `bug_draft_id`, asistan olayları `mesaj_id` taşır.
  return (
    !id ||
    o.id === id ||
    o.data.requirement_id === id ||
    o.data.script_id === id ||
    o.data.run_id === id ||
    o.data.failure_id === id ||
    o.data.bug_draft_id === id ||
    // Asistan olayları mesajını `mesaj_id` alanında taşır.
    o.data.mesaj_id === id
  );
}

/** EventSource'a dinleyici olarak kaydedilen tüm adlar. */
export const DINLENEN_OLAYLAR: readonly string[] = [...new Set<string>([...BILINEN_OLAYLAR, ...CORE_OLAYLARI])];

type Dinleyici = (o: PortalOlayi) => void;

export interface OlayKaynagi {
  close(): void;
  onopen: ((e: Event) => void) | null;
  onerror: ((e: Event) => void) | null;
  onmessage: ((e: MessageEvent) => void) | null;
  addEventListener(tur: string, fn: (e: MessageEvent) => void): void;
}

export interface OlayYoluSecenekleri {
  url?: string;
  /** Testlerde sahte EventSource vermek için. */
  kaynakUret?: (url: string) => OlayKaynagi;
  mock?: boolean;
  /** Gerçek SSE'ye ek olarak süreç içi mock olay yolunu da dinle (bazı uçlar örnek veriyken). */
  mockDa?: boolean;
  /** Sunucu `session.ended` gönderince (oturum kapandı/iptal/süre doldu); varsayılan: giriş ekranı. */
  oturumBitince?: () => void;
  /** Yeniden bağlanma gecikmesi (ms): min(azami, taban · 2^deneme). */
  taban?: number;
  azami?: number;
}

/** Olayı ayrıştırır; core-api zarfını açar; data JSON değilse ham metni {raw} olarak taşır. */
export function olayiAyristir(tur: string, ham: string, sonId?: string): PortalOlayi {
  let data: Record<string, unknown>;
  try {
    const p = JSON.parse(ham) as unknown;
    data = p && typeof p === "object" && !Array.isArray(p) ? (p as Record<string, unknown>) : { deger: p };
    // core-api zarfı: {"data": {...}, "ts": "..."} → iç nesne (+ ts) olayın verisidir.
    const ic = data.data;
    if (ic && typeof ic === "object" && !Array.isArray(ic) && "ts" in data && Object.keys(data).length === 2) {
      data = { ...(ic as Record<string, unknown>), ts: data.ts };
    }
  } catch {
    data = { raw: ham };
  }
  const type = tur === "message" && typeof data.type === "string" ? data.type : tur;
  // review.recorded'da `id` onay kaydının kimliğidir; sayfalar nesneye göre süzdüğü için nesne_id.
  const nesneId = type === "review.recorded" && typeof data.nesne_id === "string" ? data.nesne_id : undefined;
  const id = nesneId ?? (typeof data.id === "string" ? data.id : sonId || undefined);
  return { type, id, data };
}

/**
 * Bağlantıyı yöneten çerçeveden bağımsız sınıf (React dışında da test edilebilir).
 */
export class OlayYolu {
  private dinleyiciler = new Set<Dinleyici>();
  private durumDinleyicileri = new Set<(d: BaglantiDurumu) => void>();
  private kaynak: OlayKaynagi | null = null;
  private zamanlayici: ReturnType<typeof setTimeout> | null = null;
  private deneme = 0;
  private mockAboneligi: (() => void) | null = null;
  durum: BaglantiDurumu = "kapali";
  private readonly url: string;
  private readonly kaynakUret: (url: string) => OlayKaynagi;
  private readonly taban: number;
  private readonly azami: number;
  private readonly mock: boolean;
  private readonly mockDa: boolean;
  private readonly oturumBitince: () => void;

  constructor(s: OlayYoluSecenekleri = {}) {
    this.url = s.url ?? "/api/events";
    this.kaynakUret = s.kaynakUret ?? ((u) => new EventSource(u, { withCredentials: true }) as unknown as OlayKaynagi);
    this.taban = s.taban ?? 1000;
    this.azami = s.azami ?? 30000;
    this.mock = s.mock ?? false;
    this.mockDa = s.mockDa ?? false;
    this.oturumBitince = s.oturumBitince ?? oturumBitti;
  }

  abone(fn: Dinleyici): () => void {
    this.dinleyiciler.add(fn);
    return () => this.dinleyiciler.delete(fn);
  }

  durumAbone(fn: (d: BaglantiDurumu) => void): () => void {
    this.durumDinleyicileri.add(fn);
    return () => this.durumDinleyicileri.delete(fn);
  }

  private durumAyarla(d: BaglantiDurumu): void {
    this.durum = d;
    this.durumDinleyicileri.forEach((fn) => fn(d));
  }

  private yayinla(o: PortalOlayi): void {
    this.dinleyiciler.forEach((fn) => {
      try {
        fn(o);
      } catch (e) {
        console.error("Olay dinleyicisi hata verdi", e);
      }
    });
  }

  baslat(): void {
    if (this.mock) {
      this.mockAboneligi = mockOlaylaraAbone((o) => this.yayinla(o));
      this.durumAyarla("mock");
      return;
    }
    if (this.mockDa) this.mockAboneligi = mockOlaylaraAbone((o) => this.yayinla(o));
    this.baglan();
  }

  /** Bir sonraki deneme gecikmesi (ms). */
  gecikme(deneme: number): number {
    return Math.min(this.azami, this.taban * 2 ** deneme);
  }

  private baglan(): void {
    this.durumAyarla(this.deneme === 0 ? "baglaniyor" : "yeniden");
    let kaynak: OlayKaynagi;
    try {
      kaynak = this.kaynakUret(this.url);
    } catch {
      this.yenidenPlanla();
      return;
    }
    this.kaynak = kaynak;
    kaynak.onopen = () => {
      this.deneme = 0;
      this.durumAyarla("bagli");
    };
    kaynak.onerror = () => {
      // Tarayıcının kendi yeniden denemesine bırakmak yerine kapatıp kontrollü bekliyoruz:
      // HTTP hatasında EventSource kalıcı kapanır, ağ hatasında ise sonsuz hızlı deneyebilir.
      kaynak.close();
      // Durdurulmuş ya da yenisiyle değiştirilmiş kaynağın geç gelen hatası yeniden bağlatmaz.
      if (this.kaynak !== kaynak) return;
      this.kaynak = null;
      this.yenidenPlanla();
    };
    const isle = (tur: string) => (e: MessageEvent) => this.yayinla(olayiAyristir(tur, String(e.data), e.lastEventId));
    kaynak.onmessage = isle("message");
    for (const tur of DINLENEN_OLAYLAR) kaynak.addEventListener(tur, isle(tur));
    // core-api oturum geçersizleşince akışı `session.ended` ile kapatır: yeniden bağlanılmaz
    // (401 döngüsü olmaz), kullanıcı giriş ekranına yönlenir.
    kaynak.addEventListener(OTURUM_BITTI, () => {
      if (this.kaynak !== kaynak) return;
      this.durdur();
      this.oturumBitince();
    });
  }

  private yenidenPlanla(): void {
    if (this.zamanlayici) return;
    const bekleme = this.gecikme(this.deneme);
    this.deneme += 1;
    this.durumAyarla("yeniden");
    this.zamanlayici = setTimeout(() => {
      this.zamanlayici = null;
      this.baglan();
    }, bekleme);
  }

  durdur(): void {
    if (this.zamanlayici) clearTimeout(this.zamanlayici);
    this.zamanlayici = null;
    this.kaynak?.close();
    this.kaynak = null;
    this.mockAboneligi?.();
    this.mockAboneligi = null;
    this.deneme = 0;
    this.durumAyarla("kapali");
  }
}

interface OlayBaglami {
  yol: OlayYolu | null;
  durum: BaglantiDurumu;
}

const Baglam = createContext<OlayBaglami>({ yol: null, durum: "kapali" });

/**
 * Oturum açıkken olay akışını tutar.
 * - Mock zorunluysa (VITE_MOCK=1) veya core-api `GET /events` sunmuyorsa yalnızca süreç içi yol.
 * - Aksi halde gerçek SSE'ye bağlanır ve örnek veriden cevaplanan uçların olayları için süreç içi
 *   yolu da dinler (karma mod: bazı uçlar gerçek, bazıları örnek veri).
 */
export function OlayProvider({ children, etkin }: { children: ReactNode; etkin: boolean }) {
  const [durum, setDurum] = useState<BaglantiDurumu>("kapali");
  const [yol, setYol] = useState<OlayYolu | null>(null);

  useEffect(() => {
    if (!etkin) return;
    let iptalEdildi = false;
    let temizle: (() => void) | null = null;
    void (async () => {
      let mock = mockZorunlu();
      if (!mock) {
        const y = await cekirdekYetenekleri();
        mock = y !== null && !ucVar(y, "GET", "/events");
      }
      if (iptalEdildi) return;
      const y = new OlayYolu({ mock, mockDa: true });
      const iptal = y.durumAbone(setDurum);
      y.baslat();
      setYol(y);
      temizle = () => {
        iptal();
        y.durdur();
      };
    })();
    return () => {
      iptalEdildi = true;
      temizle?.();
      setYol(null);
      setDurum("kapali");
    };
  }, [etkin]);

  return <Baglam.Provider value={{ yol, durum }}>{children}</Baglam.Provider>;
}

export function useBaglantiDurumu(): BaglantiDurumu {
  return useContext(Baglam).durum;
}

/**
 * Olay dinler. `turler` verilirse yalnızca o konular (olayın adı veya `olayKonulari` karşılığı);
 * `id` verilirse yalnızca o nesne.
 */
export function useOlay(fn: (o: PortalOlayi) => void, turler?: readonly string[], id?: string): void {
  const { yol } = useContext(Baglam);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const turAnahtari = turler?.join("|") ?? "";
  useEffect(() => {
    if (!yol) return;
    const kume = turAnahtari ? new Set(turAnahtari.split("|")) : null;
    return yol.abone((o) => {
      if (olayEslesir(o, kume, id)) fnRef.current(o);
    });
  }, [yol, turAnahtari, id]);
}
