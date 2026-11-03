// Mock arka uç: asistan uçları, assistant.* olayları ve kodlu hatalar (AI-ASISTAN-PLANI §9, §13).
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { asistanApi } from "../asistan";
import { ApiError, mockUclari } from "../http";
import type { PortalOlayi } from "../types";
import { oturumAc } from "../../test/yardimci";
import { asistanMockAyarla, asistanMockIsle } from "./asistan";
import { mockOlaylaraAbone } from "./olaylar";

let olaylar: PortalOlayi[] = [];
let birak: () => void = () => undefined;

beforeEach(async () => {
  asistanMockAyarla({ otomatikIsle: false });
  olaylar = [];
  birak = mockOlaylaraAbone((o) => olaylar.push(o));
  await oturumAc("muhendis");
});
afterEach(() => birak());

async function kodu(p: Promise<unknown>): Promise<{ status: number; kod?: string }> {
  const e = await p.then(
    () => null,
    (x: unknown) => x,
  );
  expect(e).toBeInstanceOf(ApiError);
  return { status: (e as ApiError).status, kod: (e as ApiError).kod };
}

describe("asistan mock uçları", () => {
  it("status: etkin, mod, kalan soru; ÖRNEK VERİ paketi", async () => {
    const d = await asistanApi.durum();
    expect(d).toMatchObject({ etkin: true, mod: "live", kalan_soru: 30, paket_commit: "ornek-veri" });
  });

  it("sohbet oluştur → listede; sil → listeden kalkar, mesajları 404", async () => {
    const s = await asistanApi.sohbetOlustur(null);
    expect((await asistanApi.sohbetler()).map((x) => x.id)).toEqual([s.id]);
    await asistanApi.sohbetSil(s.id);
    expect(await asistanApi.sohbetler()).toEqual([]);
    expect(await kodu(asistanApi.mesajlar(s.id))).toEqual({ status: 404, kod: "bulunamadi" });
  });

  it("soru → 202 mesaj_id; olaylar mesaj_id + kullanici_id taşır; cevap ÖRNEK VERİ", async () => {
    const s = await asistanApi.sohbetOlustur(null);
    const { mesaj_id } = await asistanApi.soruGonder(s.id, { soru: "Kırarak doğrula neden gri?", baglam: { rota_kalibi: "/kod/:id" } });
    let liste = await asistanApi.mesajlar(s.id);
    expect(liste.map((m) => [m.rol, m.durum])).toEqual([
      ["user", "done"],
      ["assistant", "pending"],
    ]);
    asistanMockIsle(mesaj_id);
    const adimlar = olaylar.filter((o) => o.type === "assistant.step");
    expect(adimlar.length).toBeGreaterThanOrEqual(2);
    for (const o of olaylar) expect(o.data).toMatchObject({ mesaj_id, kullanici_id: "u-muhendis" });
    // Olay verisinde soru metni yok (yalnız sabit adım kodu).
    expect(JSON.stringify(olaylar)).not.toContain("Kırarak");
    expect(olaylar.at(-1)).toMatchObject({ type: "assistant.answered", data: { durum: "done" } });
    const m = await asistanApi.mesaj(mesaj_id);
    expect(m).toMatchObject({ durum: "done", kaynak: "model", amac: "assistant" });
    expect(m.cevap?.ornek_veri).toBe(true);
    expect(JSON.stringify(m.cevap?.cevap_bloklari)).toContain("ÖRNEK VERİ");
    liste = await asistanApi.mesajlar(s.id);
    expect(liste).toHaveLength(2);
    expect(mockUclari()).toContain("POST /assistant/conversations/:id/messages");
  });

  it("kodlu hatalar: bekleyen_var, sir_icerik, boyut, asistan_kapali, hiz_siniri, mesgul, butce_asildi, oneri_gecersiz", async () => {
    const s = await asistanApi.sohbetOlustur(null);
    await asistanApi.soruGonder(s.id, { soru: "Bugün ne yapmalıyım?" });
    expect(await kodu(asistanApi.soruGonder(s.id, { soru: "ikinci" }))).toEqual({ status: 409, kod: "bekleyen_var" });
    const sahteToken = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4";
    expect(await kodu(asistanApi.soruGonder(s.id, { soru: `bu ne ${sahteToken}` }))).toEqual({ status: 422, kod: "sir_icerik" });
    expect(await kodu(asistanApi.soruGonder(s.id, { soru: "x", baglam: { secili_eleman: { ad: sahteToken } } }))).toEqual({ status: 422, kod: "sir_icerik" });
    expect(await kodu(asistanApi.soruGonder(s.id, { soru: "a".repeat(2001) }))).toEqual({ status: 422, kod: "gecersiz_istek" });
    expect(await kodu(asistanApi.soruGonder(s.id, { soru: "x", baglam: { b: "y".repeat(3000) } }))).toEqual({ status: 422, kod: "gecersiz_istek" });

    const s2 = await asistanApi.sohbetOlustur(null);
    await oturumAc("testci");
    expect(await kodu(asistanApi.mesajlar(s2.id))).toEqual({ status: 404, kod: "bulunamadi" });
    asistanMockAyarla({ mesgul: true });
    const s3 = await asistanApi.sohbetOlustur(null);
    expect(await kodu(asistanApi.soruGonder(s3.id, { soru: "x" }))).toEqual({ status: 429, kod: "mesgul" });
    asistanMockAyarla({ mesgul: false, butceDoldu: true });
    expect(await kodu(asistanApi.soruGonder(s3.id, { soru: "x" }))).toEqual({ status: 402, kod: "butce_asildi" });
    asistanMockAyarla({ butceDoldu: false, kalanSoru: 0 });
    expect(await kodu(asistanApi.soruGonder(s3.id, { soru: "x" }))).toEqual({ status: 429, kod: "hiz_siniri" });
    asistanMockAyarla({ kalanSoru: 5, gecersizOneriler: ["r07"] });
    expect(await kodu(asistanApi.soruGonder(s3.id, { soru: "x", oneri_kural_id: "r07" }))).toEqual({ status: 409, kod: "oneri_gecersiz" });
    asistanMockAyarla({ etkin: false, neden: "worker_yok" });
    expect(await kodu(asistanApi.soruGonder(s3.id, { soru: "x" }))).toEqual({ status: 503, kod: "asistan_kapali" });
    expect(await asistanApi.durum()).toMatchObject({ etkin: false, neden: "worker_yok" });
  });

  it("iptal: pending → iptal (ücret yok); running → iptal (harcanan yazılır)", async () => {
    const s = await asistanApi.sohbetOlustur(null);
    const a = await asistanApi.soruGonder(s.id, { soru: "bir" });
    await asistanApi.iptal(a.mesaj_id);
    expect(await asistanApi.mesaj(a.mesaj_id)).toMatchObject({ durum: "iptal", maliyet_usd: null, basladi: false });
    const b = await asistanApi.soruGonder(s.id, { soru: "iki" });
    const { asistanMockBaslat } = await import("./asistan");
    asistanMockBaslat(b.mesaj_id);
    await asistanApi.iptal(b.mesaj_id);
    const m = await asistanApi.mesaj(b.mesaj_id);
    expect(m).toMatchObject({ durum: "iptal", basladi: true });
    expect(Number(m.maliyet_usd)).toBeGreaterThan(0);
    // İptal edilen mesaj sonradan işlenmez.
    asistanMockIsle(b.mesaj_id);
    expect((await asistanApi.mesaj(b.mesaj_id)).durum).toBe("iptal");
  });

  it("Daha ayrıntılı incele: ust_mesaj_id → assistant_deep çocuk; ikinci kez 409 zaten_derin; derin cevap yeniden incelenemez", async () => {
    const s = await asistanApi.sohbetOlustur(null);
    const a = await asistanApi.soruGonder(s.id, { soru: "Kırarak doğrula neden gri?" });
    asistanMockIsle(a.mesaj_id);
    const d = await asistanApi.derinIncele(s.id, a.mesaj_id);
    expect(await kodu(asistanApi.derinIncele(s.id, a.mesaj_id))).toEqual({ status: 409, kod: "zaten_derin" });
    asistanMockIsle(d.mesaj_id);
    const m = await asistanApi.mesaj(d.mesaj_id);
    expect(m).toMatchObject({ amac: "assistant_deep", ust_mesaj_id: a.mesaj_id, tetik: "kullanici", durum: "done" });
    expect(m.icerik).toBe("Kırarak doğrula neden gri?");
    expect(await kodu(asistanApi.derinIncele(s.id, d.mesaj_id))).toEqual({ status: 422, kod: "gecersiz_istek" });
  });

  it("otomatik yükseltme: 'Emin değil' → tetik=otomatik çocuk; kullanıcı yeni soru sorabilir", async () => {
    const s = await asistanApi.sohbetOlustur(null);
    const a = await asistanApi.soruGonder(s.id, { soru: "Bundan emin değilim, neden böyle?" });
    asistanMockIsle(a.mesaj_id);
    expect(olaylar.find((o) => o.type === "assistant.answered")?.data.derin_bekliyor).toBe(true);
    const liste = await asistanApi.mesajlar(s.id);
    const cocuk = liste.find((m) => m.ust_mesaj_id === a.mesaj_id)!;
    expect(cocuk).toMatchObject({ tetik: "otomatik", amac: "assistant_deep", durum: "pending" });
    await expect(asistanApi.soruGonder(s.id, { soru: "Başka bir soru" })).resolves.toHaveProperty("mesaj_id");
  });

  it("modelsiz dallar: sözlük (son hata), şablon (anahtar), kapalı kip", async () => {
    const s = await asistanApi.sohbetOlustur(null);
    const a = await asistanApi.soruGonder(s.id, { soru: "Az önceki hata ne demek?", baglam: { son_hata: { gorunen_metin: "İçerik değişti" } } });
    asistanMockIsle(a.mesaj_id);
    expect((await asistanApi.mesaj(a.mesaj_id)).kaynak).toBe("sozluk");
    const b = await asistanApi.soruGonder(s.id, { soru: "TPD-3 neden bekliyor?" });
    asistanMockIsle(b.mesaj_id);
    const mb = await asistanApi.mesaj(b.mesaj_id);
    expect(mb.kaynak).toBe("sablon");
    expect(mb.cevap?.jira_baglantilari?.[0]?.anahtar).toBe("TPD-3");
    asistanMockAyarla({ mod: "off" });
    const c = await asistanApi.soruGonder(s.id, { soru: "Kampanya indirimi nasıl hesaplanıyor?" });
    asistanMockIsle(c.mesaj_id);
    expect(await asistanApi.mesaj(c.mesaj_id)).toMatchObject({ kaynak: "kapali", amac: null });
  });

  it("geri bildirim: -1/1 kabul; geçersiz değer 422", async () => {
    const s = await asistanApi.sohbetOlustur(null);
    const a = await asistanApi.soruGonder(s.id, { soru: "Bugün ne yapmalıyım?" });
    asistanMockIsle(a.mesaj_id);
    await asistanApi.geriBildirim(a.mesaj_id, -1);
    expect((await asistanApi.mesaj(a.mesaj_id)).geri_bildirim).toBe(-1);
    expect(await kodu(asistanApi.geriBildirim(a.mesaj_id, 0 as unknown as 1))).toEqual({ status: 422, kod: "gecersiz_istek" });
  });
});
