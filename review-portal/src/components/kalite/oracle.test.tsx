// 012 Ş7 — case review: beklenen sonuç kontrolü çipi, §4.3 kapı matrisi (ekran tarafı), istisna akışı,
// düzeltme ön kontrolü, sunucu kapı hataları ve "Beklenti doğruluğu" metriği.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../../App";
import { api } from "../../api/client";
import { ApiError } from "../../api/http";
import { bekleyenMockIs, mockVerisi } from "../../api/mock/handlers";
import type { CaseOracle, KararTablosu, TestCase } from "../../api/types";
import { OturumProvider } from "../../auth";
import { oturumAc } from "../../test/yardimci";
import { BildirimProvider } from "../Bildirim";
import { goruntulenenleriSifirla } from "../CaseKarti";
import {
  ENGEL_KONTROLSUZ,
  ENGEL_SURUYOR,
  ENGEL_UYUMSUZ,
  gerekceSorunu,
  ON_KONTROL,
  oracleCipMetni,
  oracleGorunumu,
  oracleHatasindaYenile,
  oracleKapisi,
  UYARI_KISMEN,
  UYARI_KONTROL_EDILEMEDI,
  UYARI_UYUMSUZ,
} from "./oracle";

const REQ = "req-tpd-1";
const C6 = "case-1-7"; // yüksek riskli sınır case'i (toplam 750,00 TL), AC3
const C6_BASLIK = /minimum tutara eşit toplamda/;

function uygulama(yol: string) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          <Rotalar />
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}
const isBitsin = async () => {
  await waitFor(() => expect(bekleyenMockIs()).toBe(0), { timeout: 3000 });
};
/** Minimum sipariş taslağını (sınır `toplam > 750`) PO'ya onaylatır: C6 yüksek riskli uyuşmazlık olur. */
async function minSiparisOnayla(bekle = true) {
  await oturumAc("analist");
  const t = (await api.kararTablolari(REQ)).tablolar.find((x) => /Minimum/.test(x.icerik.ad))!;
  await api.kararTablosuGecis(t.id, "submit", { icerik_hash: t.icerik_hash });
  await oturumAc("po");
  await api.kararTablosuGecis(t.id, "approve", { icerik_hash: t.icerik_hash });
  if (bekle) await isBitsin();
  await oturumAc("analist");
}
const kart = async (ad: RegExp) => screen.findByRole("article", { name: ad });

beforeEach(() => {
  goruntulenenleriSifirla();
  ON_KONTROL.araMs = 20;
  ON_KONTROL.zamanAsimiMs = 2000;
});
afterEach(() => {
  ON_KONTROL.araMs = 1000;
  ON_KONTROL.zamanAsimiMs = 20000;
});

// ------------------------------------------------------------------ saf kapı matrisi
const tablo = (ac: string[], ek: Partial<KararTablosu> = {}) => ({ durum: "approved", bayat: false, icerik: { ac_refs: ac } }) as unknown as KararTablosu & typeof ek;
const oracle = (sonuc: CaseOracle["sonuc"], ek: Partial<CaseOracle> = {}): CaseOracle => ({
  sonuc,
  ozet: "",
  karsilastirmalar: [],
  karsilastirilamayan: [],
  istisna: null,
  icerik_hash: "h",
  kontrol_suruyor: false,
  ...ek,
});
const tc = (risk: "high" | "medium" | "low", o: CaseOracle | null | undefined) =>
  ({ oracle: o, icerik: { risk, acceptance_criteria_refs: ["AC3"] } }) as unknown as Pick<TestCase, "oracle" | "icerik">;
const ISTISNA = { gerekce: "PO ile görüşüldü, sınır dahil.", veren: "analist", zaman: null };

describe("onay kapısı matrisi (ANALIZ §4.3 + §13 K10, K11, V11)", () => {
  const kapsayan = [tablo(["AC3"])];
  const KAPI_YOK = { engel: null, uyari: null, istisnaGerekli: false, istisnaTuru: null, suruyor: false };
  it.each([
    // [risk, oracle, tablolar, beklenen kapı]
    ["high", oracle("uyumlu"), kapsayan, { ...KAPI_YOK, gorunum: "uyumlu" }],
    ["low", oracle("uyumlu"), kapsayan, { ...KAPI_YOK, gorunum: "uyumlu" }],
    ["high", oracle("kapsam_disi"), [], { ...KAPI_YOK, gorunum: "tablo_yok" }],
    ["high", oracle("uyumsuz"), kapsayan, { ...KAPI_YOK, gorunum: "uyumsuz", engel: ENGEL_UYUMSUZ, istisnaGerekli: true, istisnaTuru: "uyumsuz" }],
    ["medium", oracle("uyumsuz"), kapsayan, { ...KAPI_YOK, gorunum: "uyumsuz", uyari: UYARI_UYUMSUZ }],
    ["low", oracle("uyumsuz"), kapsayan, { ...KAPI_YOK, gorunum: "uyumsuz", uyari: UYARI_UYUMSUZ }],
    // S1: aynı içerik için saklı istisna kapıyı açmaz (çekirdek gerekçeyi yeniden ister).
    ["high", oracle("uyumsuz", { istisna: ISTISNA }), kapsayan, { ...KAPI_YOK, gorunum: "uyumsuz", engel: ENGEL_UYUMSUZ, istisnaGerekli: true, istisnaTuru: "uyumsuz" }],
    // K11: kısmen uyumlu her riskte uyarı, engel yok.
    ["high", oracle("kismen"), kapsayan, { ...KAPI_YOK, gorunum: "kismen", uyari: UYARI_KISMEN }],
    ["low", oracle("kismen"), kapsayan, { ...KAPI_YOK, gorunum: "kismen", uyari: UYARI_KISMEN }],
    // K10: yüksek riskte kontrol edilemedi → gerekçeli onay (tür kontrolsuz); orta/düşükte uyarı.
    ["high", oracle("kontrol_edilemedi"), kapsayan, { ...KAPI_YOK, gorunum: "kontrol_edilemedi", engel: ENGEL_KONTROLSUZ, istisnaGerekli: true, istisnaTuru: "kontrolsuz" }],
    ["medium", oracle("kontrol_edilemedi"), kapsayan, { ...KAPI_YOK, gorunum: "kontrol_edilemedi", uyari: UYARI_KONTROL_EDILEMEDI }],
    ["high", oracle(null, { kontrol_suruyor: true }), kapsayan, { ...KAPI_YOK, gorunum: "suruyor", engel: ENGEL_SURUYOR, suruyor: true }],
    ["medium", oracle(null, { kontrol_suruyor: true }), kapsayan, { ...KAPI_YOK, gorunum: "suruyor", suruyor: true }],
    // Kayıt yok ama kapsayan onaylı tablo var: "sürüyor" görünür ama ekranın tahmini onayı kapatmaz (onyüz 2).
    ["high", null, kapsayan, { ...KAPI_YOK, gorunum: "suruyor", suruyor: true }],
    // Eski "kapsam dışı" kaydı + sonradan onaylanan tablo: yine sürüyor, engel yalnız sunucu söylerse.
    ["high", oracle("kapsam_disi"), kapsayan, { ...KAPI_YOK, gorunum: "suruyor", suruyor: true }],
    ["high", null, [], { ...KAPI_YOK, gorunum: "tablo_yok" }],
    // Bayat ya da onaysız tablo kapsamaz.
    ["high", null, [{ ...tablo(["AC3"]), bayat: true }], { ...KAPI_YOK, gorunum: "tablo_yok" }],
    ["high", null, [{ ...tablo(["AC3"]), durum: "draft" }], { ...KAPI_YOK, gorunum: "tablo_yok" }],
    // Çekirdek alanı ve tablo listesini sunmuyor: çip yok, kapı sunucuda.
    ["high", undefined, null, { ...KAPI_YOK, gorunum: null }],
  ] as const)("risk %s · %j", (risk, o, tablolar, beklenen) => {
    const d = oracleKapisi(tc(risk, o as CaseOracle | null | undefined), tablolar as unknown as KararTablosu[] | null);
    expect(d).toEqual(beklenen);
  });

  it("V11: risk düşürülmüş case'te AI özgün içeriği yüksek riskliyse kapı yine kapanır", () => {
    const t = { ...tc("medium", oracle("uyumsuz")), ai_icerik: { risk: "high" } } as unknown as Pick<TestCase, "oracle" | "icerik">;
    expect(oracleKapisi(t, kapsayan)).toMatchObject({ engel: ENGEL_UYUMSUZ, istisnaTuru: "uyumsuz" });
  });

  it("çip metni: kısmen uyumluda kontrol edilemeyen değer sayısı (degerler varsa oradan), model hatasında neden", () => {
    expect(oracleCipMetni("kismen", oracle("kismen", { degerler: { uyumlu: 3, uyumsuz: 0, karsilastirilamayan: 1, atilan: 1 } }))).toBe(
      "Kısmen uyumlu — 2 değer kontrol edilemedi",
    );
    expect(oracleCipMetni("kismen", oracle("kismen"))).toBe("Kısmen uyumlu");
    expect(oracleCipMetni("kontrol_edilemedi", oracle("kontrol_edilemedi", { neden: "cagri_hatasi" }))).toBe("Kontrol yapılamadı (model hatası)");
    expect(oracleCipMetni("kontrol_edilemedi", oracle("kontrol_edilemedi", { neden: "bilinmeyen" }))).toBe("Kontrol edilemedi");
  });

  it("gerekçe kuralı (§13.2): ≥ 20 karakter ve ≥ 10 harf", () => {
    expect(gerekceSorunu("kısa")).toMatch(/en az 20 karakter/);
    expect(gerekceSorunu("1234567890 12345 !!! ...")).toMatch(/en az 10 harf/);
    expect(gerekceSorunu("Değerler elle ölçüldü, uyumlu.")).toBeNull();
  });

  it("görünüm: bilinmeyen tablo listesinde kayıt varsa sonucu, 'kapsam dışı' kaydında 'Tablo yok' der", () => {
    expect(oracleGorunumu(tc("high", oracle("uyumlu")), null)).toBe("uyumlu");
    expect(oracleGorunumu(tc("high", oracle("kapsam_disi")), null)).toBe("tablo_yok");
    expect(oracleGorunumu(tc("high", null), null)).toBeNull();
  });

  it("sunucu kapı hatasında (422 oracle_uyumsuz / 409 oracle_bekleniyor) liste yenilenir, hata yine fırlar", async () => {
    const yenile = vi.fn();
    const e422 = new ApiError(422, "uyuşmuyor", { kod: "oracle_uyumsuz" });
    await expect(oracleHatasindaYenile(() => Promise.reject(e422), yenile)()).rejects.toBe(e422);
    const e409 = new ApiError(409, "bekleniyor", { kod: "oracle_bekleniyor" });
    await expect(oracleHatasindaYenile(() => Promise.reject(e409), yenile)()).rejects.toBe(e409);
    await expect(oracleHatasindaYenile(() => Promise.reject(new ApiError(500, "x")), yenile)()).rejects.toBeInstanceOf(ApiError);
    expect(yenile).toHaveBeenCalledTimes(2);
  });
});

// ------------------------------------------------------------------ case review ekranı
describe("case review: kontrol çipi, karşılaştırma ve metrik", () => {
  it("başlangıç: uyumlu, kontrol edilemedi ve tablo yok çipleri; karşılaştırma tablosu ve tabloya bağlantı", async () => {
    await oturumAc("analist");
    uygulama(`/gereksinimler/${REQ}/caseler`);
    const c2 = await kart(/^7 adet kampanyalı/);
    expect(await within(c2).findByText("Tabloyla uyumlu ✓")).toBeInTheDocument();
    const ayrinti = within(c2).getByTestId("oracle-ayrinti");
    await userEvent.click(within(ayrinti).getByText(/^Tablo karşılaştırması/, { selector: "summary" }));
    const tablo = within(ayrinti).getByRole("region", { name: /Tablo karşılaştırması/ });
    expect(within(tablo).getAllByRole("row").length).toBeGreaterThan(2);
    expect(within(tablo).getAllByText("Aynı ✓").length).toBeGreaterThan(0);
    expect(within(ayrinti).getByRole("link", { name: "Karar tablolarını aç" })).toHaveAttribute("href", `/gereksinimler/${REQ}/karar-tablolari#tablo-kt-1`);
    expect(within(await kart(C6_BASLIK)).getByText("Tablo yok")).toBeInTheDocument();
    // AC6 case'i (C9) yalnız T2 kapsar; T2 başlangıçta taslak → "Tablo yok". Başlangıçta kontrol edilemeyen case yok.
    const cipler = (await screen.findAllByTestId("oracle-cip")).map((x) => x.textContent);
    expect(cipler).not.toContain("Kontrol edilemedi");
    expect(within(await kart(/^Kampanyalı siparişte minimum/)).getByText("Tablo yok")).toBeInTheDocument();
    // Uyumlu / tablo yok case'lerinde onay açık.
    expect(within(await kart(C6_BASLIK)).getByRole("button", { name: "Onayla" })).toBeEnabled();
    // Özet kartı: beklenti doğruluğu (4 uyumlu / 0 uyuşmaz).
    expect(await screen.findByTestId("beklenti-dogrulugu")).toHaveTextContent("%100");
    // Başlıktan karar tablolarına bağlantı (Yayın önizleme yerinde kalır).
    expect(screen.getByRole("link", { name: "Karar tabloları" })).toHaveAttribute("href", `/gereksinimler/${REQ}/karar-tablolari`);
    expect(screen.getByRole("link", { name: "Yayın önizleme" })).toBeInTheDocument();
  });

  it("beklenti doğruluğu ölçülmeyen gereksinimde 'ölçülmedi'", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler/req-tpd-3/caseler");
    await waitFor(() => expect(screen.getByTestId("beklenti-dogrulugu")).toHaveTextContent("ölçülmedi"));
  });

  it("kontrol sürerken yüksek riskli case: 'Kontrol sürüyor' ve Onayla pasif, nedeni görünür", async () => {
    await minSiparisOnayla(false);
    uygulama(`/gereksinimler/${REQ}/caseler`);
    const c = await kart(C6_BASLIK);
    expect(await within(c).findByText("Kontrol sürüyor")).toBeInTheDocument();
    expect(within(c).getByRole("button", { name: "Onayla" })).toBeDisabled();
    expect(within(c).getByText(ENGEL_SURUYOR)).toHaveClass("dugme-neden");
    // Onyüz 2: sunucu "sürüyor" dedikçe analist kontrolü yeniden isteyebilir (kalıcı kilit yok).
    expect(within(c).getAllByRole("button", { name: "Kontrolü yeniden iste" }).length).toBeGreaterThan(0);
    await isBitsin();
  });
});

describe("yüksek riskli uyuşmazlık: kapı ve istisna", () => {
  it("Onayla pasif + görünür neden; 'Case doğru, istisnayla onayla' formu odak alır, kısa gerekçeyi reddeder, geçerli gerekçeyle onaylar", async () => {
    await minSiparisOnayla();
    uygulama(`/gereksinimler/${REQ}/caseler`);
    const c = await kart(C6_BASLIK);
    expect(await within(c).findByText("Tabloyla uyuşmuyor ✗")).toBeInTheDocument();
    const onayla = within(c).getByRole("button", { name: "Onayla" });
    expect(onayla).toBeDisabled();
    expect(within(c).getByText(ENGEL_UYUMSUZ)).toHaveClass("dugme-neden");
    // Karşılaştırma uyuşmazlıkta açık gelir; farklı satır işaretli.
    expect(within(c).getByTestId("oracle-ayrinti")).toHaveAttribute("open");
    expect(within(c).getAllByText("Farklı ✗").length).toBeGreaterThan(0);

    // V10: iki yol — "Case doğru, istisnayla onayla" ve "Tablo yanlış → tabloyu yeniden aç".
    expect(within(c).getByTestId("oracle-tablo-yanlis")).toBeInTheDocument();
    await userEvent.click(within(c).getByRole("button", { name: "Case doğru, istisnayla onayla" }));
    const form = within(c).getByTestId("istisna-formu");
    const alan = within(form).getByLabelText("İstisna gerekçesi");
    await waitFor(() => expect(alan).toHaveFocus());
    await userEvent.type(alan, "kısa");
    await userEvent.click(within(form).getByRole("button", { name: "Case doğru, istisnayla onayla" }));
    expect(within(form).getByRole("alert")).toHaveTextContent("en az 20 karakter");
    expect(alan).toHaveFocus();
    await userEvent.clear(alan);
    // §13.2: 20 karakter yetmez, en az 10 harf.
    await userEvent.type(alan, "1234567890 1234567890 !!");
    await userEvent.click(within(form).getByRole("button", { name: "Case doğru, istisnayla onayla" }));
    expect(within(form).getByRole("alert")).toHaveTextContent("en az 10 harf");
    await userEvent.clear(alan);
    await userEvent.type(alan, "kısa — PO ile görüşüldü, sınır dahil kabul edildi");
    const kararSpy = vi.spyOn(api, "caseKarari");
    await userEvent.click(within(form).getByRole("button", { name: "Case doğru, istisnayla onayla" }));
    await waitFor(() => expect(mockVerisi().caseler.find((x) => x.id === C6)!.durum).toBe("approved"));
    expect(kararSpy).toHaveBeenCalledWith(C6, expect.objectContaining({ karar: "approve", oracle_istisna_turu: "uyumsuz" }));
    const sonra = await kart(C6_BASLIK);
    expect(await within(sonra).findByTestId("oracle-istisna")).toHaveTextContent("PO ile görüşüldü");
    expect(mockVerisi().denetim.at(-1)).toMatchObject({ eylem: "oracle.exception", nesne: C6 });
  });

  it("istisna formu Vazgeç ile kapanır, odak açan düğmeye döner", async () => {
    await minSiparisOnayla();
    uygulama(`/gereksinimler/${REQ}/caseler`);
    const c = await kart(C6_BASLIK);
    const ac = await within(c).findByRole("button", { name: "Case doğru, istisnayla onayla" });
    await userEvent.click(ac);
    await userEvent.click(within(c).getByRole("button", { name: "Vazgeç" }));
    expect(within(c).queryByTestId("istisna-formu")).toBeNull();
    await waitFor(() => expect(within(c).getByRole("button", { name: "Case doğru, istisnayla onayla" })).toHaveFocus());
  });

  it("V10 'Tablo yanlış': kapsayan tablo yeniden açılır (taslağa döner), case onaylanmaz", async () => {
    await minSiparisOnayla();
    uygulama(`/gereksinimler/${REQ}/caseler`);
    const c = await kart(C6_BASLIK);
    const yol = await within(c).findByTestId("oracle-tablo-yanlis");
    await userEvent.click(within(yol).getByRole("button", { name: "Tablo yanlış → tabloyu yeniden aç" }));
    expect(await within(yol).findByRole("status")).toHaveTextContent("Tablo taslağa döndü");
    expect(within(yol).getByRole("link", { name: /Tabloyu düzeltin/ })).toHaveAttribute("href", expect.stringContaining("karar-tablolari#tablo-"));
    const t2 = (await api.kararTablolari(REQ)).tablolar.find((x) => /Minimum/.test(x.icerik.ad))!;
    expect(t2.durum).toBe("draft");
    expect(mockVerisi().caseler.find((x) => x.id === C6)!.durum).toBe("draft");
  });

  it("S1: saklı istisna aynı içerikte kapıyı açmaz — yeniden açılan case'te gerekçe yeniden istenir", async () => {
    await minSiparisOnayla();
    const c6 = (await api.caseler(REQ)).find((x) => x.id === C6)!;
    const onayli = await api.caseKarari(C6, { icerik_hash: c6.icerik_hash, karar: "approve", oracle_istisna_gerekce: "PO ile görüşüldü, sınır dahil kabul." });
    await api.caseYenidenAc(onayli);
    uygulama(`/gereksinimler/${REQ}/caseler`);
    const c = await kart(C6_BASLIK);
    expect(await within(c).findByTestId("oracle-istisna")).toHaveTextContent("Saklı gerekçe onayı açmaz");
    expect(within(c).getByRole("button", { name: "Onayla" })).toBeDisabled();
    expect(within(c).getByRole("button", { name: "Case doğru, istisnayla onayla" })).toBeInTheDocument();
  });

  it("orta riskli uyuşmazlık: Onayla açık, uyarı görünür; onay uyarı kaydıyla geçer", async () => {
    await minSiparisOnayla();
    const c6 = mockVerisi().caseler.find((x) => x.id === C6)!;
    c6.icerik = { ...c6.icerik, risk: "medium" };
    c6.icerik_hash = (await api.caseOracleKontrol(C6, c6.icerik)).icerik_hash!;
    await isBitsin();
    uygulama(`/gereksinimler/${REQ}/caseler`);
    const c = await kart(C6_BASLIK);
    expect(await within(c).findByTestId("oracle-uyari")).toHaveTextContent(UYARI_UYUMSUZ);
    const onayla = within(c).getByRole("button", { name: "Onayla" });
    expect(onayla).toBeEnabled();
    expect(within(c).queryByRole("button", { name: "İstisnayla onayla" })).toBeNull();
    await userEvent.click(onayla);
    await waitFor(() => expect(mockVerisi().caseler.find((x) => x.id === C6)!.durum).toBe("approved"));
    expect(mockVerisi().denetim.at(-1)).toMatchObject({ eylem: "oracle.warning" });
  });

  it("K10 kontrol edilemeyen yüksek riskli case: Onayla pasif; 'Kontrol edilemedi, yine de onayla' gerekçe formu (tür kontrolsuz)", async () => {
    await minSiparisOnayla();
    const c9 = mockVerisi().caseler.find((x) => x.id === "case-1-9")!;
    // Kampanya bilgisi metinden çıkınca T2'nin ilk koşulu (kampanyali_sepet) karar veremez.
    c9.icerik = { ...c9.icerik, risk: "high", preconditions: ["Sepet boş"], expected_result: "Toplam 150,00 TL olsa da minimum sipariş uyarısı gösterilmez" };
    c9.icerik_hash = (await api.caseOracleKontrol(c9.id, c9.icerik)).icerik_hash!;
    await isBitsin();
    uygulama(`/gereksinimler/${REQ}/caseler`);
    const c = await kart(new RegExp(c9.icerik.title.slice(0, 20)));
    expect(await within(c).findByText("Kontrol edilemedi")).toBeInTheDocument();
    expect(within(c).getByRole("button", { name: "Onayla" })).toBeDisabled();
    expect(within(c).getByText(ENGEL_KONTROLSUZ)).toHaveClass("dugme-neden");
    expect(within(c).getByTestId("oracle-kapi")).toHaveAttribute("data-tur", "kontrolsuz");
    await userEvent.click(within(c).getByRole("button", { name: "Kontrol edilemedi, yine de onayla" }));
    const form = within(c).getByTestId("istisna-formu");
    await userEvent.type(within(form).getByLabelText("Neden kontrolsüz onaylıyorsunuz?"), "Uyarının görünmediği elle doğrulandı.");
    const kararSpy = vi.spyOn(api, "caseKarari");
    await userEvent.click(within(form).getByRole("button", { name: "Kontrol edilemedi, yine de onayla" }));
    await waitFor(() => expect(mockVerisi().caseler.find((x) => x.id === c9.id)!.durum).toBe("approved"));
    expect(kararSpy).toHaveBeenCalledWith(c9.id, expect.objectContaining({ oracle_istisna_gerekce: "Uyarının görünmediği elle doğrulandı.", oracle_istisna_turu: "kontrolsuz" }));
  });

  it("kontrol edilemeyen orta riskli case: Onayla açık, 'Kontrol edilemedi' uyarısı", async () => {
    await minSiparisOnayla();
    const c9 = mockVerisi().caseler.find((x) => x.id === "case-1-9")!;
    c9.icerik = { ...c9.icerik, risk: "medium", preconditions: ["Sepet boş"], expected_result: "Toplam 150,00 TL olsa da minimum sipariş uyarısı gösterilmez" };
    c9.icerik_hash = (await api.caseOracleKontrol(c9.id, c9.icerik)).icerik_hash!;
    await isBitsin();
    uygulama(`/gereksinimler/${REQ}/caseler`);
    const c = await kart(new RegExp(c9.icerik.title.slice(0, 20)));
    expect(await within(c).findByTestId("oracle-uyari")).toHaveTextContent(UYARI_KONTROL_EDILEMEDI);
    expect(within(c).getByRole("button", { name: "Onayla" })).toBeEnabled();
  });

  it("ekran eski sonucu gösterirken sunucu 422 oracle_uyumsuz verirse hata görünür ve liste yenilenir", async () => {
    await oturumAc("analist");
    uygulama(`/gereksinimler/${REQ}/caseler`);
    const c = await kart(C6_BASLIK);
    await within(c).findByText("Tablo yok");
    // Ekran açıkken tablo arka planda onaylandı ve kontrol bitti (olay kaçmış gibi): ekran hâlâ "Tablo yok".
    const caselerSpy = vi.spyOn(api, "caseler");
    await minSiparisOnayla();
    await oturumAc("analist");
    await userEvent.click(within(c).getByRole("button", { name: "Onayla" }));
    expect((await within(c).findAllByText(/gerekçeli istisna olmadan onaylanamaz/)).length).toBeGreaterThan(0);
    await waitFor(() => expect(caselerSpy).toHaveBeenCalled());
    expect(await within(await kart(C6_BASLIK)).findByText("Tabloyla uyuşmuyor ✗")).toBeInTheDocument();
    expect(mockVerisi().caseler.find((x) => x.id === C6)!.durum).toBe("draft");
  });
});

describe("düzeltme formu: önerilen içerik ön kontrolü", () => {
  async function duzenle() {
    await minSiparisOnayla();
    uygulama(`/gereksinimler/${REQ}/caseler`);
    const c = await kart(C6_BASLIK);
    await within(c).findByText("Tabloyla uyuşmuyor ✗");
    await userEvent.click(within(c).getByRole("button", { name: "Düzelt" }));
    return c;
  }
  async function anlamYanitla(c: HTMLElement) {
    const soru = within(c).queryByTestId("beklenen-anlam");
    if (soru) await userEvent.click(within(soru).getByLabelText("Evet, anlam değişti"));
  }

  it("değer tabloya getirilince kontrol beklenir ('Beklenen sonuç kontrol ediliyor…'), sonra onaylanır", async () => {
    const c = await duzenle();
    const kontrolSpy = vi.spyOn(api, "caseOracleKontrol");
    // İlk yoklamalarda iş sürüyor: bekleme durumu ekranda görünsün.
    const gercek = api.caseOracle;
    let n = 0;
    vi.spyOn(api, "caseOracle").mockImplementation(async (...a) => (n++ < 3 ? oracle(null, { kontrol_suruyor: true }) : gercek(...a)));
    for (const etiket of ["S4 beklenen", "Beklenen sonuç"]) {
      const alan = within(c).getByLabelText(etiket) as HTMLTextAreaElement;
      const yeni = alan.value.replace("750,00 TL", "760,00 TL");
      await userEvent.clear(alan);
      await userEvent.type(alan, yeni);
    }
    await anlamYanitla(c);
    await userEvent.click(within(c).getByRole("button", { name: "Düzeltip onayla" }));
    expect(await within(c).findByText("Beklenen sonuç kontrol ediliyor…")).toBeInTheDocument();
    expect(kontrolSpy).toHaveBeenCalledWith(C6, expect.objectContaining({ expected_result: expect.stringContaining("760,00 TL") }));
    await waitFor(() => expect(mockVerisi().caseler.find((x) => x.id === C6)!.durum).toBe("approved"), { timeout: 3000 });
    const sonra = await kart(C6_BASLIK);
    expect(await within(sonra).findByText("Tabloyla uyumlu ✓")).toBeInTheDocument();
  });

  it("önerilen içerik hâlâ uyuşmuyorsa karar gönderilmez; karşılaştırma ve istisna formu çıkar, gerekçeyle onaylanır", async () => {
    const c = await duzenle();
    const kararSpy = vi.spyOn(api, "caseKarari");
    const baslik = within(c).getByLabelText("Başlık");
    await userEvent.type(baslik, " (sınır)");
    await userEvent.click(within(c).getByRole("button", { name: "Düzeltip onayla" }));
    const panel = await within(c).findByText("Önerilen içerik tabloyla uyuşmuyor ✗");
    expect(panel).toBeInTheDocument();
    expect(kararSpy).not.toHaveBeenCalled();
    expect(within(c).getByRole("region", { name: "Önerilen içeriğin tablo karşılaştırması" })).toBeInTheDocument();
    const alan = within(c).getByLabelText("İstisna gerekçesi");
    await waitFor(() => expect(alan).toHaveFocus());
    await userEvent.type(alan, "Sınır değeri PO ile ayrıca teyit edildi.");
    await userEvent.click(within(c).getByRole("button", { name: "İstisnayla düzeltip onayla" }));
    await waitFor(() => expect(mockVerisi().caseler.find((x) => x.id === C6)!.durum).toBe("approved"));
    expect(kararSpy).toHaveBeenCalledWith(
      C6,
      expect.objectContaining({ karar: "edit", oracle_istisna_gerekce: "Sınır değeri PO ile ayrıca teyit edildi.", oracle_istisna_turu: "uyumsuz" }),
    );
  });

  it("onyüz KRİTİK 1: engelden sonra form değişirse eski içerik istisnayla gönderilmez; panel kapanır, yeniden gönderim yeni içeriği kontrol eder", async () => {
    const c = await duzenle();
    const kararSpy = vi.spyOn(api, "caseKarari");
    const kontrolSpy = vi.spyOn(api, "caseOracleKontrol");
    const baslik = within(c).getByLabelText("Başlık");
    await userEvent.type(baslik, " (sınır)");
    await userEvent.click(within(c).getByRole("button", { name: "Düzeltip onayla" }));
    await within(c).findByText("Önerilen içerik tabloyla uyuşmuyor ✗");
    // Analist engelden sonra değeri tabloya getirir: panel (ve eski içeriğin istisna formu) kapanır.
    for (const etiket of ["S4 beklenen", "Beklenen sonuç"]) {
      const alan = within(c).getByLabelText(etiket) as HTMLTextAreaElement;
      const yeni = alan.value.replace("750,00 TL", "760,00 TL");
      await userEvent.clear(alan);
      await userEvent.type(alan, yeni);
    }
    expect(within(c).queryByTestId("istisna-formu")).toBeNull();
    expect(within(c).queryByText("Önerilen içerik tabloyla uyuşmuyor ✗")).toBeNull();
    await anlamYanitla(c);
    await userEvent.click(within(c).getByRole("button", { name: "Düzeltip onayla" }));
    await waitFor(() => expect(mockVerisi().caseler.find((x) => x.id === C6)!.durum).toBe("approved"), { timeout: 3000 });
    // Gönderilen içerik güncel olandır; istisna gerekçesi yok.
    expect(kontrolSpy).toHaveBeenLastCalledWith(C6, expect.objectContaining({ expected_result: expect.stringContaining("760,00 TL") }));
    expect(kararSpy).toHaveBeenCalledTimes(1);
    expect(kararSpy.mock.calls[0][1]).not.toHaveProperty("oracle_istisna_gerekce");
    expect(kararSpy.mock.calls[0][1]).toMatchObject({ icerik: expect.objectContaining({ expected_result: expect.stringContaining("760,00 TL") }) });
  });

  it("kontrol zamanında bitmezse düzenleme kaybolmaz; 'Yeniden dene' sunulur (sahte zamanlayıcı, gerçek ayarlar)", async () => {
    const c = await duzenle();
    // S7: zaman aşımı gerçek bekleme yerine sahte zamanlayıcıyla; varsayılan ayarlar (1 sn aralık, 20 sn sınır).
    ON_KONTROL.araMs = 1000;
    ON_KONTROL.zamanAsimiMs = 20000;
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.spyOn(api, "caseOracle").mockResolvedValue(oracle(null, { kontrol_suruyor: true }));
    const kullanici = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await kullanici.type(within(c).getByLabelText("Başlık"), " x");
    await kullanici.click(within(c).getByRole("button", { name: "Düzeltip onayla" }));
    expect(await within(c).findByText("Beklenen sonuç kontrol ediliyor…")).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(19000);
    expect(within(c).queryByText("Kontrol zamanında bitmedi")).toBeNull();
    await vi.advanceTimersByTimeAsync(2500);
    expect(await within(c).findByText("Kontrol zamanında bitmedi")).toBeInTheDocument();
    vi.useRealTimers();
    expect(within(c).getByRole("button", { name: "Yeniden dene" })).toBeInTheDocument();
    expect((within(c).getByLabelText("Başlık") as HTMLInputElement).value).toMatch(/ x$/);
    expect(mockVerisi().caseler.find((x) => x.id === C6)!.durum).toBe("draft");
  });

  it("tablo kapsamı dışındaki case'te ön kontrol istenmez", async () => {
    await oturumAc("analist");
    const spy = vi.spyOn(api, "caseOracleKontrol");
    uygulama(`/gereksinimler/${REQ}/caseler`);
    const c = await kart(C6_BASLIK);
    await within(c).findByText("Tablo yok");
    await userEvent.click(within(c).getByRole("button", { name: "Düzelt" }));
    await userEvent.type(within(c).getByLabelText("Başlık"), " x");
    await userEvent.click(within(c).getByRole("button", { name: "Düzeltip onayla" }));
    await waitFor(() => expect(mockVerisi().caseler.find((x) => x.id === C6)!.durum).toBe("approved"));
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("karşılaştırılamayan değerler ve kısmen uyumlu (K11)", () => {
  it("V9: C2'de bedava adet, indirim ve toplam karşılaştırılır; karşılaştırılamayan yok, tolerans görünür", async () => {
    await oturumAc("analist");
    const c2 = (await api.caseler(REQ)).find((c) => c.id === "case-1-2")!;
    expect(c2.oracle?.sonuc).toBe("uyumlu");
    expect(c2.oracle?.karsilastirilamayan).toEqual([]);
    expect(new Set(c2.oracle?.karsilastirmalar.map((k) => k.column))).toEqual(new Set(["bedava_adet", "indirim", "toplam"]));
    uygulama(`/gereksinimler/${REQ}/caseler`);
    const kartC2 = await kart(/^7 adet kampanyalı/);
    const ayrinti = within(kartC2).getByTestId("oracle-ayrinti");
    await userEvent.click(within(ayrinti).getByText(/^Tablo karşılaştırması/, { selector: "summary" }));
    expect(within(ayrinti).getByRole("columnheader", { name: "Case metnindeki ifade" })).toBeInTheDocument();
    // Onyüz 19: sayısal çıktıda tablo değerinin yanında tolerans.
    expect(within(ayrinti).getAllByText(/± 0,01/).length).toBeGreaterThan(0);
    expect(within(ayrinti).getByTestId("oracle-degerler")).toHaveTextContent(/Değer düzeyinde: \d+ uyumlu · 0 farklı · 0 karşılaştırılamadı/);
  });

  it("ara toplam yazmayan case: 'Kısmen uyumlu — n değer kontrol edilemedi' çipi, soluk grup ve uyarıyla açık onay", async () => {
    await oturumAc("analist");
    const c = mockVerisi().caseler.find((x) => x.id === "case-1-10")!;
    c.durum = "draft";
    c.icerik = JSON.parse(JSON.stringify(c.icerik).replaceAll(/ara toplam [0-9.,]+ TL, /g, "")) as TestCase["icerik"];
    c.icerik_hash = (await api.caseOracleKontrol(c.id, c.icerik)).icerik_hash!;
    await isBitsin();
    const o = (await api.caseler(REQ)).find((x) => x.id === c.id)!.oracle!;
    expect(o.sonuc).toBe("kismen");
    const n = o.degerler!.karsilastirilamayan + o.degerler!.atilan;
    expect(n).toBeGreaterThan(0);
    uygulama(`/gereksinimler/${REQ}/caseler`);
    const k = await kart(new RegExp(c.icerik.title.slice(0, 20)));
    expect(await within(k).findByText(`Kısmen uyumlu — ${n} değer kontrol edilemedi`)).toBeInTheDocument();
    expect(within(k).getByTestId("oracle-ayrinti")).toHaveAttribute("open");
    const grup = within(k).getAllByTestId("oracle-karsilastirilamadi")[0];
    expect(within(grup).getByRole("rowheader", { name: "Karşılaştırılamadı: case'te bulunamayan girdi: ara_toplam" })).toBeInTheDocument();
    expect(within(k).getByTestId("oracle-uyari")).toHaveTextContent(UYARI_KISMEN);
    expect(within(k).getByRole("button", { name: "Onayla" })).toBeEnabled();
  });
});
