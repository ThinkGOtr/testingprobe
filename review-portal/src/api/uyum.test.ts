import { describe, expect, it } from "vitest";
import { denetimiUyarla, ozetMetni } from "./uyum";

const coreYaniti = {
  events: [
    {
      id: 3,
      zaman: "2026-10-30T18:47:11.790477Z",
      aktor: "analist",
      eylem: "auth.login",
      nesne: "app_user:1",
      ozet: {},
      prev_hash: "a".repeat(64),
      hash: "b".repeat(64),
    },
    {
      id: 2,
      zaman: "2026-10-30T18:45:14.506111Z",
      aktor: "system",
      eylem: "seed.applied",
      nesne: null,
      ozet: { yeni: 0 },
      prev_hash: "c".repeat(64),
      hash: "a".repeat(64),
    },
  ],
  tip_hash: "b".repeat(64),
  next_before_id: null,
  verify: { ok: true, count: 3, tip_hash: "b".repeat(64), broken_at: null, reason: null },
};

describe("denetimiUyarla", () => {
  it("core-api şeklini portal şekline çevirir", () => {
    const sabit = new Date("2026-10-30T19:00:00Z");
    const r = denetimiUyarla(coreYaniti, () => sabit);
    expect(r.olaylar).toHaveLength(2);
    expect(r.olaylar[0]).toMatchObject({ id: "3", sira: 3, aktor: "analist", nesne: "app_user:1", ozet: "" });
    expect(r.olaylar[1]).toMatchObject({ id: "2", nesne: "", ozet: '{"yeni":0}' });
    expect(r.dogrulama).toEqual({
      gecerli: true,
      kontrol_edilen: 3,
      ilk_kirik_id: null,
      son_hash: "b".repeat(64),
      zaman: sabit.toISOString(),
    });
  });

  it("kırık zinciri ilk kırık kimlikle bildirir", () => {
    const r = denetimiUyarla({ ...coreYaniti, verify: { ok: false, count: 2, tip_hash: "x", broken_at: 2, reason: "hash" } });
    expect(r.dogrulama).toMatchObject({ gecerli: false, ilk_kirik_id: "2" });
  });

  it("doğrulama istenmediyse dogrulama null olur", () => {
    expect(denetimiUyarla({ ...coreYaniti, verify: null }).dogrulama).toBeNull();
  });

  it("mock (portal) şeklini olduğu gibi geçirir", () => {
    const portal = { olaylar: [], dogrulama: null };
    expect(denetimiUyarla(portal)).toBe(portal);
  });

  it("tanınmayan gövdede hata verir", () => {
    expect(() => denetimiUyarla({ detail: "x" })).toThrow();
  });

  it("ozetMetni: metin, boş nesne ve null", () => {
    expect(ozetMetni("hazır")).toBe("hazır");
    expect(ozetMetni({})).toBe("");
    expect(ozetMetni(null)).toBe("");
    expect(ozetMetni([1, 2])).toBe("[1,2]");
  });
});
