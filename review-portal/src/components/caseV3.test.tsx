// Case şeması v3 (specs/011 §4.8, dalga 1): case kartı rozetleri ve blokları, hazır olmayan case'te
// onay engeli (K6), eski (v2) case görünümü (K9), saldırı verisinin HTML olarak işlenmemesi, düzeltme
// formunun "hazır yapma" akışı, "Kapsam ve açık noktalar" paneli, yayın engeli ve yanıt uyarlaması.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import { V3_GEREKSINIM_ID, V3_SALDIRI_VERISI } from "../api/mock/caseV3";
import { mockVerisi } from "../api/mock/handlers";
import type { CaseKapsamOzeti, TestCase, TestCaseIcerik } from "../api/types";
import { caseIcerikUyarla, caseKapsamOzetiUyarla, caseUyarla, yayinOnizlemeUyarla } from "../api/uyum";
import { OturumProvider } from "../auth";
import { hataListesi, hazirlikSorunlari, tutarlilikSorunlari } from "../lib/caseV3";
import { oturumAc, sar } from "../test/yardimci";
import { BildirimProvider } from "./Bildirim";
import { CaseKarti } from "./CaseKarti";
import { KapsamPaneli } from "./KapsamPaneli";

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

/** Sunucu yanıtındaki (zenginleştirilmiş) v3 case: readiness, legacy, çözülmüş atıflar. */
async function v3Case(id: string): Promise<TestCase> {
  return (await api.caseler(V3_GEREKSINIM_ID)).find((c) => c.id === id)!;
}

/** Eski (v2) içerik: v3 anahtarlarının hiçbiri yok. Golden'lardan bağımsız sabit örnek. */
const ESKI_ICERIK: TestCaseIcerik = {
  title: "Sepete ürün eklenir",
  type: "positive",
  risk: "medium",
  acceptance_criteria_refs: ["AC1"],
  preconditions: ["Sepet boş"],
  steps: [{ id: "S1", action: "Sepete ekle butonuna bas", data: null, expected: "Sepet sayacı 1 olur" }],
  expected_result: "Ürün sepette görünür",
  tags: ["AI-generated"],
};

/** Mock deposundaki bir taslağı eski şemalı içerikle değiştirir ve sunucu yanıtı biçiminde döndürür. */
async function eskiCase(): Promise<TestCase> {
  const ham = mockVerisi().caseler.find((c) => c.id === "case-v3-1")!;
  ham.icerik = JSON.parse(JSON.stringify(ESKI_ICERIK)) as TestCaseIcerik;
  return v3Case("case-v3-1");
}

describe("CaseKarti v3: rozetler ve bloklar", () => {
  it("hazır case: hazır olma, öncelik ve teknik rozetleri (tam adla), kapsam, doğrulama noktası, test verisi, temizlik", async () => {
    await oturumAc("analist");
    sar(<CaseKarti tc={await v3Case("case-v3-1")} guncellendi={() => {}} />);
    const hazir = screen.getByTestId("case-hazirlik");
    expect(hazir).toHaveTextContent("Hazır olma durumu: ✓ Hazır");
    expect(hazir).toHaveAttribute("data-durum", "ready");
    // Teknik rozeti: kısaltma görünür; tam Türkçe ad title'da ve erişilebilir metinde.
    // B4: dd'de role/aria-label yok (axe definition-list); etiket dt "Teknikler".
    const teknikler = screen.getByText("Teknikler").nextElementSibling as HTMLElement;
    expect(teknikler.tagName).toBe("DD");
    expect(teknikler).not.toHaveAttribute("role");
    expect(teknikler).not.toHaveAttribute("aria-label");
    expect(within(teknikler).getByTitle("eşdeğerlik bölümleme")).toHaveTextContent("EP (eşdeğerlik bölümleme)");
    expect(within(teknikler).getByTitle("sınır değer analizi")).toHaveTextContent("BVA (sınır değer analizi)");
    expect(screen.getByTestId("case-oncelik")).toHaveTextContent("P1 (Öncelik 1 (en yüksek))");
    expect(screen.getByText("Ana akış ve üst sınır: not kaydedilmezse özellik kullanılamaz.")).toBeInTheDocument();
    const ozet = within(screen.getByTestId("case-v3"));
    expect(ozet.getByText("EP-V1")).toBeInTheDocument();
    expect(ozet.getByText("BV-1")).toBeInTheDocument();
    expect(ozet.getByText("Arayüz (UI)")).toBeInTheDocument();
    expect(ozet.getByText("Sistem")).toBeInTheDocument();
    // Test verisi tablosu: sütun başlıkları ve satır başlığı.
    const veri = within(screen.getByRole("region", { name: /^Test verisi:/ }));
    expect(veri.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Veri", "Değer", "Kapsam öğesi", "İşaret"]);
    expect(veri.getByRole("cell", { name: "not_250" })).toBeInTheDocument();
    expect(within(screen.getByTestId("case-temizlik")).getByText("Oluşturulan siparişi iptal et")).toBeInTheDocument();
    expect(screen.queryByTestId("case-eski-sema")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Onayla" })).toBeEnabled());
  });

  it("varsayıma bağlı case: rozet, varsayım metni ve sahibi; Onayla pasif ve nedeni yazılı", async () => {
    await oturumAc("analist");
    sar(<CaseKarti tc={await v3Case("case-v3-2")} guncellendi={() => {}} />);
    expect(screen.getByTestId("case-hazirlik")).toHaveTextContent("⚠ Varsayıma bağlı");
    const blok = within(screen.getByTestId("case-varsayimlar"));
    expect(blok.getByText("A1")).toBeInTheDocument();
    expect(blok.getByText(/250 karakter sınırı bayt değil/)).toBeInTheDocument();
    expect(blok.getByText(/Sahibi: Analist/)).toBeInTheDocument();
    const onayla = screen.getByRole("button", { name: "Onayla" });
    await waitFor(() => expect(onayla).toHaveAccessibleDescription(/Hazır olmayan case onaylanamaz \(varsayıma bağlı\)/));
    expect(onayla).toBeDisabled();
    // Düzelt ve Reddet açık kalır (K6: analist hazır yapar ya da reddeder).
    expect(screen.getByRole("button", { name: "Düzelt" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Reddet" })).toBeEnabled();
  });

  it("soru bekleyen case: açık soru metni ve sahibi görünür; Onayla pasif; sunucu onayı 422 ile reddeder", async () => {
    await oturumAc("analist");
    const tc = await v3Case("case-v3-3");
    sar(<CaseKarti tc={tc} guncellendi={() => {}} />);
    expect(screen.getByTestId("case-hazirlik")).toHaveTextContent("? Soru bekliyor");
    const blok = within(screen.getByTestId("case-acik-sorular"));
    expect(blok.getByText("Q1")).toBeInTheDocument();
    expect(blok.getByText(/Yalnızca boşluk karakterlerinden oluşan not kaydedilir mi/)).toBeInTheDocument();
    expect(blok.getByText(/Sahibi: PO/)).toBeInTheDocument();
    const onayla = screen.getByRole("button", { name: "Onayla" });
    await waitFor(() => expect(onayla).toHaveAccessibleDescription(/Hazır olmayan case onaylanamaz \(açık soru bekliyor\)/));
    expect(onayla).toBeDisabled();
    // Beklenen sonuç boş: uydurulmaz, açıkça yazılır.
    expect(screen.getByText(/henüz yazılamıyor/)).toBeInTheDocument();
    await expect(api.caseKarari(tc.id, { icerik_hash: tc.icerik_hash, karar: "approve" })).rejects.toMatchObject({ status: 422 });
    expect(mockVerisi().caseler.find((c) => c.id === tc.id)!.durum).toBe("draft");
  });

  it("çözülmüş metni gelmeyen atıf yalnız kimliğiyle gösterilir (çökmez)", async () => {
    await oturumAc("analist");
    const tc = { ...(await v3Case("case-v3-3")), acik_sorular: undefined };
    sar(<CaseKarti tc={tc} guncellendi={() => {}} />);
    const blok = within(screen.getByTestId("case-acik-sorular"));
    expect(blok.getByText("Q1")).toBeInTheDocument();
    expect(blok.getByText(/metni bu yanıtta yok/)).toBeInTheDocument();
  });

  it("saldırı verisi HTML olarak işlenmez: düz metin/kod olarak ve 'güvenlik testi girdisi' işaretiyle gösterilir", async () => {
    await oturumAc("analist");
    const { container } = sar(<CaseKarti tc={await v3Case("case-v3-4")} guncellendi={() => {}} />);
    const veri = screen.getByTestId("case-test-verisi");
    const kod = veri.querySelector("code.veri-deger")!;
    expect(kod.textContent).toBe(V3_SALDIRI_VERISI);
    // Değer metin düğümüdür: belgeye <img>/<script> öğesi eklenmez.
    expect(kod.children).toHaveLength(0);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("[onerror]")).toBeNull();
    expect(within(veri).getByText("⚠ Güvenlik testi girdisi")).toBeInTheDocument();
  });

  it("betik içeren değerler de (başlık, veri) metin olarak kalır", async () => {
    await oturumAc("analist");
    const tc = await v3Case("case-v3-4");
    tc.icerik.test_data = [{ name: "betik", value: "<script>window.__tp_xss = 1</script>", class: null, synthetic: true, is_attack_payload: true }];
    const { container } = sar(<CaseKarti tc={tc} guncellendi={() => {}} />);
    expect(container.querySelector("script")).toBeNull();
    expect((window as unknown as { __tp_xss?: number }).__tp_xss).toBeUndefined();
    expect(screen.getByText("<script>window.__tp_xss = 1</script>")).toBeInTheDocument();
  });

  it("eski (v2) case: 'eski şema' notu; v3 blokları hiç çizilmez; onay açık", async () => {
    await oturumAc("analist");
    const tc = await eskiCase();
    expect(tc.legacy).toBe(true);
    expect(tc.readiness).toBe("ready");
    sar(<CaseKarti tc={tc} guncellendi={() => {}} />);
    expect(screen.getByTestId("case-eski-sema")).toHaveTextContent("eski şema");
    for (const kimlik of ["case-v3", "case-hazirlik", "case-oncelik", "case-test-verisi", "case-temizlik", "case-acik-sorular", "case-varsayimlar"]) {
      expect(screen.queryByTestId(kimlik)).not.toBeInTheDocument();
    }
    expect(screen.queryByRole("group", { name: "Test tasarım teknikleri" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Onayla" })).toBeEnabled());
  });

  it("core onay engeli (onay_engeli) varsa Onayla pasif ve engel metni yazılı", async () => {
    await oturumAc("analist");
    const tc = { ...(await v3Case("case-v3-1")), onay_engeli: "Tutarlılık ihlali olan case onaylanamaz", uyarilar: ["Kapsam öğesi tanımlı değil: EP-V9"] };
    sar(<CaseKarti tc={tc} guncellendi={() => {}} />);
    const onayla = screen.getByRole("button", { name: "Onayla" });
    await waitFor(() => expect(onayla).toHaveAccessibleDescription(/Tutarlılık ihlali olan case onaylanamaz/));
    expect(onayla).toBeDisabled();
    expect(screen.getByText("Kapsam öğesi tanımlı değil: EP-V9")).toBeInTheDocument();
  });
});

describe("CaseKarti v3: düzeltme formu", () => {
  it("tür seçiminde yetki ve entegrasyon var; eski case'te yalnız eski türler ve v3 alanı yok", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    const { unmount } = sar(<CaseKarti tc={await v3Case("case-v3-1")} guncellendi={() => {}} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Düzelt" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Düzelt" }));
    expect(within(screen.getByLabelText("Tür")).getAllByRole("option").map((o) => o.textContent)).toEqual(["Pozitif", "Negatif", "Sınır", "Yetki", "Entegrasyon"]);
    for (const etiket of ["Öncelik", "Öncelik gerekçesi", "Doğrulama noktası", "Kapsadığı öğeler", "Varsayım atıfları", "Açık soru atıfları", "Temizlik adımları (her satır bir adım)"]) {
      expect(screen.getByLabelText(etiket)).toBeInTheDocument();
    }
    expect(screen.getByRole("group", { name: "Test tasarım teknikleri" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /^EP/ })).toBeChecked();
    expect(screen.getByLabelText("Veri 1 değeri")).toBeInTheDocument();
    unmount();

    sar(<CaseKarti tc={await eskiCase()} guncellendi={() => {}} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Düzelt" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Düzelt" }));
    expect(within(screen.getByLabelText("Tür")).getAllByRole("option").map((o) => o.textContent)).toEqual(["Pozitif", "Negatif", "Sınır"]);
    expect(screen.queryByLabelText("Öncelik")).not.toBeInTheDocument();
    expect(screen.queryByTestId("hazirlik-alani")).not.toBeInTheDocument();
  });

  it("eski case düzeltmesi v3 anahtarı eklemeden gönderilir (K9)", async () => {
    await oturumAc("analist");
    const spy = vi.spyOn(api, "caseKarari");
    const guncellendi = vi.fn();
    const u = userEvent.setup();
    sar(<CaseKarti tc={await eskiCase()} guncellendi={guncellendi} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Düzelt" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Düzelt" }));
    await u.type(screen.getByLabelText("S1 veri"), "P-001");
    await u.click(screen.getByRole("button", { name: "Düzeltip onayla" }));
    await waitFor(() => expect(guncellendi).toHaveBeenCalled());
    const icerik = spy.mock.calls[0][1].icerik!;
    expect(Object.keys(icerik).sort()).toEqual(Object.keys(ESKI_ICERIK).sort());
    spy.mockRestore();
  });

  it("soru bekleyen case'i hazır yapma akışı: form eksikleri söyler, hazır olmadan kaydetmez; hazır yapılınca onaylanır", async () => {
    await oturumAc("analist");
    const spy = vi.spyOn(api, "caseKarari");
    const guncellendi = vi.fn();
    const u = userEvent.setup();
    sar(<CaseKarti tc={await v3Case("case-v3-3")} guncellendi={guncellendi} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Düzelt" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Düzelt" }));

    // "Soru bekliyor" hâliyle kaydedilemez: form nedenini söyler, istek gitmez.
    expect(screen.getByLabelText("Durum")).toHaveValue("blocked");
    expect(screen.getByTestId("hazirlik-eksikleri")).toHaveTextContent('Durum "Soru bekliyor": bu hâliyle kaydedilemez');
    await u.click(screen.getByRole("button", { name: "Düzeltip onayla" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/Düzeltme case'i onaylar; durum "Soru bekliyor" iken kaydedilemez/);
    expect(spy).not.toHaveBeenCalled();

    // "Hazır" seçilince atıfların boşaltılması ve beklenenlerin doldurulması gerektiği listelenir.
    await u.selectOptions(screen.getByLabelText("Durum"), "ready");
    const eksikler = screen.getByTestId("hazirlik-eksikleri");
    expect(eksikler).toHaveTextContent("açık soru atıflarını boşaltın (Q1)");
    expect(eksikler).toHaveTextContent("beklenen sonucu dolu olmalı");
    expect(eksikler).toHaveTextContent("boş: S2, S3");
    await u.click(screen.getByRole("button", { name: "Düzeltip onayla" }));
    expect(screen.getByTestId("case-hata-listesi")).toHaveTextContent("açık soru atıflarını boşaltın");
    expect(spy).not.toHaveBeenCalled();

    await u.click(screen.getByRole("button", { name: "Hazır yap: atıfları boşalt" }));
    expect(screen.getByLabelText("Açık soru atıfları")).toHaveValue("");
    await u.type(screen.getByLabelText("S2 beklenen"), "Not alanı boş sayılır");
    await u.type(screen.getByLabelText("S3 beklenen"), "Sipariş notsuz oluşturulur");
    await u.type(screen.getByLabelText("Beklenen sonuç"), "Sipariş detayında not görünmez");
    expect(screen.getByTestId("hazirlik-eksikleri")).toBeEmptyDOMElement();
    await u.click(screen.getByRole("radio", { name: /Evet, anlam değişti/ }));
    await u.click(screen.getByRole("button", { name: "Düzeltip onayla" }));
    await waitFor(() => expect(guncellendi).toHaveBeenCalled());

    const girdi = spy.mock.calls[0][1];
    expect(girdi.karar).toBe("edit");
    expect(girdi.icerik).toMatchObject({ readiness: "ready", open_question_refs: [], assumption_refs: [], expected_result: "Sipariş detayında not görünmez" });
    const sonuc = guncellendi.mock.calls[0][0] as TestCase;
    expect(sonuc.durum).toBe("approved");
    expect(sonuc.readiness).toBe("ready");
    expect(sonuc.acik_sorular).toEqual([]);
    spy.mockRestore();
  });

  it("v3 alanları düzenlenir: teknik, kapsam, öncelik, doğrulama noktası, test verisi, temizlik", async () => {
    await oturumAc("analist");
    const spy = vi.spyOn(api, "caseKarari");
    const guncellendi = vi.fn();
    const u = userEvent.setup();
    sar(<CaseKarti tc={await v3Case("case-v3-4")} guncellendi={guncellendi} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Düzelt" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Düzelt" }));
    await u.selectOptions(screen.getByLabelText("Öncelik"), "P2");
    await u.selectOptions(screen.getByLabelText("Doğrulama noktası"), "API");
    await u.clear(screen.getByLabelText("Öncelik gerekçesi"));
    await u.type(screen.getByLabelText("Öncelik gerekçesi"), "Depo ekranı ayrı story");
    await u.clear(screen.getByLabelText("Temizlik adımları (her satır bir adım)"));
    await u.type(screen.getByLabelText("Temizlik adımları (her satır bir adım)"), "Siparişi iptal et{Enter}Oturumu kapat");
    // Saldırı verisi düzenleme alanında da düz metindir (textarea değeri).
    expect(screen.getByLabelText("Veri 1 değeri")).toHaveValue(V3_SALDIRI_VERISI);
    expect(screen.getByRole("checkbox", { name: /Güvenlik\s+testi girdisi/ })).toBeChecked();
    await u.click(screen.getByRole("button", { name: "Düzeltip onayla" }));
    await waitFor(() => expect(guncellendi).toHaveBeenCalled());
    expect(spy.mock.calls[0][1].icerik).toMatchObject({
      priority: "P2",
      verification_point: "API",
      priority_rationale: "Depo ekranı ayrı story",
      teardown: ["Siparişi iptal et", "Oturumu kapat"],
      technique: ["EG"],
      covers: ["EG-1"],
      test_data: [{ name: "xss_notu", value: V3_SALDIRI_VERISI, class: "EG-1", synthetic: true, is_attack_payload: true }],
    });
    spy.mockRestore();
  });

  it("teknik ↔ kapsam uyumsuzluğunu sunucu 422 ile reddeder; hata listesi madde madde gösterilir", async () => {
    await oturumAc("analist");
    const guncellendi = vi.fn();
    const u = userEvent.setup();
    sar(<CaseKarti tc={await v3Case("case-v3-1")} guncellendi={guncellendi} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Düzelt" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Düzelt" }));
    await u.clear(screen.getByLabelText("Kapsadığı öğeler"));
    await u.type(screen.getByLabelText("Kapsadığı öğeler"), "EP-V9");
    await u.click(screen.getByRole("button", { name: "Düzeltip onayla" }));
    const liste = await screen.findByTestId("case-hata-listesi");
    expect(screen.getByRole("alert")).toHaveTextContent("Düzenlenen case şemaya uymuyor ya da üretim özetiyle tutarsız");
    const maddeler = within(liste).getAllByRole("listitem").map((li) => li.textContent);
    expect(maddeler).toContain("Kapsam öğesi tanımlı değil: EP-V9");
    expect(maddeler).toContain("Teknik BVA için kapsam öğesi yok (BV-… bekleniyor).");
    expect(guncellendi).not.toHaveBeenCalled();
    // Form açık kalır: analist düzeltip yeniden gönderebilir.
    expect(screen.getByLabelText("Kapsadığı öğeler")).toHaveValue("EP-V9");
  });

  it("onay 422 dönerse (ör. core engeli sonradan oluştu) kartta hata listesi gösterilir", async () => {
    await oturumAc("analist");
    const spy = vi
      .spyOn(api, "caseKarari")
      .mockRejectedValueOnce(new ApiError(422, 'Tutarlılık ihlali olan case onaylanamaz — ["Kapsam öğesi tanımlı değil: EP-V9", "Açık soru tanımlı değil: Q7"]'));
    const u = userEvent.setup();
    sar(<CaseKarti tc={await v3Case("case-v3-1")} guncellendi={() => {}} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Onayla" })).toBeEnabled());
    await u.click(screen.getByRole("button", { name: "Onayla" }));
    const liste = await screen.findByTestId("case-hata-listesi");
    expect(within(liste).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("alert")).toHaveTextContent("Tutarlılık ihlali olan case onaylanamaz");
    spy.mockRestore();
  });
});

describe("Kapsam ve açık noktalar paneli", () => {
  it("case review sayfasında: oranlar, dağılımlar, açık soru, varsayım, kapsam matrisi, kapsanmayanlar, negatif kararlar", async () => {
    await oturumAc("analist");
    uygulama(`/gereksinimler/${V3_GEREKSINIM_ID}/caseler`);
    const panel = within((await screen.findByRole("heading", { name: "Kapsam ve açık noktalar" })).closest("section")!);
    await panel.findByTestId("kapsam-oranlar");
    // 4 AC'nin 4'ü, 10 öğenin 8'i kapsanıyor; 6 geçersiz öğenin 6'sının kararı var.
    const oranlar = within(panel.getByTestId("kapsam-oranlar"));
    expect(oranlar.getByText("Gereksinim kapsamı").parentElement).toHaveTextContent("%100");
    expect(oranlar.getByText("Öğe kapsamı").parentElement).toHaveTextContent("%80");
    expect(oranlar.getByText("Negatif karar kapsamı").parentElement).toHaveTextContent("%100");

    const teknik = within(panel.getByTestId("kapsam-teknik-dagilimi"));
    expect(teknik.getByTitle("eşdeğerlik bölümleme").closest("li")).toHaveTextContent("EP (eşdeğerlik bölümleme) 4 case");
    expect(teknik.getByTitle("hata tahmini").closest("li")).toHaveTextContent("1 case");
    const hazirlik = within(panel.getByTestId("kapsam-hazirlik-dagilimi")).getAllByRole("listitem").map((li) => li.textContent);
    expect(hazirlik).toEqual(["Hazır olma durumu: ✓ Hazır 3 case", "Hazır olma durumu: ⚠ Varsayıma bağlı 2 case", "Hazır olma durumu: ? Soru bekliyor 1 case"]);

    expect(within(panel.getByTestId("kapsam-acik-sorular")).getByText(/Yalnızca boşluk karakterlerinden oluşan not/)).toBeInTheDocument();
    expect(panel.getByTestId("kapsam-acik-sorular")).toHaveTextContent("Sahibi: PO");
    expect(panel.getByTestId("kapsam-varsayimlar")).toHaveTextContent("250 karakter sınırı bayt değil");

    // Kapsam matrisi: öğe → kapsayan case'ler; kapsanmayan öğe gerekçesiyle.
    const matris = within(panel.getByRole("region", { name: "Kapsam matrisi tablosu" }));
    expect(matris.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Öğe", "Tür", "Tanım", "Sınıf", "Kapsayan case'ler", "Gerekçe"]);
    const satir = (oge: string) => within(matris.getByRole("cell", { name: oge }).closest("tr")!);
    expect(satir("BV-1").getAllByRole("link").map((a) => a.textContent)).toEqual(["#1", "#6"]);
    // Bağlantı case kimliğiyle kurulur (sıra no üretimler arasında tekil değil); erişilebilir ad başlığı taşır.
    expect(satir("BV-1").getByRole("link", { name: "#1: 250 karakterlik not siparişle birlikte kaydedilir" })).toHaveAttribute("href", "#case-case-v3-1");
    expect(oranlar.getByText("Öğe kapsamı").parentElement).toHaveTextContent("8/10");
    expect(satir("AC4").getByText("Kabul kriteri")).toBeInTheDocument();
    expect(satir("EP-I2").getByText(/Geçersiz/)).toBeInTheDocument();
    // UX-13: gerekçesi yazılı kapsanmayan öğe nötr; "⚠ Kapsanmıyor" yalnız gerekçesizde.
    expect(satir("EG-2").getByText("Kapsanmıyor (gerekçeli)")).toBeInTheDocument();
    expect(matris.queryByText("⚠ Kapsanmıyor")).not.toBeInTheDocument();
    expect(satir("EG-2").getByText(/Story satır sonu davranışını tanımlamıyor/)).toBeInTheDocument();

    const kapsanmayan = panel.getByTestId("kapsam-kapsanmayanlar");
    expect(kapsanmayan).toHaveTextContent("Kapsanmayanlar (2)");
    expect(kapsanmayan).toHaveTextContent("EG-3");
    expect(kapsanmayan).toHaveTextContent("Ağ hatası davranışı bu story'nin kapsamında tanımlı değil.");

    const kararlar = within(panel.getByRole("region", { name: "Negatif kapsam kararları tablosu" }));
    expect(kararlar.getAllByText("Negatif case ile test edilir")).toHaveLength(5);
    expect(kararlar.getByText("Kapsam dışı (gerekçeli)")).toBeInTheDocument();
  });

  it("karar kapsamı değiştirir: case reddedilince panel yenilenir", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama(`/gereksinimler/${V3_GEREKSINIM_ID}/caseler`);
    const panel = within((await screen.findByRole("heading", { name: "Kapsam ve açık noktalar" })).closest("section")!);
    await panel.findByTestId("kapsam-oranlar");
    const kart = within((await screen.findByRole("heading", { name: "Nottaki betik sipariş detayında çalıştırılmaz" })).closest("article")!);
    await u.click(kart.getByRole("button", { name: "Reddet" }));
    await u.selectOptions(kart.getByLabelText("Ret nedeni"), "out_of_scope");
    await u.click(kart.getByRole("button", { name: "Reddi kaydet" }));
    // EG-1'i kapsayan tek case reddedildi: öğe kapsamı 8/10 → 7/10; AC3 yalnız #6 ile kapsanır.
    await waitFor(() => expect(within(panel.getByTestId("kapsam-oranlar")).getByText("Öğe kapsamı").parentElement).toHaveTextContent("%70"));
    expect(panel.getByTestId("kapsam-uyarilari")).toHaveTextContent('EG-1: karar "tested" ama hiçbir güncel case kapsamıyor.');
  });

  it("eski şemalı gereksinim (özet yok): anlamlı boş durum", () => {
    const { rerender } = render(<KapsamPaneli ozet={null} caseSayisi={3} eskiSema />);
    expect(screen.getByTestId("kapsam-bos")).toHaveTextContent("Bu gereksinimin case'leri eski şemayla üretildi; kapsam özeti yok.");
    expect(screen.queryByTestId("kapsam-oranlar")).not.toBeInTheDocument();
    rerender(<KapsamPaneli ozet={null} caseSayisi={0} />);
    expect(screen.getByTestId("kapsam-bos")).toHaveTextContent("Henüz kapsam özeti yok.");
    rerender(<KapsamPaneli ozet={undefined} yukleniyor caseSayisi={0} />);
    expect(screen.getByRole("status")).toHaveTextContent("Yükleniyor");
  });

  it("özeti olmayan üretimde yalnız kabul kriteri kapsamı gösterilir; boş listeler için boş durum metni", () => {
    const ozet: CaseKapsamOzeti = {
      requirement_id: "r",
      uretimler: [],
      kapsam_matrisi: [{ item: "AC1", tur: "ac", tanim: "Ürün sepete eklenir", valid: null, covered_by: [1], gerekce: null }],
      oranlar: { gereksinim_kapsami: { kapsanan: 1, toplam: 1, oran: 1 }, oge_kapsami: { kapsanan: 0, toplam: 0, oran: null }, negatif_karar_kapsami: { kapsanan: 0, toplam: 0, oran: null } },
      teknik_dagilimi: {},
      readiness_dagilimi: { ready: 1 },
      kapsanmayan: [],
      uyarilar: [],
    };
    const { rerender } = render(<KapsamPaneli ozet={ozet} caseSayisi={1} eskiSema />);
    expect(screen.getByTestId("kapsam-bos")).toHaveTextContent("eski şemayla üretildi");
    expect(screen.getByRole("cell", { name: "AC1" })).toBeInTheDocument();
    expect(screen.getByText("Öğe kapsamı").parentElement).toHaveTextContent("hesaplanamadı");
    expect(screen.getByText("Teknik bilgisi olan case yok.")).toBeInTheDocument();
    expect(screen.queryByTestId("kapsam-acik-sorular")).not.toBeInTheDocument();
    // Özeti olan ama listeleri boş üretim: bölümler boş durum metniyle çizilir.
    const bosUretim = { uretim_no: 1, kanal: "portal", tur: "uretim", open_questions: [], assumptions: [], coverage_items: [], negative_coverage: [], not_covered: [], observations: [], automation_open_points: [], config_matrix: { parameters: [], constraints: [] }, testability_gaps: [] };
    rerender(<KapsamPaneli ozet={{ ...ozet, uretimler: [bosUretim] }} caseSayisi={1} />);
    expect(screen.queryByTestId("kapsam-bos")).not.toBeInTheDocument();
    expect(screen.getByText("Açık soru yok.")).toBeInTheDocument();
    expect(screen.getByText("Varsayım yok.")).toBeInTheDocument();
    expect(screen.getByText("Negatif kapsam kararı yok.")).toBeInTheDocument();
    expect(screen.getByText(/Her kabul kriteri ve kapsam öğesi en az bir case tarafından kapsanıyor/)).toBeInTheDocument();
  });
});

describe("yayın önizleme: hazır olmayan onaylı case", () => {
  it("blocked_not_ready engelini nedeniyle gösterir; seçilemez", async () => {
    await oturumAc("analist");
    // K6 öncesi kayıt: örnek veride onaylı case hep hazırdır (UX-10); eski kaydı burada kurarız.
    const eski = mockVerisi().caseler.find((c) => c.id === "case-v3-6")!;
    Object.assign(eski, { durum: "approved", karar: "approve", karar_veren: "analist", onaylanan_hash: eski.icerik_hash });
    uygulama(`/gereksinimler/${V3_GEREKSINIM_ID}/yayin`);
    const satir = within((await screen.findByText(/Türkçe karakterli 250 karakterlik not eksiksiz görünür/)).closest("tr")!);
    expect(satir.getByText("Yayınlanamaz: hazır değil")).toBeInTheDocument();
    expect(satir.getByTestId("yayin-engel-nedeni")).toHaveTextContent("Case hazır değil (varsayıma bağlı); yalnız hazır case yayınlanır.");
    expect(satir.getByRole("checkbox")).toBeDisabled();
    expect(screen.getByRole("button", { name: /Seçilenleri yayınla \(0\)/ })).toBeDisabled();
  });

  it("uyarlama: neden metni ve yeni işlem değerleri korunur; bilinmeyen işlem güvenli tarafa düşer", () => {
    const o = yayinOnizlemeUyarla({
      requirement_id: "r",
      hedef: "jira",
      proje: "TPD",
      kalemler: [
        { case_id: "a", title: "A", islem: "blocked_not_ready", neden: "Hazır değil: açık soru bekliyor", readiness: "blocked" },
        { case_id: "b", title: "B", islem: "blocked_gate", neden: "Denetim kararı yok" },
        { case_id: "c", title: "C", islem: "blocked_requirement_changed" },
        { case_id: "d", title: "D", islem: "ileride_eklenen" },
      ],
    });
    expect(o.kalemler.map((k) => [k.islem, k.neden])).toEqual([
      ["blocked_not_ready", "Hazır değil: açık soru bekliyor"],
      ["blocked_gate", "Denetim kararı yok"],
      ["blocked_requirement_changed", null],
      ["blocked_not_approved", null],
    ]);
  });
});

describe("yanıt uyarlaması ve kurallar", () => {
  it("eski içerikte v3 anahtarı üretilmez; v3 içerikte eksik alanlar tamamlanır", () => {
    expect(Object.keys(caseIcerikUyarla(ESKI_ICERIK)).sort()).toEqual(Object.keys(ESKI_ICERIK).sort());
    const v3 = caseIcerikUyarla({ ...ESKI_ICERIK, readiness: "blocked", open_question_refs: ["Q1"], test_data: [{ name: "x", value: 5, is_attack_payload: true }] });
    expect(v3).toMatchObject({ readiness: "blocked", technique: [], covers: [], assumption_refs: [], teardown: [], test_level: null, platform: null });
    expect(v3.test_data).toEqual([{ name: "x", value: "5", class: null, synthetic: true, is_attack_payload: true }]);
  });

  it("case: core alanları (readiness, legacy, atıflar, onay_engeli) okunur; yoksa içerikten türetilir", () => {
    const eski = caseUyarla({ id: "c1", icerik: ESKI_ICERIK });
    expect([eski.readiness, eski.legacy, eski.acik_sorular, eski.onay_engeli]).toEqual(["ready", true, undefined, undefined]);
    const yeni = caseUyarla({
      id: "c2",
      icerik: { ...ESKI_ICERIK, readiness: "blocked", open_question_refs: ["Q1"] },
      readiness: "blocked",
      legacy: false,
      uretim_no: 2,
      acik_sorular: [{ id: "Q1", question: "Soru?", owner: "PO" }],
      varsayimlar: [],
      onay_engeli: "Hazır olmayan case onaylanamaz",
      uyarilar: ["u"],
    });
    expect(yeni).toMatchObject({ readiness: "blocked", legacy: false, uretim_no: 2, acik_sorular: [{ id: "Q1", question: "Soru?", owner: "PO" }], varsayimlar: [], onay_engeli: "Hazır olmayan case onaylanamaz" });
  });

  it("case-summary: core biçimi okunur; eksik alanlar boş değere tamamlanır; nesne olmayan yanıt null", () => {
    expect(caseKapsamOzetiUyarla(null)).toBeNull();
    expect(caseKapsamOzetiUyarla({ requirement_id: "r" })).toEqual({
      requirement_id: "r",
      uretimler: [],
      kapsam_matrisi: [],
      oranlar: {
        gereksinim_kapsami: { kapsanan: null, toplam: null, oran: null },
        oge_kapsami: { kapsanan: null, toplam: null, oran: null },
        negatif_karar_kapsami: { kapsanan: null, toplam: null, oran: null },
      },
      teknik_dagilimi: {},
      readiness_dagilimi: {},
      kapsanmayan: [],
      uyarilar: [],
    });
    const o = caseKapsamOzetiUyarla({
      requirement_id: "r",
      uretimler: [{ uretim_no: 2, kanal: "portal", tur: "negatif", ozet_var: true, open_questions: [{ id: "Q1", question: "S?", owner: "PO" }], coverage_items: [{ id: "EP-I1", ac_ref: null, definition: "d", valid: false }] }],
      kapsam_matrisi: [
        { item: "EP-I1", tur: "oge", tanim: "d", valid: false, ac_ref: null, karar: "tested", covered_by: [3], covered_by_cases: [{ id: "x", sira_no: 3, uretim_no: 2, title: "Başlık" }], gerekce: null },
      ],
      oranlar: { gereksinim_kapsami: { kapsanan: 1, toplam: 2, oran: 0.5 }, oge_kapsami: 1, negatif_karar_kapsami: { kapsanan: 0, toplam: 0, oran: null } },
      teknik_dagilimi: { EP: 2 },
      readiness_dagilimi: { ready: 1, blocked: 1 },
      kapsanmayan: [{ item: "AC2", tur: "ac", tanim: "t", valid: null, karar: null, gerekce: null }],
      uyarilar: ["u"],
    })!;
    expect(o.uretimler[0]).toMatchObject({ uretim_no: 2, tur: "negatif", ozet_var: true, assumptions: [], not_covered: [], config_matrix: { parameters: [], constraints: [] } });
    expect(o.kapsam_matrisi[0]).toMatchObject({ item: "EP-I1", tur: "oge", valid: false, covered_by: [3], karar: "tested", ac_ref: null, kapsayanlar: [{ id: "x", sira_no: 3, uretim_no: 2, title: "Başlık" }] });
    expect(o.kapsanmayan).toEqual([{ item: "AC2", tur: "ac", tanim: "t", karar: null, gerekce: "" }]);
    // Oran nesnesi okunur; yalın sayı (eski biçim) da kabul edilir.
    expect(o.oranlar).toEqual({
      gereksinim_kapsami: { kapsanan: 1, toplam: 2, oran: 0.5 },
      oge_kapsami: { kapsanan: null, toplam: null, oran: 1 },
      negatif_karar_kapsami: { kapsanan: 0, toplam: 0, oran: null },
    });
  });

  it("hata listesi: core 'mesaj — [..]' biçimi ve '; ' ile birleşmiş liste maddelere ayrılır", () => {
    expect(hataListesi('Şemaya uymuyor — ["a", "b"]')).toEqual({ baslik: "Şemaya uymuyor", maddeler: ["a", "b"] });
    expect(hataListesi("bir; iki")).toEqual({ baslik: "", maddeler: ["bir", "iki"] });
    expect(hataListesi("Tek hata — açıklama")).toEqual({ baslik: "Tek hata — açıklama", maddeler: [] });
    expect(hataListesi(null)).toEqual({ baslik: "", maddeler: [] });
  });

  it("hazır olma kuralları (§4.2 kural 4–6)", () => {
    const temel = caseIcerikUyarla({ ...ESKI_ICERIK, readiness: "ready", technique: ["EP"], covers: ["EP-V1"] });
    expect(hazirlikSorunlari(ESKI_ICERIK)).toEqual([]);
    expect(hazirlikSorunlari(temel)).toEqual([]);
    expect(hazirlikSorunlari({ ...temel, open_question_refs: ["Q1"] })).toHaveLength(1);
    expect(hazirlikSorunlari({ ...temel, readiness: "assumption_dependent" })[0]).toMatch(/en az bir varsayıma atıf/);
    expect(hazirlikSorunlari({ ...temel, readiness: "blocked", open_question_refs: ["Q1"] })[0]).toMatch(/beklenen sonucu boş olmalı/);
    expect(hazirlikSorunlari({ ...temel, readiness: "blocked", open_question_refs: ["Q1"], expected_result: "" })).toEqual([]);
    expect(hazirlikSorunlari({ ...temel, test_data: [{ name: "v", value: "1", class: null, synthetic: false, is_attack_payload: false }] })[0]).toMatch(/sentetik olmalı/);
    // Saldırı verisinin değeri başka alanda geçemez (kural 6).
    const sizinti = { ...temel, title: "Not <b>x</b> ile", test_data: [{ name: "v", value: "<b>x</b>", class: null, synthetic: true, is_attack_payload: true }] };
    expect(tutarlilikSorunlari(sizinti)[0]).toMatch(/Güvenlik testi girdisi "v" değeri başka alanda geçemez/);
  });
});
