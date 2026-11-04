import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { BILINEN_OLAYLAR, CORE_OLAYLARI, DINLENEN_OLAYLAR, olayEslesir, olayiAyristir, olayKonulari, OlayYolu, type OlayKaynagi } from "./events";
import { mockOlayYayinla } from "./mock/olaylar";
import type { PortalOlayi } from "./types";

class SahteKaynak implements OlayKaynagi {
  static hepsi: SahteKaynak[] = [];
  onopen: ((e: Event) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  kapandi = false;
  dinleyiciler = new Map<string, (e: MessageEvent) => void>();
  constructor(public url: string) {
    SahteKaynak.hepsi.push(this);
  }
  close() {
    this.kapandi = true;
  }
  addEventListener(tur: string, fn: (e: MessageEvent) => void) {
    this.dinleyiciler.set(tur, fn);
  }
  ac() {
    this.onopen?.(new Event("open"));
  }
  hata() {
    this.onerror?.(new Event("error"));
  }
  gonder(tur: string, data: unknown, lastEventId = "") {
    const e = new MessageEvent(tur, { data: typeof data === "string" ? data : JSON.stringify(data), lastEventId });
    if (tur === "message") this.onmessage?.(e);
    else this.dinleyiciler.get(tur)?.(e);
  }
}

describe("OlayYolu", () => {
  beforeEach(() => {
    SahteKaynak.hepsi = [];
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  const yeni = () => new OlayYolu({ kaynakUret: (u) => new SahteKaynak(u), taban: 1000, azami: 8000 });

  it("adlı olayları ayrıştırıp dinleyicilere iletir", () => {
    const y = yeni();
    const gelen: PortalOlayi[] = [];
    y.abone((o) => gelen.push(o));
    y.baslat();
    const k = SahteKaynak.hepsi[0];
    expect(k.url).toBe("/api/events");
    k.ac();
    expect(y.durum).toBe("bagli");
    k.gonder("agent.step", { id: "scr-2", sira: 3 });
    k.gonder("message", { type: "ci.status", id: "run-1" });
    expect(gelen).toEqual([
      { type: "agent.step", id: "scr-2", data: { id: "scr-2", sira: 3 } },
      { type: "ci.status", id: "run-1", data: { type: "ci.status", id: "run-1" } },
    ]);
    y.durdur();
    expect(k.kapandi).toBe(true);
    expect(y.durum).toBe("kapali");
  });

  it("hatada kapatır ve üstel geri çekilmeyle yeniden bağlanır; açılınca sayaç sıfırlanır", () => {
    const y = yeni();
    const durumlar: string[] = [];
    y.durumAbone((d) => durumlar.push(d));
    y.baslat();
    SahteKaynak.hepsi[0].hata();
    expect(SahteKaynak.hepsi[0].kapandi).toBe(true);
    expect(y.durum).toBe("yeniden");
    vi.advanceTimersByTime(999);
    expect(SahteKaynak.hepsi).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(SahteKaynak.hepsi).toHaveLength(2);
    SahteKaynak.hepsi[1].hata();
    vi.advanceTimersByTime(1999);
    expect(SahteKaynak.hepsi).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(SahteKaynak.hepsi).toHaveLength(3);
    SahteKaynak.hepsi[2].ac();
    expect(y.durum).toBe("bagli");
    SahteKaynak.hepsi[2].hata();
    vi.advanceTimersByTime(1000);
    expect(SahteKaynak.hepsi).toHaveLength(4);
    expect(durumlar).toContain("bagli");
    y.durdur();
  });

  it("gecikme azami değerle sınırlıdır", () => {
    const y = yeni();
    expect([0, 1, 2, 3, 4, 10].map((n) => y.gecikme(n))).toEqual([1000, 2000, 4000, 8000, 8000, 8000]);
  });

  it("durdurulduktan sonra bekleyen yeniden bağlanma iptal olur", () => {
    const y = yeni();
    y.baslat();
    SahteKaynak.hepsi[0].hata();
    y.durdur();
    vi.advanceTimersByTime(60000);
    expect(SahteKaynak.hepsi).toHaveLength(1);
  });

  it("mock modunda süreç içi olay yolunu dinler", () => {
    const y = new OlayYolu({ mock: true, kaynakUret: () => new SahteKaynak("x") });
    const gelen: PortalOlayi[] = [];
    y.abone((o) => gelen.push(o));
    y.baslat();
    expect(y.durum).toBe("mock");
    mockOlayYayinla({ type: "pr.opened", id: "scr-9", data: { number: 14 } });
    expect(gelen).toHaveLength(1);
    expect(SahteKaynak.hepsi).toHaveLength(0);
    y.durdur();
    mockOlayYayinla({ type: "pr.opened", id: "scr-9", data: {} });
    expect(gelen).toHaveLength(1);
  });
});

describe("olayiAyristir", () => {
  it("JSON olmayan veriyi raw olarak taşır, lastEventId'yi kimlik yapar", () => {
    expect(olayiAyristir("ci.status", "merhaba", "run-5")).toEqual({ type: "ci.status", id: "run-5", data: { raw: "merhaba" } });
  });

  it("core-api zarfını ({data, ts}) açar ve iç kimliği kullanır", () => {
    const ham = JSON.stringify({ data: { id: "tc-1", from: "draft", durum: "approved" }, ts: "2026-10-30T18:00:00Z" });
    expect(olayiAyristir("test_case.state", ham)).toEqual({
      type: "test_case.state",
      id: "tc-1",
      data: { id: "tc-1", from: "draft", durum: "approved", ts: "2026-10-30T18:00:00Z" },
    });
  });

  it("zarf olmayan nesneyi olduğu gibi bırakır", () => {
    const ham = JSON.stringify({ id: "s1", data: { x: 1 } });
    expect(olayiAyristir("agent.step", ham).data).toEqual({ id: "s1", data: { x: 1 } });
  });
});

describe("core-api olay adları (adlı SSE olayları)", () => {
  const kok = resolve(__dirname, "../../..");
  const coreVar = existsSync(resolve(kok, "core/src/tp_core/workflow/states.py"));

  it.skipIf(!coreVar)("core'un yayımladığı her olay adı dinlenir (states.py + service.py'den türetilir)", () => {
    const states = readFileSync(resolve(kok, "core/src/tp_core/workflow/states.py"), "utf8");
    const service = readFileSync(resolve(kok, "core/src/tp_core/workflow/service.py"), "utf8");
    const varliklar = [...states.matchAll(/entity="([a-z_]+)"/g)].map((m) => m[1]);
    expect(varliklar.length).toBeGreaterThanOrEqual(7);
    expect(service).toMatch(/publish_tx\(conn, f"\{kind\}\.state"/);
    const sabitAdlar = [...service.matchAll(/publish_tx\(\s*conn,\s*"([a-z_.]+)"/g)].map((m) => m[1]);
    expect(sabitAdlar).toContain("review.recorded");
    const beklenen = [...varliklar.map((v) => `${v}.state`), ...sabitAdlar];
    for (const ad of beklenen) {
      expect(DINLENEN_OLAYLAR).toContain(ad);
      expect(CORE_OLAYLARI as readonly string[]).toContain(ad);
    }
    // Her varlığın durum olayı bir portal konusuna çevrilir (sayfalar konuya abone).
    for (const v of varliklar) {
      expect(olayKonulari({ type: `${v}.state`, data: {} })).toHaveLength(2);
    }
  });

  it("adlı requirement.state olayı (core zarfı) aboneye ulaşır ve requirement.updated konusuyla eşleşir", () => {
    vi.useFakeTimers();
    SahteKaynak.hepsi = [];
    const y = new OlayYolu({ kaynakUret: (u) => new SahteKaynak(u) });
    const gelen: PortalOlayi[] = [];
    y.abone((o) => gelen.push(o));
    y.baslat();
    const k = SahteKaynak.hepsi[0];
    k.ac();
    // core-api events.py: event: requirement.state, data: {"data": {...}, "ts": "..."}
    k.gonder("requirement.state", { data: { id: "req-7", from: "in_review", durum: "findings_open", aktor: "core-worker" }, ts: "2026-10-30T09:00:00Z" });
    k.gonder("test_case.state", { data: { id: "tc-3", from: "draft", durum: "approved", aktor: "analist" }, ts: "2026-10-30T09:00:01Z" });
    expect(gelen.map((o) => [o.type, o.id])).toEqual([
      ["requirement.state", "req-7"],
      ["test_case.state", "tc-3"],
    ]);
    expect(gelen[0].data).toMatchObject({ durum: "findings_open", ts: "2026-10-30T09:00:00Z" });
    // Gereksinim sayfası ["requirement.updated", …] ile abone: core olayı eşleşir, kimlik süzgeci de çalışır.
    const konular = new Set(["requirement.updated", "finding.updated"]);
    expect(olayEslesir(gelen[0], konular, "req-7")).toBe(true);
    expect(olayEslesir(gelen[0], konular, "req-8")).toBe(false);
    expect(olayEslesir(gelen[1], konular)).toBe(false);
    expect(olayEslesir(gelen[1], new Set(["case.updated"]))).toBe(true);
    y.durdur();
    vi.useRealTimers();
  });

  it("Demo-A ayrıntılı olayları dinlenir ve doğru konulara düşer", () => {
    for (const ad of ["finding.verified", "po.approved", "case.generated", "publish.started", "publish.progress", "publish.completed", "publish.failed"]) {
      expect(DINLENEN_OLAYLAR).toContain(ad);
    }
    const dogrulandi = olayiAyristir("finding.verified", JSON.stringify({ data: { id: "f-1", requirement_id: "req-1" }, ts: "t" }));
    expect(olayKonulari(dogrulandi)).toEqual(["finding.verified", "finding.updated", "requirement.updated"]);
    // Gereksinim ekranı kendi kimliğiyle abone: bulgunun gereksinim kimliği eşleşir, başkası eşleşmez.
    expect(olayEslesir(dogrulandi, new Set(["finding.updated"]), "req-1")).toBe(true);
    expect(olayEslesir(dogrulandi, new Set(["finding.updated"]), "req-2")).toBe(false);
    expect(olayKonulari({ type: "po.approved", id: "req-1", data: {} })).toEqual(["po.approved", "requirement.updated"]);
    expect(olayKonulari({ type: "case.generated", data: {} })).toEqual(["case.generated", "case.updated"]);
    expect(olayKonulari({ type: "publish.completed", data: {} })).toEqual(["publish.completed", "publish.updated", "case.updated", "requirement.updated"]);
  });

  it("review.recorded nesne kimliğiyle ve nesne türünün konusuyla eşleşir", () => {
    const o = olayiAyristir(
      "review.recorded",
      JSON.stringify({ data: { id: "rev-1", nesne_turu: "test_case", nesne_id: "tc-9", karar: "approve" }, ts: "t" }),
    );
    expect(o.id).toBe("tc-9");
    expect(o.data.id).toBe("rev-1");
    expect(olayKonulari(o)).toEqual(["review.recorded", "case.updated"]);
    expect(olayEslesir(o, new Set(["case.updated"]), "tc-9")).toBe(true);
  });

  it("karma modda gerçek SSE ile birlikte süreç içi (örnek veri) olayları da dinler", () => {
    SahteKaynak.hepsi = [];
    const y = new OlayYolu({ kaynakUret: (u) => new SahteKaynak(u), mockDa: true });
    const gelen: string[] = [];
    y.abone((o) => gelen.push(o.type));
    y.baslat();
    SahteKaynak.hepsi[0].ac();
    expect(y.durum).toBe("bagli");
    SahteKaynak.hepsi[0].gonder("script.state", { data: { id: "s1", durum: "pr_open" }, ts: "t" });
    mockOlayYayinla({ type: "agent.step", id: "scr-2", data: { sira: 1 } });
    expect(gelen).toEqual(["script.state", "agent.step"]);
    y.durdur();
    mockOlayYayinla({ type: "agent.step", id: "scr-2", data: { sira: 2 } });
    expect(gelen).toHaveLength(2);
  });
});

describe("OlayYolu session.ended", () => {
  beforeEach(() => {
    SahteKaynak.hepsi = [];
    vi.useFakeTimers();
  });
  afterEach(() => vi.useRealTimers());

  it("oturum bitince akışı kapatır, yeniden bağlanmaz ve giriş yoluna haber verir", () => {
    const oturumBitince = vi.fn();
    const y = new OlayYolu({ kaynakUret: (u) => new SahteKaynak(u), taban: 1000, azami: 8000, oturumBitince });
    const gelen: PortalOlayi[] = [];
    y.abone((o) => gelen.push(o));
    y.baslat();
    const k = SahteKaynak.hepsi[0];
    k.ac();
    k.gonder("session.ended", { reason: "revoked" });
    expect(oturumBitince).toHaveBeenCalledTimes(1);
    expect(k.kapandi).toBe(true);
    expect(y.durum).toBe("kapali");
    // Sunucu bağlantıyı kapatınca gelen hata yeni bağlantı planlamamalı.
    k.hata();
    vi.advanceTimersByTime(60_000);
    expect(SahteKaynak.hepsi).toHaveLength(1);
    expect(gelen).toEqual([]);
  });

  it("varsayılan olarak http'nin yetkisiz dinleyicisini çağırır", async () => {
    const http = await import("./http");
    const dinleyici = vi.fn();
    http.yetkisizOlunca(dinleyici);
    try {
      const y = new OlayYolu({ kaynakUret: (u) => new SahteKaynak(u) });
      y.baslat();
      SahteKaynak.hepsi[0].gonder("session.ended", {});
      expect(dinleyici).toHaveBeenCalledTimes(1);
    } finally {
      http.yetkisizOlunca(null);
    }
  });
});

describe("Demo-B core olay adları (codegen + ci şeritleri)", () => {
  const kok = resolve(__dirname, "../../..");
  const dosyalar = ["core/src/tp_core/features/codegen/service.py", "core/src/tp_core/features/ci/service.py"].map((d) => resolve(kok, d));

  it.skipIf(!dosyalar.every((d) => existsSync(d)))("core'un Demo-B'de yayımladığı her olay adı dinlenir ve script/koşu konusuna düşer", () => {
    const adlar = new Set<string>();
    for (const d of dosyalar) {
      const kaynak = readFileSync(d, "utf8");
      for (const m of kaynak.matchAll(/(?:_olay|publish_tx)\(\s*[\w.()]+,\s*"([a-z_]+\.[a-z_.]+)"/g)) adlar.add(m[1]);
    }
    expect(adlar.size).toBeGreaterThanOrEqual(4);
    for (const ad of adlar) {
      expect(DINLENEN_OLAYLAR, ad).toContain(ad);
      const konular = olayKonulari({ type: ad, data: {} });
      expect(konular.some((k) => k === "script.updated" || k === "ci.status"), `${ad} → ${konular.join(",")}`).toBe(true);
    }
  });

  it("agent.step core şekli (script_id, n, tool, summary, screenshot_url) script ekranına eşleşir", () => {
    const o = olayiAyristir("agent.step", JSON.stringify({ data: { script_id: "s-1", n: 3, tool: "browser_click", summary: "x" }, ts: "t" }));
    expect(olayEslesir(o, new Set(["agent.step"]), "s-1")).toBe(true);
    expect(olayEslesir(o, new Set(["agent.step"]), "s-2")).toBe(false);
    const ci = olayiAyristir("ci.status", JSON.stringify({ data: { id: "r-1", run_id: "r-1", script_id: "s-1", durum: "running" }, ts: "t" }));
    expect(olayEslesir(ci, new Set(["ci.status"]), "s-1")).toBe(true);
    expect(olayEslesir(ci, new Set(["ci.status"]), "r-1")).toBe(true);
  });
});

describe("asistan olayları (AI-ASISTAN-PLANI §9)", () => {
  it("assistant.step ve assistant.answered BILINEN_OLAYLAR'da; CORE_OLAYLARI değişmez", () => {
    expect(BILINEN_OLAYLAR).toContain("assistant.step");
    expect(BILINEN_OLAYLAR).toContain("assistant.answered");
    expect(DINLENEN_OLAYLAR).toContain("assistant.answered");
    expect(CORE_OLAYLARI as readonly string[]).not.toContain("assistant.step");
  });

  it("olayEslesir data.mesaj_id ile eşleşir (core zarfı, kimliksiz olay)", () => {
    const o = olayiAyristir("assistant.answered", JSON.stringify({ data: { mesaj_id: "m-1", kullanici_id: "u-1", durum: "done" }, ts: "t" }));
    expect(o.id).toBeUndefined();
    expect(olayEslesir(o, new Set(["assistant.answered"]), "m-1")).toBe(true);
    expect(olayEslesir(o, new Set(["assistant.answered"]), "m-2")).toBe(false);
    expect(olayEslesir(o, new Set(["assistant.step"]), "m-1")).toBe(false);
  });
});
