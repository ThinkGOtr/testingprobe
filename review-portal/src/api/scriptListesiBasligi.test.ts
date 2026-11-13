// MİM-D5 (011 tur 3): `GET /scripts` düz dizi + liste sınırı yanıt başlığı. Başlık varsa o, yoksa ≥200 kuralı.
import { afterEach, describe, expect, it, vi } from "vitest";
import { sahteSunucu } from "../test/sahteSunucu";
import { api } from "./client";
import { dahaFazlaBasligiOku, SCRIPT_DAHA_FAZLA_BASLIGI, SCRIPT_LISTE_SINIRI, scriptListesiUyarla } from "./uyumDemoB";

const n = (k: number) => Array.from({ length: k }, (_, i) => ({ id: `s${i}`, case_ids: [], durum: "merged" }));

afterEach(() => vi.unstubAllGlobals());

describe("GET /scripts liste sınırı başlığı", () => {
  it("başlık değerleri; tanınmayan değer yok sayılır", () => {
    const h = (v?: string) => new Headers(v === undefined ? {} : { [SCRIPT_DAHA_FAZLA_BASLIGI]: v });
    expect(dahaFazlaBasligiOku(h("1"))).toBe(true);
    expect(dahaFazlaBasligiOku(h("true"))).toBe(true);
    expect(dahaFazlaBasligiOku(h("0"))).toBe(false);
    expect(dahaFazlaBasligiOku(h("evet"))).toBeNull();
    expect(dahaFazlaBasligiOku(h())).toBeNull();
  });

  it("uyarlayıcı: başlık bilgisi uzunluk kuralının önüne geçer", () => {
    expect(scriptListesiUyarla(n(3), true).sinira_ulasti).toBe(true);
    expect(scriptListesiUyarla(n(SCRIPT_LISTE_SINIRI), false).sinira_ulasti).toBe(false);
    expect(scriptListesiUyarla(n(SCRIPT_LISTE_SINIRI), null).sinira_ulasti).toBe(true);
  });

  it("istemci: core başlığı okunur; başlık yoksa ≥200 kuralı", async () => {
    sahteSunucu({ "GET /scripts": { govde: n(SCRIPT_LISTE_SINIRI), basliklar: { [SCRIPT_DAHA_FAZLA_BASLIGI]: "1" } } });
    expect((await api.scriptListesi()).sinira_ulasti).toBe(true);
    // Tam 200 kayıt ama core "fazlası yok" diyor (limit+1 ile ölçtü): eksik sayılmaz.
    sahteSunucu({ "GET /scripts": { govde: n(SCRIPT_LISTE_SINIRI), basliklar: { [SCRIPT_DAHA_FAZLA_BASLIGI]: "0" } } });
    expect((await api.scriptListesi()).sinira_ulasti).toBe(false);
    // Eski core: başlık yok → uzunluk kuralı.
    sahteSunucu({ "GET /scripts": { govde: n(SCRIPT_LISTE_SINIRI) } });
    expect((await api.scriptListesi()).sinira_ulasti).toBe(true);
    sahteSunucu({ "GET /scripts": { govde: n(5) } });
    expect((await api.scriptListesi()).sinira_ulasti).toBe(false);
  });
});
