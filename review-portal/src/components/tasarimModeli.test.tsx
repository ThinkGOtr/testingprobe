// İki tur (011 F3, K1): üretim kipi formu, tasarım modeli paneli (tablolar, Onayla engeli, alan bazlı
// Düzelt, Reddet, sıradaki adım, yer tutucu engeli, yeniden üretim onayı), K20/D1: onaydan sonra tur 2
// otomatik (alan yoksa eski "Case'leri üret") ve mock uç sözleşmesi.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ayar, mockVerisi } from "../api/mock/handlers";
import { goldenModel, ozettenModel } from "../api/mock/tasarimModeli";
import { KAYNAK } from "../api/mock/fixtures";
import type { GereksinimDetay as Detay } from "../api/types";
import type { DesignModel, TasarimModeliKaydi } from "../api/tasarimModeliTipleri";
import { modelTamamla } from "../api/tasarimModeliTipleri";
import { OturumProvider } from "../auth";
import { modelSorunlari, tur2Uyarla, YER_TUTUCU_NEDENI } from "../lib/tasarimModeli";
import { oturumAc, sar } from "../test/yardimci";
import { BildirimProvider } from "./Bildirim";
import { gecerlilikDegistir, ogeSil, TasarimModeliDuzenleyici } from "./TasarimModeliDuzenleyici";
import { TasarimModeliTablolari } from "./TasarimModeliTablolari";

const bekleIsler = async () => {
  const { bekleyenMockIs } = await import("../api/mock/handlers");
  const son = Date.now() + 5000;
  do await new Promise((r) => setTimeout(r, 10));
  while (bekleyenMockIs() > 0 && Date.now() < son);
};

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

const gereksinim = (id: string) => mockVerisi().gereksinimler.find((g) => g.id === id)! as Detay;

/** TPD-1'i PO onaylı, case üretimi bekleyen hâle getirir. */
function poOnayli(): Detay {
  const g = gereksinim("req-tpd-1");
  g.durum = "po_approved";
  delete g.adim;
  return g;
}

const ORNEK: DesignModel = modelTamamla({
  conditions: [{ id: "TCOND-1", ac_refs: ["AC3"], statement: "Kampanyasız minimum tutar 750,00 TL", risk: "high", rationale: "Para etkili" }],
  techniques: [
    { condition_id: "TCOND-1", technique: "EP", rationale: "Tutar sınıfları" },
    { condition_id: "TCOND-1", technique: "BVA", rationale: "Sıralı tutar, eşik var" },
    { condition_id: "TCOND-1", technique: "DT", rationale: "Kampanya × tutar" },
  ],
  coverage_items: [
    { id: "EP-V1", ac_ref: "AC3", definition: "750,00 TL ve üzeri", valid: true },
    { id: "EP-I1", ac_ref: "AC3", definition: "750,00 TL altı", valid: false },
    { id: "BV-1", ac_ref: "AC3", definition: "Tam 750,00 TL", valid: true },
    { id: "DT-R1", ac_ref: "AC3", definition: "Kampanyasız ve altı", valid: false },
  ],
  partitions: [
    { field: "tutar", item_id: "EP-V1", definition: "≥ 750,00", representative: "800,00 TL", valid: true },
    { field: "tutar", item_id: "EP-I1", definition: "< 750,00", representative: "150,00 TL", valid: false },
  ],
  boundaries: [{ field: "tutar", item_id: "BV-1", value: "750,00 TL", side: "on", expected: "accept", inclusive_source: "AC3" }],
  decision_tables: [
    {
      id: "DT1",
      conditions: ["Kampanyalı", "Tutar"],
      actions: ["Uyarı"],
      rules: [{ item_id: "DT-R1", condition_values: [{ condition: "Kampanyalı", value: "hayır" }, { condition: "Tutar", value: "< 750" }], actions: ["Uyarı göster"] }],
      undefined_combinations: [{ description: "Kampanyalı ve kampanyasız ürün birlikte", question_ref: "Q1" }],
    },
  ],
  model_issues: [{ kind: "undefined_combination", detail: "Karışık sepet tanımsız" }],
  open_questions: [{ id: "Q1", question: "Karışık sepette minimum aranır mı?", owner: "PO" }],
});

// Uygulamanın tamamını çizen akış testleri yük altında yavaş: tek test başına üst sınır.
const AGIR = 60_000;
const BEKLE = { timeout: 15_000 };

beforeEach(() => {
  ayar.isAdimiMs = 0;
});

describe("model içi tutarlılık (önizleme)", () => {
  it("örnek model temiz; tanımsız öğe, geçerlilik çelişkisi ve yinelenen kimlik yakalanır", () => {
    expect(modelSorunlari(ORNEK)).toEqual([]);
    const bozuk = JSON.parse(JSON.stringify(ORNEK)) as DesignModel;
    bozuk.partitions[0].item_id = "EP-V9";
    bozuk.coverage_items.push({ ...bozuk.coverage_items[1] });
    bozuk.boundaries[0].expected = "reject";
    const s = modelSorunlari(bozuk).join("\n");
    expect(s).toMatch(/coverage_items'ta olmayan öğe: EP-V9/);
    expect(s).toMatch(/yinelenen kapsam öğesi kimliği: EP-I1/);
    expect(s).toMatch(/BV-1: reddedilen sınır değer valid:true/);
  });

  it("öğe silinince bağlı satırlar da çıkar; geçerlilik değişimi bölüme yansır", () => {
    const m = ogeSil(ORNEK, "DT-R1");
    expect(m.decision_tables[0].rules).toEqual([]);
    expect(modelSorunlari(m)).toEqual([]);
    const g = gecerlilikDegistir(ORNEK, "EP-V1", false);
    expect(g.partitions[0].valid).toBe(false);
  });

  it("golden yoksa model case_generation golden'ının üst listelerinden türetilir (birebir aynı)", () => {
    const ozet = KAYNAK.case_generation["TPD-3"].ozet!;
    const m = ozettenModel(ozet);
    expect(m.coverage_items).toEqual(ozet.coverage_items);
    expect(m.open_questions).toEqual(ozet.open_questions);
    expect(m.assumptions).toEqual(ozet.assumptions);
    expect(modelSorunlari(m)).toEqual([]);
  });

  it("golden modeli (varsa) case_generation golden'ıyla aynı üst listeleri taşır", () => {
    const g = poOnayli();
    const { model, mod } = goldenModel(g);
    expect(mod).toBe("replay");
    const ad = Object.keys(KAYNAK.case_generation).find((a) => KAYNAK.case_generation[a].girdi_ac.join("\n") === g.kabul_kriterleri.map((x) => `${x.ref}: ${x.metin}`).join("\n"))!;
    const ozet = KAYNAK.case_generation[ad].ozet as Record<string, unknown>;
    expect(model.coverage_items).toEqual(ozet.coverage_items);
    expect(model.open_questions).toEqual(ozet.open_questions);
    expect(model.assumptions).toEqual(ozet.assumptions);
  });
});

describe("tasarım modeli tabloları", () => {
  it("koşullar, teknikler, bölümler, sınırlar, karar tablosu, model sorunları ve açık sorular tablo olarak; boş bölüm yok", async () => {
    await oturumAc("testci");
    sar(<TasarimModeliTablolari m={ORNEK} />);
    expect(within(screen.getByTestId("model-kosullar")).getByText("Kampanyasız minimum tutar 750,00 TL")).toBeInTheDocument();
    expect(within(screen.getByTestId("model-teknikler")).getByText("Sıralı tutar, eşik var")).toBeInTheDocument();
    expect(within(screen.getByTestId("model-bolumler")).getByText("150,00 TL")).toBeInTheDocument();
    expect(within(screen.getByTestId("model-sinirlar")).getByText("kabul")).toBeInTheDocument();
    const dt = screen.getByTestId("model-karar-tablosu");
    expect(within(dt).getByRole("columnheader", { name: "Kampanyalı" })).toBeInTheDocument();
    expect(within(dt).getByText("Uyarı göster")).toBeInTheDocument();
    expect(screen.getByTestId("model-tanimsiz-kombinasyon")).toHaveTextContent("Kampanyalı ve kampanyasız ürün birlikte (Q1)");
    expect(screen.getByTestId("model-sorunlari")).toHaveTextContent("Tanımsız kombinasyon");
    expect(screen.getByTestId("model-acik-sorular")).toHaveTextContent("Karışık sepette minimum aranır mı?");
    expect(screen.queryByTestId("model-durum-modeli")).not.toBeInTheDocument();
    expect(screen.queryByTestId("model-akislar")).not.toBeInTheDocument();
    expect(screen.queryByTestId("model-pairwise")).not.toBeInTheDocument();
    expect(screen.queryByTestId("model-varsayimlar")).not.toBeInTheDocument();
  });
});

describe("alan bazlı düzeltme", () => {
  it("tanım düzeltilir, öğe silinir, soru eklenir; kaydet düzenlenmiş modeli verir", async () => {
    await oturumAc("testci");
    const kaydet = vi.fn();
    const u = userEvent.setup();
    sar(<TasarimModeliDuzenleyici ilk={ORNEK} kaydet={kaydet} vazgec={() => undefined} />);
    const kaydetDugmesi = screen.getByRole("button", { name: "Düzeltmeyi kaydet ve onayla" });
    expect(kaydetDugmesi).toBeDisabled(); // değişiklik yok
    const tanim = screen.getByLabelText("EP-V1 tanımı");
    await u.clear(tanim);
    await u.type(tanim, "750,00 TL ve üstü (dahil)");
    await u.click(screen.getByRole("button", { name: "DT-R1 öğesini sil" }));
    await u.click(screen.getByRole("button", { name: "Soru ekle" }));
    expect(kaydetDugmesi).toBeDisabled(); // boş soru metni
    await u.type(screen.getByLabelText("Q2 soru"), "Kuruş yuvarlama?");
    await u.selectOptions(screen.getByLabelText("BV-1 beklenen"), "open_question");
    expect(kaydetDugmesi).toBeEnabled();
    await u.click(kaydetDugmesi);
    const m = kaydet.mock.calls[0][0] as DesignModel;
    expect(m.coverage_items.find((o) => o.id === "EP-V1")!.definition).toBe("750,00 TL ve üstü (dahil)");
    expect(m.coverage_items.some((o) => o.id === "DT-R1")).toBe(false);
    expect(m.decision_tables[0].rules).toEqual([]);
    expect(m.open_questions.map((q) => q.id)).toEqual(["Q1", "Q2"]);
    expect(m.boundaries[0].expected).toBe("open_question");
  });

  it("geçersiz yeni öğe kimliği reddedilir; model kontrolü ihlali kaydı engeller", async () => {
    await oturumAc("testci");
    const u = userEvent.setup();
    sar(<TasarimModeliDuzenleyici ilk={ORNEK} kaydet={() => undefined} vazgec={() => undefined} />);
    await u.type(screen.getByLabelText("Yeni öğe kimliği"), "XX-1");
    await u.type(screen.getByLabelText("Yeni öğe tanımı"), "deneme");
    expect(screen.getByText(/Kimlik deseni/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Öğe ekle" })).toBeDisabled();
    // ST öğesi eklenir ama ST tekniği seçilmemiş: model kontrolü uyarısı, kaydet pasif.
    await u.clear(screen.getByLabelText("Yeni öğe kimliği"));
    await u.type(screen.getByLabelText("Yeni öğe kimliği"), "ST-T1");
    await u.click(screen.getByRole("button", { name: "Öğe ekle" }));
    expect(screen.getByTestId("duzen-sorunlar")).toHaveTextContent("ST-T1: tekniği (ST)");
    expect(screen.getByRole("button", { name: "Düzeltmeyi kaydet ve onayla" })).toBeDisabled();
  });
});

describe("iki tur akışı (gereksinim detayı + mock)", () => {
  it("üretim formunda varsayılan iki tur; üst düğme kipi söyler ve kipi açıkça gönderir, model üretilir", async () => {
    await oturumAc("testci");
    const g = poOnayli();
    const spy = vi.spyOn(api, "caseUret");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-tpd-1");
    const form = await screen.findByTestId("uretim-kipi", undefined, BEKLE);
    expect(within(form).getByRole("radio", { name: /İki tur \(önerilen\)/ })).toBeChecked();
    expect(within(form).getByRole("radio", { name: /Tek tur \(hızlı\)/ })).not.toBeChecked();
    expect(screen.queryByRole("button", { name: "Case üret (tek tur)" })).not.toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Tasarım modelini üret (iki tur)" }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("req-tpd-1", "iki_tur"), BEKLE);
    await bekleIsler();
    await waitFor(() => expect(g.durum).toBe("model_ready"), BEKLE);
    const panel = await screen.findByTestId("tasarim-modeli-paneli", undefined, BEKLE);
    expect(await within(panel).findByTestId("model-ogeler", undefined, BEKLE)).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Modeli onayla" })).toBeEnabled();
    expect(within(panel).queryByRole("button", { name: "Case'leri üret" })).not.toBeInTheDocument();
    expect(within(panel).getByTestId("model-siradaki-adim")).toHaveTextContent(
      "Sıradaki adım: modeli inceleyip onaylayın — onaydan sonra case'ler otomatik üretilir",
    );
    spy.mockRestore();
  }, AGIR);

  it("tek tur seçilirse gövde tek_tur ve doğrudan case üretimi", async () => {
    await oturumAc("testci");
    const g = poOnayli();
    const spy = vi.spyOn(api, "caseUret");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-tpd-1");
    await u.click(await screen.findByRole("radio", { name: /Tek tur \(hızlı\)/ }, BEKLE));
    await u.click(screen.getByRole("button", { name: "Case üret (tek tur)" }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("req-tpd-1", "tek_tur"), BEKLE);
    await bekleIsler();
    await waitFor(() => expect(g.durum).toBe("cases_ready"), BEKLE);
    spy.mockRestore();
  }, AGIR);

  it("K20: onay tur 2'yi otomatik başlatır — bildirim ve panel durumu; 'Case'leri üret' görünmez", async () => {
    await oturumAc("testci");
    const g = poOnayli();
    await api.caseUret("req-tpd-1", "iki_tur");
    await bekleIsler();
    ayar.isAdimiMs = 200; // tur 2 sürerken panel durumu görünsün
    const caseUret = vi.spyOn(api, "caseUret");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-tpd-1");
    const panel = await screen.findByTestId("tasarim-modeli-paneli", undefined, BEKLE);
    await u.click(await within(panel).findByRole("button", { name: "Modeli onayla" }, BEKLE));
    expect(await screen.findByText(/Tasarım modeli onaylandı\. Case üretimi otomatik başladı \(üretim \d+\)\./, undefined, BEKLE)).toBeInTheDocument();
    expect(await within(panel).findByTestId("model-tur2-durumu", undefined, BEKLE)).toHaveTextContent(/Case üretimi otomatik başladı \(üretim \d+\)\./);
    expect(within(panel).queryByRole("button", { name: "Case'leri üret" })).not.toBeInTheDocument();
    // Tur 2 portaldan ayrı bir generate-cases çağrısı gerektirmez.
    expect(caseUret).not.toHaveBeenCalled();
    ayar.isAdimiMs = 0;
    await bekleIsler();
    await waitFor(() => expect(g.durum).toBe("cases_ready"), BEKLE);
    caseUret.mockRestore();
  }, AGIR);

  it("onay yanıtında tur 2 alanı yoksa (eski core) 'Case'leri üret' görünür; tıklanınca onaylı modelden case üretilir", async () => {
    await oturumAc("testci");
    const g = poOnayli();
    await api.caseUret("req-tpd-1", "iki_tur");
    await bekleIsler();
    // Eski core: onay yalnız modeli onaylar (gereksinim model_ready kalır), yanıtta tur2 yok.
    const karar = vi.spyOn(api, "tasarimModeliKarari").mockImplementation(async (modelId) => {
      const kayit = mockVerisi().tasarimModelleri!["req-tpd-1"].find((m) => m.id === modelId)!;
      kayit.durum = "approved";
      kayit.onaylanan_hash = kayit.icerik_hash;
      return { ...kayit, tur2: null };
    });
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-tpd-1");
    const panel = await screen.findByTestId("tasarim-modeli-paneli", undefined, BEKLE);
    await u.click(await within(panel).findByRole("button", { name: "Modeli onayla" }, BEKLE));
    expect(await screen.findByText("Tasarım modeli onaylandı.", undefined, BEKLE)).toBeInTheDocument();
    const uret = await within(panel).findByRole("button", { name: "Case'leri üret" }, BEKLE);
    expect(within(panel).getByTestId("model-siradaki-adim")).toHaveTextContent("'Case'leri üret' ile onaylı modelden case üretin.");
    karar.mockRestore();
    const spy = vi.spyOn(api, "caseUret");
    await u.click(uret);
    await waitFor(() => expect(spy).toHaveBeenCalledWith("req-tpd-1", "iki_tur"), BEKLE);
    await bekleIsler();
    await waitFor(() => expect(g.durum).toBe("cases_ready"), BEKLE);
    spy.mockRestore();
  }, AGIR);

  it("REPLAY-MISS yer tutucu model onaylanamaz: Onayla ve Düzelt pasif, neden görünür; sıradaki adım yeniden üretim", async () => {
    await oturumAc("testci");
    poOnayli();
    await api.caseUret("req-tpd-1", "iki_tur");
    await bekleIsler();
    const kayit = mockVerisi().tasarimModelleri!["req-tpd-1"].at(-1) as TasarimModeliKaydi;
    kayit.uretim_modu = "replay_miss";
    uygulama("/gereksinimler/req-tpd-1");
    const panel = await screen.findByTestId("tasarim-modeli-paneli", undefined, BEKLE);
    const onayla = await within(panel).findByRole("button", { name: "Modeli onayla" }, BEKLE);
    expect(onayla).toBeDisabled();
    expect(onayla).toHaveAccessibleDescription(YER_TUTUCU_NEDENI);
    expect(within(panel).getByRole("button", { name: "Düzelt" })).toBeDisabled();
    expect(within(panel).getByRole("button", { name: "Reddet" })).toBeEnabled();
    expect(within(panel).getByTestId("model-yer-tutucu")).toHaveTextContent("Yer tutucu model — onaylanamaz");
    expect(within(panel).getByTestId("model-siradaki-adim")).toHaveTextContent("modeli yeniden üretin — yer tutucu model onaylanamaz");
    // Mock sözleşmesi: yer tutucu dışında core yine kontrolleri uygular; portal onay isteği göndermez.
    expect(within(panel).getByRole("button", { name: "Modeli yeniden üret…" })).toBeEnabled();
  }, AGIR);

  it("'Modeli yeniden üret…' sayfa içi onay ister; Vazgeç istek göndermez, onay modeli yeniden üretir", async () => {
    await oturumAc("testci");
    const g = poOnayli();
    await api.caseUret("req-tpd-1", "iki_tur");
    await bekleIsler();
    const uret = vi.spyOn(api, "tasarimModeliUret");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-tpd-1");
    const panel = await screen.findByTestId("tasarim-modeli-paneli", undefined, BEKLE);
    const dugme = await within(panel).findByRole("button", { name: "Modeli yeniden üret…" }, BEKLE);
    await u.click(dugme);
    const onay = within(panel).getByTestId("model-yeniden-uret-onayi");
    expect(onay).toHaveTextContent("Mevcut taslak (sürüm 1) geçersiz olur");
    expect(within(onay).getByRole("button", { name: "Vazgeç" })).toHaveFocus();
    await u.click(within(onay).getByRole("button", { name: "Vazgeç" }));
    expect(within(panel).queryByTestId("model-yeniden-uret-onayi")).not.toBeInTheDocument();
    expect(uret).not.toHaveBeenCalled();
    await u.click(within(panel).getByRole("button", { name: "Modeli yeniden üret…" }));
    await u.click(within(within(panel).getByTestId("model-yeniden-uret-onayi")).getByRole("button", { name: "Evet, yeniden üret" }));
    await waitFor(() => expect(uret).toHaveBeenCalledWith("req-tpd-1"), BEKLE);
    await bekleIsler();
    await waitFor(() => expect(mockVerisi().tasarimModelleri!["req-tpd-1"].filter((m) => m.durum === "draft")).toHaveLength(1), BEKLE);
    expect(g.durum).toBe("model_ready");
    uret.mockRestore();
  }, AGIR);

  it("model kontrolü ihlali varsa 'Modeli onayla' pasif ve nedeni yazılı; Düzelt açılır", async () => {
    await oturumAc("testci");
    poOnayli();
    await api.caseUret("req-tpd-1", "iki_tur");
    await bekleIsler();
    const kayit = mockVerisi().tasarimModelleri!["req-tpd-1"].at(-1) as TasarimModeliKaydi;
    kayit.icerik.partitions.push({ field: "x", item_id: "EP-V99", definition: "tanımsız", representative: "", valid: true });
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-tpd-1");
    const panel = await screen.findByTestId("tasarim-modeli-paneli", undefined, BEKLE);
    const onayla = await within(panel).findByRole("button", { name: "Modeli onayla" }, BEKLE);
    expect(onayla).toBeDisabled();
    expect(within(panel).getByTestId("model-kontrol-sorunlari")).toHaveTextContent("EP-V99");
    await u.click(within(panel).getByRole("button", { name: "Düzelt" }));
    expect(within(panel).getByTestId("model-duzenleyici")).toBeInTheDocument();
  }, AGIR);

  it("Reddet: ret nedeniyle kaydedilir; ardından 'Modeli yeniden üret…'", async () => {
    await oturumAc("testci");
    poOnayli();
    await api.caseUret("req-tpd-1", "iki_tur");
    await bekleIsler();
    const spy = vi.spyOn(api, "tasarimModeliKarari");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-tpd-1");
    const panel = await screen.findByTestId("tasarim-modeli-paneli", undefined, BEKLE);
    await u.click(await within(panel).findByRole("button", { name: "Reddet" }, BEKLE));
    const form = within(panel).getByTestId("model-ret-formu");
    await u.selectOptions(within(form).getByRole("combobox"), "out_of_scope");
    await u.click(within(form).getByRole("button", { name: "Reddi kaydet" }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ karar: "reject", ret_nedeni: "out_of_scope", icerik_hash: expect.any(String) })),
    );
    expect(await screen.findByText("Tasarım modeli reddedildi.", undefined, BEKLE)).toBeInTheDocument();
    expect(await within(panel).findByRole("button", { name: "Modeli yeniden üret…" }, BEKLE)).toBeEnabled();
    expect(within(panel).getByTestId("model-siradaki-adim")).toHaveTextContent("Sıradaki adım: modeli yeniden üretin.");
    spy.mockRestore();
  }, AGIR);
});

describe("mock uç sözleşmesi", () => {
  it("edit kararı görülen hash ve düzenlenmiş içerikle; eski hash 409, aynı içerik 422", async () => {
    await oturumAc("testci");
    const g = poOnayli();
    const y = await api.caseUret("req-tpd-1", "iki_tur");
    expect(y).toMatchObject({ kip: "iki_tur", asama: "model" });
    await bekleIsler();
    const d = await api.tasarimModeli(g.id);
    expect(d.requirement_durum).toBe("model_ready");
    expect(d.case_uretimi_hazir).toBe(false);
    const m = d.model!;
    await expect(api.tasarimModeliKarari(m.id, { karar: "approve", icerik_hash: "sha256:eski" })).rejects.toMatchObject({ status: 409 });
    await expect(api.tasarimModeliKarari(m.id, { karar: "edit", icerik_hash: m.icerik_hash, icerik: m.icerik })).rejects.toMatchObject({ status: 422 });
    const yeni = JSON.parse(JSON.stringify(m.icerik)) as DesignModel;
    yeni.coverage_items[0].definition += " (düzeltildi)";
    const k = await api.tasarimModeliKarari(m.id, { karar: "edit", icerik_hash: m.icerik_hash, icerik: yeni });
    expect(k.durum).toBe("approved");
    expect(k.onaylanan_hash).toBe(k.icerik_hash);
    // D1/K20: onay tur 2'yi (onaylı modelden case üretimi) otomatik başlatır.
    expect(k.tur2).toMatchObject({ basladi: true, uretim_no: expect.any(Number) });
    expect(g.durum).toBe("generating");
    expect((await api.tasarimModeli(g.id)).case_uretimi_hazir).toBe(false);
    await bekleIsler();
    expect(g.durum).toBe("cases_ready");
    expect(mockVerisi().caseler.some((c) => c.requirement_id === g.id && c.durum === "draft")).toBe(true);
  });

  it("ret tur 2 başlatmaz (yanıtta tur2 yok)", async () => {
    await oturumAc("testci");
    const g = poOnayli();
    await api.caseUret("req-tpd-1", "iki_tur");
    await bekleIsler();
    const m = (await api.tasarimModeli(g.id)).model!;
    const k = await api.tasarimModeliKarari(m.id, { karar: "reject", icerik_hash: m.icerik_hash, ret_nedeni: "missing_ac" });
    expect(k.tur2).toBeNull();
    expect(g.durum).toBe("model_ready");
  });
});

describe("tur 2 yanıt uyarlaması (D1)", () => {
  it("tur2 nesnesi, düz tur2_basladi ve alan yokluğu", () => {
    expect(tur2Uyarla({ tur2: { basladi: true, job_id: "j1", uretim_no: 3, mesaj: "m" } })).toEqual({ basladi: true, job_id: "j1", uretim_no: 3, mesaj: "m" });
    expect(tur2Uyarla({ tur2_basladi: true })).toEqual({ basladi: true, job_id: null, uretim_no: null, mesaj: null });
    expect(tur2Uyarla({ tur2_basladi: false })).toMatchObject({ basladi: false });
    expect(tur2Uyarla({ tur2: null })).toBeNull();
    expect(tur2Uyarla({ id: "m1" })).toBeNull();
  });
});
