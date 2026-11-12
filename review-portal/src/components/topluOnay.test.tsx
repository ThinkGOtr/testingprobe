// D5 / A2: "Neden onaylanamıyor" kutusu (UX-2), K20 "Varsayım doğrulandı" ve toplu onay, "Hazır değil"
// süzgeci ve URL parametreleri (UX-6), derinleştirme rozeti (UX-5), kart başlığı sadeliği (UX-12),
// kapsam matrisi etiketleri ve hazır kapsam (UX-13 / D3), örnek verinin K6 tutarlılığı (UX-10).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import { V3_GEREKSINIM_ID } from "../api/mock/caseV3";
import { ICERIK_DEGISMIS, mockVerisi } from "../api/mock/handlers";
import type { CaseKapsamOzeti, TestCase } from "../api/types";
import { OturumProvider } from "../auth";
import { caseHazirlik, hazirlikYonlendirmesi, sayiEki, topluOnayEngeli } from "../lib/caseV3";
import { oturumAc, sar } from "../test/yardimci";
import { BildirimProvider } from "./Bildirim";
import { PoyaGonderEylemi } from "./AcikSorular";
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

const SAYFA = `/gereksinimler/${V3_GEREKSINIM_ID}/caseler`;

async function v3Case(id: string): Promise<TestCase> {
  return (await api.caseler(V3_GEREKSINIM_ID)).find((c) => c.id === id)!;
}

const ham = (id: string) => mockVerisi().caseler.find((c) => c.id === id)!;

/** Örnek v3 gereksinimi serbest metindir (story yok); PO'ya gönderim Jira story'si ister. */
function jiraStorysiVer(anahtar = "TPD-9") {
  mockVerisi().gereksinimler.find((g) => g.id === V3_GEREKSINIM_ID)!.jira_key = anahtar;
}

/** Kart başlığından makaleyi bulur. */
async function kart(baslik: string | RegExp) {
  return within((await screen.findByRole("heading", { name: baslik })).closest("article")!);
}

describe("sayıya Türkçe ek", () => {
  it("belirtme ve tamlayan ekleri okunuşa göre", () => {
    expect([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 40, 100, 1000].map((n) => sayiEki(n, "belirtme"))).toEqual([
      "1'i", "2'yi", "3'ü", "4'ü", "5'i", "6'yı", "7'yi", "8'i", "9'u", "10'u", "20'yi", "40'ı", "100'ü", "1000'i",
    ]);
    expect([1, 2, 3, 6, 9, 10, 12].map((n) => sayiEki(n, "tamlayan"))).toEqual(["1'in", "2'nin", "3'ün", "6'nın", "9'un", "10'un", "12'nin"]);
  });
});

describe("Neden onaylanamıyor kutusu (UX-2)", () => {
  it("metinler: tek varsayım, çok varsayım, soru (+varsayım), tutarlılık; onaylı ve hazır case'te kutu yok", async () => {
    await oturumAc("analist");
    jiraStorysiVer();
    const varsayim = await v3Case("case-v3-2");
    expect(hazirlikYonlendirmesi(varsayim)).toEqual({
      tur: "varsayim",
      metin: "A1 varsayımı doğrulanmadı. Doğruladıysanız 'Varsayım doğrulandı' ile onaylayın; değilse 'Düzelt' ile beklenen sonucu güncelleyin ya da reddedin.",
      dogrulanacak: ["A1"],
    });
    const cok = { ...varsayim, icerik: { ...varsayim.icerik, assumption_refs: ["A1", "A2"] } };
    expect(hazirlikYonlendirmesi(cok)!.metin).toMatch(/^A1, A2 varsayımları doğrulanmadı\. Doğruladıysanız 'Varsayımlar doğrulandı' ile onaylayın/);
    const soru = await v3Case("case-v3-3");
    expect(hazirlikYonlendirmesi(soru)).toEqual({
      tur: "soru",
      metin: "Q1 PO'nun yanıtını bekliyor ve henüz gönderilmedi; 'Açık soruları PO'ya gönder' ile gönderin, yanıt gelince 'Düzelt' ile beklenen sonucu yazın.",
      dogrulanacak: [],
      duzeltBirincil: false,
    });
    const ikisi = { ...soru, icerik: { ...soru.icerik, assumption_refs: ["A1"] } };
    const y = hazirlikYonlendirmesi(ikisi)!;
    expect(y.dogrulanacak).toEqual([]);
    expect(y.metin.startsWith("Q1 PO'nun yanıtını bekliyor")).toBe(true);
    expect(y.metin).toContain("A1 varsayımına bağlı");
    const tutarsiz = { ...(await v3Case("case-v3-1")), onay_engeli: "Tutarlılık ihlali olan case onaylanamaz" };
    expect(hazirlikYonlendirmesi(tutarsiz)!.metin).toBe("Tutarlılık ihlali olan case onaylanamaz. 'Düzelt' ile giderin ya da reddedin.");
    expect(hazirlikYonlendirmesi(await v3Case("case-v3-1"))).toBeNull();
    expect(hazirlikYonlendirmesi(await v3Case("case-v3-5"))).toBeNull();
  });

  it("kartta: varsayımda 'Varsayım doğrulandı' düğmesi; soruda düğme yok ve D6 yuvası çizilir", async () => {
    await oturumAc("analist");
    jiraStorysiVer();
    const { unmount } = sar(<CaseKarti tc={await v3Case("case-v3-2")} guncellendi={() => {}} />);
    const kutu = within(screen.getByTestId("hazirlik-yonlendirme"));
    expect(kutu.getByText("Neden onaylanamıyor, ne yapmalı?")).toBeInTheDocument();
    expect(kutu.getByTestId("hazirlik-yonlendirme-metin")).toHaveTextContent(/^A1 varsayımı doğrulanmadı\./);
    await waitFor(() => expect(kutu.getByRole("button", { name: "Varsayım doğrulandı" })).toBeEnabled());
    // Kutu kartın üstünde: başlık satırından hemen sonra, case başlığından önce.
    const sira = [screen.getByTestId("hazirlik-yonlendirme"), screen.getByRole("heading", { name: /251 karakterlik/ })];
    expect(sira[0].compareDocumentPosition(sira[1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    unmount();

    sar(<CaseKarti tc={await v3Case("case-v3-3")} guncellendi={() => {}} poyaGonder={<button type="button">PO'ya gönder</button>} />);
    const soru = within(screen.getByTestId("hazirlik-yonlendirme"));
    expect(soru.getByTestId("hazirlik-yonlendirme-metin")).toHaveTextContent("Q1 PO'nun yanıtını bekliyor ve henüz gönderilmedi; 'Açık soruları PO'ya gönder' ile gönderin, yanıt gelince 'Düzelt' ile beklenen sonucu yazın.");
    expect(soru.queryByRole("button", { name: /Varsayım/ })).not.toBeInTheDocument();
    expect(soru.getByRole("button", { name: "PO'ya gönder" })).toBeInTheDocument();
  });

  it("çok varsayımda düğme adı kimlikleri taşır", async () => {
    await oturumAc("analist");
    const tc = await v3Case("case-v3-2");
    sar(<CaseKarti tc={{ ...tc, icerik: { ...tc.icerik, assumption_refs: ["A1", "A2"] } }} guncellendi={() => {}} />);
    expect(screen.getByRole("button", { name: "Varsayımlar doğrulandı (A1, A2)" })).toBeInTheDocument();
  });
});

describe("Varsayım doğrulandı (K20)", () => {
  it("görülen hash ile gönderilir; case onaylı + hazır döner; bildirim gösterilir", async () => {
    await oturumAc("analist");
    const spy = vi.spyOn(api, "varsayimDogrulandi");
    const guncellendi = vi.fn();
    const u = userEvent.setup();
    const tc = await v3Case("case-v3-2");
    sar(<CaseKarti tc={tc} guncellendi={guncellendi} />);
    await u.click(screen.getByRole("button", { name: "Varsayım doğrulandı" }));
    const onay = within(screen.getByTestId("varsayim-dogrulama-onayi"));
    await u.type(onay.getByLabelText("Doğrulama notu (isteğe bağlı)"), "PO ile teyit edildi");
    await u.click(onay.getByRole("button", { name: "Evet, doğrulandı — onayla" }));
    await waitFor(() => expect(guncellendi).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith("case-v3-2", { icerik_hash: tc.icerik_hash, varsayim_id: "A1", gerekce: "PO ile teyit edildi" });
    const yeni = guncellendi.mock.calls[0][0] as TestCase;
    expect([yeni.durum, yeni.readiness, yeni.karar]).toEqual(["approved", "ready", "edit"]);
    expect(yeni.icerik.assumption_refs).toEqual([]);
    expect(yeni.icerik.expected_result).toBe(tc.icerik.expected_result);
    expect(await screen.findByText("Case #2 onaylandı: A1 varsayımı doğrulandı.")).toBeInTheDocument();
    spy.mockRestore();
  });

  it("mock: başka atıf kalırsa 422 (Türkçe), bayat hash 409, atıf yapılmayan varsayım 422", async () => {
    await oturumAc("analist");
    const c = ham("case-v3-6");
    c.icerik = { ...c.icerik, open_question_refs: ["Q1"] };
    const tc = await v3Case("case-v3-6");
    await expect(api.varsayimDogrulandi(tc.id, { icerik_hash: tc.icerik_hash, varsayim_id: "A1" })).rejects.toSatisfy(
      (e: unknown) => e instanceof ApiError && e.status === 422 && e.message.includes("Case'in başka varsayımı/sorusu var (Q1); önce onları çözün ya da 'Düzelt' kullanın"),
    );
    const iki = await v3Case("case-v3-2");
    await expect(api.varsayimDogrulandi(iki.id, { icerik_hash: "bayat", varsayim_id: "A1" })).rejects.toSatisfy((e: unknown) => e instanceof ApiError && e.status === 409);
    await expect(api.varsayimDogrulandi(iki.id, { icerik_hash: iki.icerik_hash, varsayim_id: "A9" })).rejects.toSatisfy((e: unknown) => e instanceof ApiError && e.status === 422);
    expect(ham("case-v3-2").durum).toBe("draft");
  });

  it("409'da liste yeniden yüklenir (cakismada)", async () => {
    await oturumAc("analist");
    const yenile = vi.fn();
    const u = userEvent.setup();
    const tc = await v3Case("case-v3-2");
    ham("case-v3-2").icerik_hash = "baskasi-degistirdi";
    sar(<CaseKarti tc={tc} guncellendi={() => {}} yenile={yenile} />);
    await u.click(screen.getByRole("button", { name: "Varsayım doğrulandı" }));
    await u.click(screen.getByRole("button", { name: "Evet, doğrulandı — onayla" }));
    await waitFor(() => expect(yenile).toHaveBeenCalled());
  });
});

describe("toplu onay (K20)", () => {
  it("seçim kuralları: yalnız hazır, tutarlı taslak; karar verilmişte kutu yok; seçilemeyende neden görünür", async () => {
    await oturumAc("analist");
    const tumu = await api.caseler(V3_GEREKSINIM_ID);
    expect(tumu.filter((c) => topluOnayEngeli(c) === null).map((c) => c.sira_no)).toEqual([1, 4]);
    expect(topluOnayEngeli({ ...tumu[0], onay_engeli: "Tutarlılık ihlali olan case onaylanamaz" })).toBe("Tutarlılık ihlali var");

    uygulama(SAYFA);
    const tumuSec = await screen.findByRole("checkbox", { name: "Tümünü seç (seçilebilir 2)" });
    expect(tumuSec).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Case 1'i seç: 250 karakterlik not siparişle birlikte kaydedilir" })).toBeEnabled();
    const ikinci = screen.getByRole("checkbox", { name: "Case 2'yi seç: 251 karakterlik not kaydedilmez" });
    expect(ikinci).toBeDisabled();
    expect(ikinci).toHaveAccessibleDescription("Toplu onaya seçilemez: Hazır değil (Varsayıma bağlı)");
    // Onaylı case 5: kutu yok.
    const besinci = await kart("Başka bayinin sipariş notu görüntülenemez");
    expect(besinci.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("tümünü seç → onay kutusu → hepsi onaylanır; bildirim ve liste yenilenir", async () => {
    await oturumAc("analist");
    const spy = vi.spyOn(api, "topluOnay");
    const u = userEvent.setup();
    uygulama(SAYFA);
    await u.click(await screen.findByRole("checkbox", { name: "Tümünü seç (seçilebilir 2)" }));
    expect(screen.getByText("2 case seçildi")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Seçilenleri onayla" }));
    const onay = within(screen.getByTestId("toplu-onay-onayi"));
    expect(onay.getByText(/2 case kendi görülen içerikleriyle ayrı ayrı onaylanacak/)).toBeInTheDocument();
    await u.click(onay.getByRole("button", { name: "Evet, 2 case'i onayla" }));
    expect(await screen.findByText("2 case onaylandı")).toBeInTheDocument();
    expect(spy.mock.calls[0][0]).toEqual([
      { case_id: "case-v3-1", icerik_hash: ham("case-v3-1").onaylanan_hash },
      { case_id: "case-v3-4", icerik_hash: ham("case-v3-4").onaylanan_hash },
    ]);
    expect([ham("case-v3-1").durum, ham("case-v3-4").durum]).toEqual(["approved", "approved"]);
    // Liste yenilendi: onaylanan case'lerin kutusu kalktı.
    await waitFor(() => expect(screen.queryByRole("checkbox", { name: /^Case 1'i seç/ })).not.toBeInTheDocument());
    spy.mockRestore();
  });

  it("karışık sonuç: '1 onaylandı, 1 onaylanamadı' ve kalem hatası case başlığıyla listelenir", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama(SAYFA);
    await u.click(await screen.findByRole("checkbox", { name: /^Case 1'i seç/ }));
    await u.click(screen.getByRole("checkbox", { name: /^Case 4'ü seç/ }));
    await u.click(screen.getByRole("button", { name: "Seçilenleri onayla" }));
    // Görüntülendikten sonra case 4 başkası tarafından değişti: kalem 409.
    ham("case-v3-4").icerik_hash = "baskasi-degistirdi";
    await u.click(screen.getByRole("button", { name: "Evet, 2 case'i onayla" }));
    const sonuc = within(await screen.findByTestId("toplu-onay-sonuc"));
    expect(sonuc.getByText("1 onaylandı, 1 onaylanamadı")).toBeInTheDocument();
    expect(sonuc.getByRole("listitem")).toHaveTextContent(`#4 Nottaki betik sipariş detayında çalıştırılmaz: ${ICERIK_DEGISMIS}`);
    expect([ham("case-v3-1").durum, ham("case-v3-4").durum]).toEqual(["approved", "draft"]);
  });

  it("mock: kalem bazlı sonuç (hazır değil 422, bayat hash 409); her kalem ayrı karar", async () => {
    await oturumAc("analist");
    const [c1, c2, , c4] = await api.caseler(V3_GEREKSINIM_ID);
    const s = await api.topluOnay([
      { case_id: c1.id, icerik_hash: c1.icerik_hash },
      { case_id: c2.id, icerik_hash: c2.icerik_hash },
      { case_id: c4.id, icerik_hash: "bayat" },
    ]);
    expect([s.onaylanan, s.basarisiz]).toEqual([1, 2]);
    expect(s.sonuclar.map((k) => [k.case_id, k.basarili, k.kod])).toEqual([
      ["case-v3-1", true, null],
      ["case-v3-2", false, 422],
      ["case-v3-4", false, 409],
    ]);
    expect(s.sonuclar[0].case?.durum).toBe("approved");
    expect(s.sonuclar[1].hata).toMatch(/Hazır olmayan case onaylanamaz/);
  });
});

describe("case listesi süzgeçleri (UX-6)", () => {
  it("?filtre=hazir-degil: sekme seçili, yalnız hazır olmayan case'ler", async () => {
    await oturumAc("analist");
    uygulama(`${SAYFA}?filtre=hazir-degil`);
    const sekme = await screen.findByRole("button", { name: "Hazır değil (3)" });
    expect(sekme).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(document.querySelectorAll("article.case")).toHaveLength(3));
    expect(screen.queryByRole("heading", { name: "250 karakterlik not siparişle birlikte kaydedilir" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Hepsi (6)" }));
    await waitFor(() => expect(document.querySelectorAll("article.case")).toHaveLength(6));
  });

  it("?uretim=2: o üretimin case'leri, açıklama ve 'Tümünü göster'; derinleştirme rozeti", async () => {
    await oturumAc("analist");
    ham("case-v3-4").uretim_no = 2;
    mockVerisi().caseUretimleri![V3_GEREKSINIM_ID].push({ ...mockVerisi().caseUretimleri![V3_GEREKSINIM_ID][0], uretim_no: 2, tur: "negatif" });
    uygulama(`${SAYFA}?uretim=2`);
    expect(await screen.findByTestId("case-suzgec")).toHaveTextContent("Üretim 2'nin case'leri gösteriliyor");
    await waitFor(() => expect(document.querySelectorAll("article.case")).toHaveLength(1));
    const k = await kart("Nottaki betik sipariş detayında çalıştırılmaz");
    expect(await k.findByTestId("case-uretim-rozeti")).toHaveTextContent("Negatif genişletme · üretim 2");
    await userEvent.click(screen.getByRole("button", { name: "Tümünü göster" }));
    await waitFor(() => expect(document.querySelectorAll("article.case")).toHaveLength(6));
    expect(screen.queryByTestId("case-suzgec")).not.toBeInTheDocument();
  });

  it("kapsam panelindeki dağılım rozeti listeyi süzer", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama(SAYFA);
    await u.click(await screen.findByRole("button", { name: "Soru bekliyor: 1 case — listeyi bu duruma süz" }));
    expect(await screen.findByTestId("case-suzgec")).toHaveTextContent('Hazır olma durumu "Soru bekliyor" olan case\'ler gösteriliyor');
    await waitFor(() => expect(document.querySelectorAll("article.case")).toHaveLength(1));
    await u.click(screen.getByRole("button", { name: /^EP \(eşdeğerlik bölümleme\): 4 case/ }));
    expect(await screen.findByTestId("case-suzgec")).toHaveTextContent("EP (eşdeğerlik bölümleme) tekniğini kullanan case'ler");
  });
});

describe("case kartı sadeliği (UX-12) ve derinleştirme rozeti (UX-5)", () => {
  it("başlıkta yalnız durum, hazır olma ve öncelik; tür/teknik listede; v3'te risk yok, eski case'te var", async () => {
    await oturumAc("analist");
    const { container, unmount } = sar(<CaseKarti tc={await v3Case("case-v3-1")} guncellendi={() => {}} />);
    const baslik = container.querySelector("header.case-baslik")!;
    expect([...baslik.querySelectorAll(".cip")].map((c) => c.textContent)).toEqual(["Karar bekliyor", "Hazır olma durumu: ✓ Hazır", "P1 (Öncelik 1, en yüksek)"]);
    const ozellik = within(screen.getByTestId("case-ozellikler"));
    expect(ozellik.getByText("Tür").nextElementSibling).toHaveTextContent("Sınır");
    expect(ozellik.queryByText("Risk")).not.toBeInTheDocument();
    expect(ozellik.getByText("Teknikler").nextElementSibling).toHaveTextContent(/EP/);
    unmount();

    const eski = await v3Case("case-v3-1");
    const { readiness: _r, ...icerik } = { ...eski.icerik, readiness: undefined };
    sar(<CaseKarti tc={{ ...eski, legacy: true, readiness: undefined, icerik: icerik as TestCase["icerik"] }} guncellendi={() => {}} />);
    expect(within(screen.getByTestId("case-ozellikler")).getByText("Risk").nextElementSibling).toHaveTextContent("Yüksek risk");
  });

  it("üretim türü rozeti: negatif/teknik var, ilk üretimde yok", async () => {
    await oturumAc("analist");
    const tc = { ...(await v3Case("case-v3-1")), uretim_no: 3 };
    const { rerender } = sar(<CaseKarti tc={tc} guncellendi={() => {}} uretimTuru="teknik" />);
    expect(screen.getByTestId("case-uretim-rozeti")).toHaveTextContent("Teknik derinleştirme · üretim 3");
    rerender(
      <MemoryRouter>
        <OturumProvider>
          <BildirimProvider>
            <CaseKarti tc={{ ...tc, uretim_no: 1 }} guncellendi={() => {}} uretimTuru="uretim" />
          </BildirimProvider>
        </OturumProvider>
      </MemoryRouter>,
    );
    expect(screen.queryByTestId("case-uretim-rozeti")).not.toBeInTheDocument();
  });

  it("onaylı kartta varsayım başlığı 'Dayandığı varsayımlar'", async () => {
    await oturumAc("analist");
    const tc = await v3Case("case-v3-2");
    sar(<CaseKarti tc={{ ...tc, durum: "approved", karar: "approve" }} guncellendi={() => {}} />);
    expect(within(screen.getByTestId("case-varsayimlar")).getByText("Dayandığı varsayımlar")).toBeInTheDocument();
  });
});

describe("kapsam matrisi (UX-13, D3)", () => {
  it("hazır case kapsamı satırda ve oranlarda; 'hazır case yok' uyarısı", async () => {
    await oturumAc("analist");
    uygulama(SAYFA);
    const matris = within(await screen.findByRole("region", { name: "Kapsam matrisi tablosu" }));
    const satir = (oge: string) => within(matris.getByRole("cell", { name: oge }).closest("tr")!);
    // BV-1: #1 (hazır) ve #6 (varsayıma bağlı) kapsar.
    expect(satir("BV-1").getByTestId("kapsam-hazir-case")).toHaveTextContent("hazır case: 1");
    // EP-I2 yalnız #3 (soru bekliyor) ile kapsanır.
    expect(satir("EP-I2").getByTestId("kapsam-hazir-case")).toHaveTextContent("⚠ hazır case yok");
    expect(satir("EP-I2").getByText(/Negatif case ile test edilir/)).toBeInTheDocument();
    expect(satir("EG-3").getByText("Kapsam dışı (gerekçeli)")).toBeInTheDocument();
    const oranlar = within(screen.getByTestId("kapsam-oranlar"));
    expect(oranlar.getByText("Hazır case'lerle öğe kapsamı")).toBeInTheDocument();
    expect(oranlar.getByText("Hazır case'lerle gereksinim kapsamı")).toBeInTheDocument();
  });

  it("alan yoksa (eski core) hazır kapsam gizli; gerekçesiz kapsanmayan uyarı; baslangictaAcik=false ayrıntıları kapatır", () => {
    const ozet: CaseKapsamOzeti = {
      requirement_id: "r",
      uretimler: [],
      kapsam_matrisi: [
        { item: "AC1", tur: "ac", tanim: "Ürün sepete eklenir", valid: null, covered_by: [1], gerekce: null },
        { item: "AC2", tur: "ac", tanim: "Sepet boşaltılır", valid: null, covered_by: [], gerekce: null },
      ],
      oranlar: { gereksinim_kapsami: { kapsanan: 1, toplam: 2, oran: 0.5 }, oge_kapsami: { kapsanan: 0, toplam: 0, oran: null }, negatif_karar_kapsami: { kapsanan: 0, toplam: 0, oran: null } },
      teknik_dagilimi: {},
      readiness_dagilimi: { ready: 1 },
      kapsanmayan: [],
      uyarilar: [],
    };
    const { rerender } = render(<KapsamPaneli ozet={ozet} caseSayisi={1} />);
    expect(screen.queryByTestId("kapsam-hazir-case")).not.toBeInTheDocument();
    expect(screen.queryByText(/Hazır case'lerle/)).not.toBeInTheDocument();
    expect(screen.getByText("⚠ Kapsanmıyor")).toBeInTheDocument();
    expect(screen.queryByTestId("kapsam-ayrintilar")).not.toBeInTheDocument();
    rerender(<KapsamPaneli ozet={ozet} caseSayisi={1} baslangictaAcik={false} />);
    expect(screen.getByTestId("kapsam-ayrintilar")).not.toHaveAttribute("open");
    expect(screen.getByTestId("kapsam-oranlar")).toBeInTheDocument();
  });
});

describe("örnek veri K6 tutarlılığı (UX-10)", () => {
  it("onaylı ya da yayınlanmış her case hazırdır", () => {
    const tutarsiz = mockVerisi().caseler.filter((c) => (c.durum === "approved" || c.durum === "published") && caseHazirlik(c) !== "ready");
    expect(tutarsiz.map((c) => c.id)).toEqual([]);
  });
});

describe("D6: soru bekleyen case'te metin PO durumuna göre (K16)", () => {
  it("gönderilmedi / gönderildi / yanıtlandı ve D6 alanı yokken eski metin", async () => {
    await oturumAc("analist");
    jiraStorysiVer();
    const soru = await v3Case("case-v3-3");
    const po = (d: "gonderilmedi" | "gonderildi" | "yanitlandi") => ({
      ...soru,
      po_sorulari: { Q1: { tur: "soru" as const, po_etiketi: "CQ1", po_durumu: d, po_yaniti: d === "yanitlandi" ? { metin: "Evet", yazar: "PO", zaman: null } : null } },
    });
    expect(hazirlikYonlendirmesi(po("gonderilmedi"))!.metin).toContain("'Açık soruları PO'ya gönder' ile gönderin");
    // B7: gönderilen soru PO'nun gördüğü kimlikle (CQ1) anılır; "Q1 (CQ1)" karışıklığı yok.
    expect(hazirlikYonlendirmesi(po("gonderildi"))!.metin).toBe("CQ1 PO'ya gönderildi, yanıt bekleniyor; yanıt gelince 'Düzelt' ile beklenen sonucu yazın.");
    // B3: yanıt gelince tek mesaj ve sıradaki eylem "Düzelt" (birincil).
    const yanit = hazirlikYonlendirmesi(po("yanitlandi"))!;
    expect(yanit.metin).toBe("CQ1: PO yanıtladı. 'Düzelt' ile beklenen sonucu yanıta göre yazın (ya da case'i yeniden üretin).");
    expect(yanit.duzeltBirincil).toBe(true);
    expect(hazirlikYonlendirmesi(po("gonderildi"))!.duzeltBirincil).toBe(false);
    const { po_sorulari: _p, ...eski } = soru;
    expect(hazirlikYonlendirmesi(eski)!.metin).toBe("Q1 PO'nun yanıtını bekliyor. Henüz gönderilmediyse 'Açık soruları PO'ya gönder' ile gönderin; yanıt gelince 'Düzelt' ile beklenen sonucu yazın.");
  });
});

describe("D5 × D6: kutudaki 'Açık soruları PO'ya gönder' eylemi", () => {
  it("gönderilmemiş soruda düğme; tıklanınca gereksinimin soruları gönderilir ve liste yenilenir; gönderildiyse düğme yok", async () => {
    await oturumAc("analist");
    jiraStorysiVer();
    const soru = (await api.caseler(V3_GEREKSINIM_ID)).find((c) => c.id === "case-v3-3")!;
    const spy = vi.spyOn(api, "acikSorulariGonder").mockResolvedValue({} as Awaited<ReturnType<typeof api.acikSorulariGonder>>);
    const yenile = vi.fn();
    const u = userEvent.setup();
    const gonderilmedi = { ...soru, po_sorulari: { Q1: { tur: "soru" as const, po_etiketi: "CQ1", po_durumu: "gonderilmedi" as const, po_yaniti: null } } };
    const { unmount } = sar(<CaseKarti tc={gonderilmedi} guncellendi={() => {}} poyaGonder={<PoyaGonderEylemi tc={gonderilmedi} tamamlandi={yenile} />} />);
    const kutu = within(screen.getByTestId("hazirlik-yonlendirme"));
    await u.click(await kutu.findByRole("button", { name: "Açık soruları PO'ya gönder" }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith(V3_GEREKSINIM_ID));
    await waitFor(() => expect(yenile).toHaveBeenCalled());
    unmount();
    const gonderildi = { ...soru, po_sorulari: { Q1: { tur: "soru" as const, po_etiketi: "CQ1", po_durumu: "gonderildi" as const, po_yaniti: null } } };
    sar(<CaseKarti tc={gonderildi} guncellendi={() => {}} poyaGonder={<PoyaGonderEylemi tc={gonderildi} />} />);
    expect(within(screen.getByTestId("hazirlik-yonlendirme")).queryByRole("button", { name: "Açık soruları PO'ya gönder" })).not.toBeInTheDocument();
    spy.mockRestore();
  });
});
