// 012 review turu 2 (u2, onyüz 21/22, g2 O2, koordinatör ekran turu): portal düzeltmelerinin testleri.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Rotalar } from "../../App";
import { api, hataKosusuApi } from "../../api/client";
import { ApiError } from "../../api/http";
import { mockVerisi } from "../../api/mock/handlers";
import { kaliteVerisi, tabloDogrula } from "../../api/mock/kalite";
import { kuleAyar, kuleMockIlerlet } from "../../api/mock/kule";
import { MIN_SIPARIS_DOGRU } from "../../api/mock/kaliteVerisi";
import type { KontrolKulesi as Kule, OracleKarsilastirma, TestCase } from "../../api/types";
import { kontrolKulesiUyarla } from "../../api/uyumDemoB";
import { OturumProvider } from "../../auth";
import { alintiMetni, ciktiyiOku, satiriOku, trAd } from "../../lib/ifadeAciklama";
import { isleriBekle, t2Duzelt, t2Onayla } from "../../test/kaliteYardimci";
import { oturumAc, sar } from "../../test/yardimci";
import { BildirimProvider } from "../Bildirim";
import { CaseKarti } from "../CaseKarti";
import { ayirtEdiciGirdi, HataKosusuKarti, turetmeOnerisi } from "../kule/HataKosusuKarti";
import { HataYakalamaKarosu, OnayliUyumsuzKarti } from "../kule/KaliteKpilari";
import { damgaAlani, karsilastirilamamaNedeni, KarsilastirmaTablosu, ozetMetni } from "./oracle";
import { OrnekIzgarasi, sayiDegeri } from "./OrnekIzgarasi";
import { caseOracleYanitiUyarla } from "../../api/uyumKalite";
import { icerikFarklari } from "./ortak";

const REQ = "req-tpd-1";
const YOL = `/gereksinimler/${REQ}/karar-tablolari`;

function uygulama(yol: string): ReturnType<typeof render> {
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
const kart = async (ad: RegExp) => screen.findByRole("region", { name: ad });
const kule = (ek: Record<string, unknown>): Kule => kontrolKulesiUyarla({ gecme_orani: { oran: 1, toplam: 1, gecen: 1 }, ai_katkisi: {}, ...ek });
const yalin = (ui: ReactElement) => sar(ui);

describe("u2 N8, N18 + koordinatör 1: iş dili ve alıntı", () => {
  it("Türkçe adlar, çıktı anlamı açıklamadan, mantıksal çıktı 'uyarı görünür/görünmez'", () => {
    expect(trAd("sepet_tutari")).toBe("sepet tutarı");
    expect(trAd("kampanyali_sepet")).toBe("kampanyalı sepet");
    expect(ciktiyiOku({ ad: "indirim", aciklama: "Bedava adetlerin tutarı (kampanya indirimi)" }, "yuvarla(ara_toplam / adet * (adet // 7), 2)")).toBe(
      "indirim = bedava adetlerin tutarı, kuruşa yuvarlanır",
    );
    expect(ciktiyiOku({ ad: "bedava_adet" }, "adet // 7")).toBe("bedava adet = adet ÷ 7 (tam kısım)");
    expect(ciktiyiOku({ ad: "minimum_uyarisi", tur: "mantiksal" }, "dogru")).toBe("uyarı görünür");
    expect(satiriOku("sepet_tutari < 750", { minimum_uyarisi: "dogru" }, [{ ad: "minimum_uyarisi", tur: "mantiksal" }])).toBe(
      "Eğer sepet tutarı 750'den az → uyarı görünür",
    );
    // Açıklamasız uzun ifade: formül okunur (anlam uydurulmaz).
    expect(ciktiyiOku({ ad: "x" }, "yuvarla(a / b, 2)")).toBe("x = yuvarla(a ÷ b, 2)");
  });

  it("özet cümlesinde bitişik tırnak çifti teke iner", () => {
    expect(ozetMetni('2 beklenen değer tabloyla uyuşmuyor; ör. minimum_uyarisi: case “"Minimum sipariş tutarı 750,00 TL" uyarısı görünür”, tablo yanlış.')).toBe(
      '2 beklenen değer tabloyla uyuşmuyor; ör. minimum_uyarisi: case "Minimum sipariş tutarı 750,00 TL" uyarısı görünür, tablo yanlış.',
    );
    expect(ozetMetni("ör. indirim: case “25,00 TL”, tablo 0.")).toBe("ör. indirim: case “25,00 TL”, tablo 0.");
  });

  it("alıntı zaten tırnakla başlıyorsa yeniden sarılmaz (““…” olmaz); karşılaştırmada mantıksal değer iş dilinde, satır T2 · R3", () => {
    expect(alintiMetni('"Minimum sipariş tutarı 750,00 TL" uyarısı görünür')).toBe('"Minimum sipariş tutarı 750,00 TL" uyarısı görünür');
    expect(alintiMetni("25,00 TL")).toBe("“25,00 TL”");
    const k: OracleKarsilastirma = {
      column: "minimum_uyarisi",
      alan: "steps[3].expected",
      alinti: '"Minimum sipariş tutarı 750,00 TL" uyarısı görünür',
      case_degeri: true,
      tablo_degeri: false,
      uyumlu: false,
      tablo_id: "kt-2",
      tablo_ad: "Minimum",
      satir_id: "R3",
    };
    yalin(<KarsilastirmaTablosu satirlar={[k]} baslik="Karşılaştırma" />);
    const satir = screen.getAllByRole("row")[1];
    expect(satir).toHaveTextContent('"Minimum sipariş tutarı 750,00 TL" uyarısı görünür');
    expect(satir.textContent).not.toContain("““");
    expect(within(satir).getByText("uyarı görünür")).toBeInTheDocument();
    expect(within(satir).getByText(/uyarı görünmez/)).toBeInTheDocument();
  });
});

describe("u2 N9: PO incelerken içerik değişirse satır farkı", () => {
  it("icerikFarklari: satır kimliğiyle yol, eski → yeni", () => {
    const yeni = { ...MIN_SIPARIS_DOGRU, satirlar: MIN_SIPARIS_DOGRU.satirlar.map((s) => (s.id === "R2" ? { ...s, kosul: "sepet_tutari <= 750" } : s)) };
    expect(icerikFarklari(MIN_SIPARIS_DOGRU, yeni)).toEqual([{ yol: "Satır R2 · koşul", once: "sepet_tutari < 750", sonra: "sepet_tutari <= 750" }]);
  });

  it("ekranda: 'İçerik siz bakarken değişti' kutusunda değişen satır vurgulu", async () => {
    await oturumAc("po");
    uygulama(YOL);
    const t2 = await kart(/T2 · Minimum sipariş/);
    expect(within(t2).getByRole("button", { name: "PO olarak onayla" })).toBeEnabled();
    // Analist geri çekip R2'yi düzeltti, yeniden gönderdi.
    await oturumAc("analist");
    const t = () => kaliteVerisi(mockVerisi()).tablolar.find((x) => x.id === "kt-2")!;
    await api.kararTablosuGecis("kt-2", "withdraw");
    await api.kararTablosuKaydet("kt-2", { icerik: { ...t().icerik, satirlar: MIN_SIPARIS_DOGRU.satirlar }, icerik_hash: t().icerik_hash });
    await api.kararTablosuGecis("kt-2", "submit", { icerik_hash: t().icerik_hash });
    await oturumAc("po");
    const { mockOlayYayinla } = await import("../../api/mock/olaylar");
    mockOlayYayinla({ type: "karar_tablosu.updated", id: "kt-2", data: { id: "kt-2", requirement_id: REQ, durum: "pending_po", eylem: "duzenle" } });
    const fark = await within(t2).findByTestId("kt-icerik-farki", undefined, { timeout: 3000 });
    expect(fark).toHaveTextContent("Satır R2 · koşul: sepet_tutari <= 750 → sepet_tutari < 750");
    expect(within(fark).getByText("sepet_tutari <= 750").tagName).toBe("DEL");
    expect(within(fark).getByText("sepet_tutari < 750").tagName).toBe("INS");
  });
});

describe("u2 N7, N12: Kule'den 'Bu girdiyle ek case türet'", () => {
  it("bağlantı parametreleri ilişkiyi ve C2'yi seçer, 'türetilecek girdi: adet 14' görünür; türetme 14 adetlik case üretir", async () => {
    await oturumAc("analist");
    uygulama(`${YOL}?iliski=mi-1&kaynak=case-1-2&girdi=adet+14#ek-case-turet`);
    const bolum = await screen.findByTestId("ek-case-turet");
    expect(await within(bolum).findByTestId("turet-onizleme")).toHaveTextContent("Kaçan hata için hazırlandı: İ1 ilişkisi, kaynak C2 · türetilecek girdi: adet 14");
    await waitFor(() => expect(within(bolum).getByLabelText(/^C2 7 adet/)).toBeChecked());
    // N12: kaynak listesi ilişkinin AC'siyle (AC2) süzülür — C1 (AC1) listede yok.
    expect(within(bolum).queryByLabelText(/^C1 /)).toBeNull();
    const turet = vi.spyOn(api, "ekCaseTuret");
    await userEvent.click(within(bolum).getByRole("button", { name: "Ek case türet" }));
    await within(bolum).findByTestId("turet-sonuc");
    expect(turet).toHaveBeenCalledWith(REQ, { iliski_id: "mi-1", case_ids: ["case-1-2"] });
    const yeni = mockVerisi().caseler.at(-1)!;
    expect(yeni.icerik.steps.map((s) => s.data).join(" ")).toContain("× 14");
    expect(yeni.icerik.expected_result).toMatch(/2 adet bedava|bedava adet 2/);
  });

  it("turetmeOnerisi: ayırt edici girdi (adet = 14) ↔ ilişki dönüşümü (adet * 2) → kaynak değeri 7 olan onaylı C2", async () => {
    await oturumAc("analist");
    const y = await api.kararTablolari(REQ);
    const cs = await api.caseler(REQ);
    const oneri = turetmeOnerisi(
      { kod: "kampanya_tek_bedava", ad: "x", tur: "kod", aciklama: "", yakalayan_kural: "", ac_refs: ["AC2"], tablo: "T1", ayirt_edici: { girdi: "adet = 14", dogru: "", hatali: "" } },
      y.iliskiler,
      cs,
    );
    expect(oneri).toMatchObject({ iliski: { id: "mi-1" }, kaynak: { id: "case-1-2" }, girdi: "adet 14" });
  });

  it("analist dışı rolde düğme 'Analiste ilet (kopyala)': istek + önerilen türetme + bağlantı panoya", async () => {
    await oturumAc("muhendis");
    const yaz = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText: yaz }, configurable: true });
    sar(<HataKosusuKarti />);
    const kacan = within(await screen.findByTestId("hk-kacan-kampanya_tek_bedava"));
    expect(kacan.queryByRole("link", { name: "Bu girdiyle ek case türet" })).toBeNull();
    const ilet = await kacan.findByRole("button", { name: "Analiste ilet (kopyala)" });
    await waitFor(() => expect(kacan.getByTestId("hk-turet-onizleme-kampanya_tek_bedava")).toBeInTheDocument());
    await userEvent.click(ilet);
    expect(yaz).toHaveBeenCalledWith(expect.stringMatching(/Önerilen türetme: adet 14 \(ilişki İ1, kaynak C2\)\. Bağlantı: .*karar-tablolari\?iliski=mi-1&kaynak=case-1-2&girdi=adet\+14#ek-case-turet$/));
  });
});

describe("u2 N11: AI olmayan case'te 'AI 0 ms' yazılmaz", () => {
  it("ilişkiden türetilen case: 'İlişkiden türetildi (model çağrısı yok)'", async () => {
    await oturumAc("analist");
    const c = mockVerisi().caseler.find((x) => x.id === "case-1-2")!;
    const tc: TestCase = { ...c, id: "case-t", ai_generated: false, ai_sure_ms: 0, mode: null, icerik: { ...c.icerik, tags: [...c.icerik.tags, "metamorfik"] } };
    sar(<CaseKarti tc={tc} guncellendi={() => {}} />);
    expect(await screen.findByText(/İlişkiden türetildi \(model çağrısı yok\)/)).toBeInTheDocument();
    expect(screen.queryByText(/AI 0 ms/)).toBeNull();
  });
});

describe("onyüz 21: satır kimliği hataları satıra bağlı", () => {
  it("mock: boş ve yinelenen satır kimliği `satirlar[i].id` yoluyla", () => {
    const h = tabloDogrula({ ...MIN_SIPARIS_DOGRU, satirlar: [MIN_SIPARIS_DOGRU.satirlar[0], { ...MIN_SIPARIS_DOGRU.satirlar[1], id: "R1" }, { ...MIN_SIPARIS_DOGRU.satirlar[2], id: "" }] });
    expect(h).toContain("satirlar[1].id: 'R1' kimliği birden çok satırda kullanılmış");
    expect(h).toContain("satirlar[2].id: satır kimliği boş olamaz");
  });

  it("ekranda: kimlik hatası satırın grubuna ve koşul alanına bağlı (aria-describedby + aria-invalid)", async () => {
    await oturumAc("analist");
    await api.kararTablosuGecis("kt-2", "withdraw");
    vi.spyOn(api, "kararTablosuKaydet").mockRejectedValue(
      new ApiError(422, "1 doğrulama hatası", { kod: "karar_tablosu_gecersiz", hatalar: ["satirlar[1].id: 'R1' kimliği birden çok satırda kullanılmış"] }),
    );
    uygulama(YOL);
    const t2 = await kart(/T2 · Minimum sipariş/);
    await userEvent.click(within(t2).getByRole("button", { name: "Düzenle" }));
    const form = within(t2).getByTestId("kt-duzenleyici");
    await userEvent.click(within(form).getByRole("button", { name: "Kaydet" }));
    const r2 = within(form).getByRole("group", { name: "Satır R2" });
    const hata = await within(r2).findByTestId("kt-satir-id-hatasi");
    expect(hata).toHaveTextContent("Satır R2: 'R1' kimliği birden çok satırda kullanılmış");
    expect(r2.getAttribute("aria-describedby")!.split(" ")).toContain(hata.id);
    const kosul = within(r2).getByLabelText("Koşul");
    expect(kosul).toHaveAttribute("aria-invalid", "true");
    expect(kosul.getAttribute("aria-describedby")!.split(" ")).toContain(hata.id);
    // Genel listede tekrarlanmaz.
    expect(within(form).queryByTestId("genel-hatalar")).toBeNull();
  });
});

describe("onyüz 22: yeniden üretim kutusu odak", () => {
  it("açılınca odak kutudaki ilk düğmede; Esc kapatır ve odak 'AI taslağı üret'e döner", async () => {
    await oturumAc("analist");
    uygulama(YOL);
    await kart(/T1 · Kampanya/);
    await userEvent.click(screen.getByRole("button", { name: "AI taslağı üret" }));
    const kutu = screen.getByTestId("taslak-onay");
    await waitFor(() => expect(within(kutu).getByRole("button", { name: "Evet, yeni taslak üret" })).toHaveFocus());
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByTestId("taslak-onay")).toBeNull();
    await waitFor(() => expect(screen.getByRole("button", { name: "AI taslağı üret" })).toHaveFocus());
  });
});

describe("u2 N5: PO tablo geçmişinde 'Tablo yanlış' bildirimini görür", () => {
  it("yeniden açılan tablo: uyarı (gerekçe, kişi, case bağlantısı) ve geçmiş satırı", async () => {
    await t2Onayla();
    await api.kararTablosuGecis("kt-2", "reopen", { icerik_hash: kaliteVerisi(mockVerisi()).tablolar[1].icerik_hash, gerekce: "Story 750,00 TL'yi dahil sayıyor.", case_id: "case-1-7" });
    await t2Duzelt({ ...MIN_SIPARIS_DOGRU, aciklama: "Yeniden gözden geçirildi." });
    await oturumAc("po");
    uygulama(YOL);
    const t2 = await kart(/T2 · Minimum sipariş/);
    const not = within(t2).getByTestId("kt-tablo-yanlis-notu");
    expect(not).toHaveTextContent("Tablo yanlış bildirildi");
    expect(not).toHaveTextContent("“Story 750,00 TL'yi dahil sayıyor.”");
    expect(within(not).getByRole("link", { name: "Bildiren case'i aç" })).toHaveAttribute("href", `/gereksinimler/${REQ}/caseler#case-case-1-7`);
    expect(within(t2).getByTestId("kt-gecmis")).toHaveTextContent("Yeniden açtı (Tablo yanlış bildirimi) — “Story 750,00 TL'yi dahil sayıyor.”");
  });
});

describe("Kule ekran turu (koordinatör 2–5) + u2 N14, N16", () => {
  it("onaylı-uyumsuz listesi 'TPD-1 · C6 <başlık>' (ham case kimliği yok); künye yoksa yalnız başlık", () => {
    yalin(
      <OnayliUyumsuzKarti
        k={kule({
          onayli_uyumsuz: [
            { case_id: "8f1c2d4e-uuid", requirement_id: "req-tpd-1", baslik: "750 TL'de uyarı", jira_key: "TPD-1", sira_no: 6 },
            { case_id: "eski-uuid", requirement_id: "req-tpd-1", baslik: "Eski çekirdek" },
          ],
        })}
      />,
    );
    expect(screen.getByRole("link", { name: "TPD-1 · C6 750 TL'de uyarı" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Eski çekirdek" })).toBeInTheDocument();
    expect(screen.queryByText("8f1c2d4e-uuid")).toBeNull();
  });

  it("Q2 Y10: kapsam yetersizse karo 'ölçülmedi — <not>'", () => {
    yalin(
      <HataYakalamaKarosu
        k={kule({
          hata_yakalama: {
            son_kosu: { id: "f1", bitis: "2026-11-10T10:00:00+03:00", durum: "done" },
            oran: null,
            yakalanan: 1,
            kacan: 0,
            gecersiz: 8,
            el_yazisi: { oran: null, yakalanan: 1, kacan: 0 },
            kapsam: { kosulan_hata: 9, katalog: 9, platformlar: ["ios"], tam_katalog: true, gecerli_adim: 1, esik: 0.5, yeterli: false, not: "Geçerli hata adımı kataloğun %50'sinin altında (ios 1/9); oran ölçü sayılmaz." },
          },
        })}
      />,
    );
    expect(screen.getByTestId("hata-yakalama")).toHaveTextContent(/^ölçülmedi$/);
    expect(screen.getByTestId("hata-yakalama-ayrinti")).toHaveTextContent(/^ölçülmedi — Geçerli hata adımı kataloğun %50'sinin altında \(ios 1\/9\); oran ölçü sayılmaz\./);
  });

  it("kart varsayılan olarak Kule'nin ölçtüğü koşuyu açar; tümü geçersiz yeni koşu seçilebilir ve 'bütün testler sayıldı' demez", async () => {
    await oturumAc("muhendis");
    kuleAyar.adimMs = 3_600_000;
    await hataKosusuApi.baslat({ platformlar: ["ios"] });
    while (kuleMockIlerlet());
    const u = userEvent.setup();
    sar(<HataKosusuKarti olculenKosuId="hk-1" />);
    await waitFor(() => expect(screen.getByTestId("hk-sonuc")).toHaveAttribute("data-kosu", "hk-1"));
    expect(screen.getByTestId("hk-sonuc")).toHaveTextContent("Kule ölçüsü");
    // N16: son sütun başlıklı.
    const gecmis = within(screen.getByTestId("hk-gecmis"));
    expect(gecmis.getByRole("columnheader", { name: "Görünüm" })).toBeInTheDocument();
    expect(within(gecmis.getByTestId("hk-gecmis-hk-1")).getByText(/Kule ölçüsü/)).toBeInTheDocument();
    // N14: kural dağılımında geçersiz adım hücrede görünür (android min_siparis_1000).
    const dagilim = within(screen.getByTestId("hk-kural-dagilim"));
    expect(dagilim.getByRole("rowheader", { name: "T2 · AC3" }).closest("tr")).toHaveTextContent("⚠ 1 geçersiz");
    // Tümü geçersiz iOS koşusu.
    await u.click(within(gecmis.getByTestId("hk-gecmis-hk-2")).getByRole("button", { name: /^Aç:/ }));
    await waitFor(() => expect(screen.getByTestId("hk-sonuc")).toHaveAttribute("data-kosu", "hk-2"));
    expect(screen.queryByTestId("hk-suite")).toBeNull();
    expect(screen.queryByText(/bütün testler sayıldı/)).toBeNull();
    expect(screen.getByTestId("hk-kapsam-notu")).toHaveTextContent(/^Oran ölçülmedi — Geçerli hata adımı kataloğun %50'inin altında \(ios 0\/9\)/);
  }, 20_000);
});

describe("tur 2: kısmen nedenleri düz Türkçe", () => {
  it("yüksek riskte atılan olgu nedeni: nedenler listelenir, 'Değerleri elle doğruladım, onayla' gerekçe formu (tür kontrolsuz)", async () => {
    await t2Onayla();
    await isleriBekle();
    const c = mockVerisi().caseler.find((x) => x.id === "case-1-9")!;
    c.icerik = { ...c.icerik, risk: "high" };
    c.icerik_hash = (await api.caseOracleKontrol(c.id, c.icerik)).icerik_hash!;
    await isleriBekle();
    const kayit = kaliteVerisi(mockVerisi()).kontroller.find((r) => r.test_case_id === c.id && r.icerik_hash === c.icerik_hash)!;
    kayit.sonuc = "kismen";
    kayit.kismen_nedeni = ["eksik_girdi", "atilan_olgu"];
    uygulama(`/gereksinimler/${REQ}/caseler`);
    const k = await screen.findByRole("article", { name: new RegExp(c.icerik.title.slice(0, 20)) });
    const neden = await within(k).findByTestId("oracle-kismen-nedeni");
    expect(neden).toHaveTextContent("case metninde tablonun bir girdisi yok");
    expect(neden).toHaveTextContent("case'ten çıkarılan bir değer metinde doğrulanamadığı için atıldı");
    expect(within(k).getByRole("button", { name: "Onayla" })).toBeDisabled();
    expect(within(k).getByTestId("oracle-kapi")).toHaveAttribute("data-tur", "kontrolsuz");
    const kararSpy = vi.spyOn(api, "caseKarari");
    await userEvent.click(within(k).getByRole("button", { name: "Değerleri elle doğruladım, onayla" }));
    await userEvent.type(within(k).getByLabelText("Neden kontrolsüz onaylıyorsunuz?"), "Atılan değer elle karşılaştırıldı, doğru.");
    await userEvent.click(within(k).getByRole("button", { name: "Değerleri elle doğruladım, onayla" }));
    await waitFor(() => expect(mockVerisi().caseler.find((x) => x.id === c.id)!.durum).toBe("approved"));
    expect(kararSpy).toHaveBeenCalledWith(c.id, expect.objectContaining({ oracle_istisna_turu: "kontrolsuz", oracle_kayit_damgasi: kayit.damga }));
  });
});

describe("Q1 sözleşme ayrıntıları", () => {
  it("damga 'yok' gönderilmez; kısmen nedeni null → alan yok; istisna id okunur", () => {
    expect(damgaAlani({ damga: "yok" } as never)).toEqual({});
    expect(damgaAlani({ damga: "2026-11-12T10:00:00+00:00" } as never)).toEqual({ oracle_kayit_damgasi: "2026-11-12T10:00:00+00:00" });
    const o = caseOracleYanitiUyarla({
      case_id: "c",
      oracle: { sonuc: "uyumsuz", ozet: "", karsilastirmalar: [], kismen_nedeni: null, damga: "yok", istisna: { id: "ist-1", gerekce: "g", tur: "uyumsuz", gecerli: true }, kontrol_suruyor: false },
    })!;
    expect(o).not.toHaveProperty("kismen_nedeni");
    expect(o.istisna).toMatchObject({ id: "ist-1", gecerli: true });
  });

  it("karşılaştırılamayan sayı türleri düz Türkçe", () => {
    expect(karsilastirilamamaNedeni("Beklenen alandaki sayı hiçbir tablo değeriyle eşlenmedi")).toBe("case metninde karşılaştırılmayan sayı");
    expect(karsilastirilamamaNedeni("Girdi alanındaki sayı çıkarılan değerlerle eşleşmiyor (çelişebilir)")).toBe("girdi değeri çelişiyor");
    expect(karsilastirilamamaNedeni("Yazıyla yazılmış sayı karşılaştırılamaz")).toBe("yazıyla yazılmış sayı");
    expect(karsilastirilamamaNedeni("case'te bulunamayan girdi: ara_toplam")).toBe("case'te bulunamayan girdi: ara_toplam");
  });

  it("ornekler: `ortusme` + `onem: bilgi` uyarı değil bilgi notu", async () => {
    await oturumAc("po");
    const t = (await api.kararTablolari(REQ)).tablolar[1];
    vi.spyOn(api, "kararTablosuOrnekleri").mockResolvedValue({
      ornekler: [],
      uyarilar: [
        { tur: "ortusme", onem: "bilgi", mesaj: "R1 önceliklidir (kampanyalı sepette R2'ye bakılmaz).", satirlar: ["R1", "R2"] },
        { tur: "ortusme", onem: "uyari", mesaj: "R2 ve R3 aynı tutarı kısıtlıyor.", satirlar: ["R2", "R3"] },
      ],
    });
    yalin(<OrnekIzgarasi tablo={t} />);
    const liste = await screen.findByTestId("kt-ornek-uyari");
    const [bilgi, uyari] = within(liste).getAllByRole("listitem");
    expect(bilgi).toHaveTextContent(/^Bilgi: R1 önceliklidir/);
    expect(bilgi).toHaveAttribute("data-onem", "bilgi");
    expect(uyari).toHaveTextContent(/^Satırlar örtüşüyor: R2 ve R3/);
  });
});

describe("u2 N17: yüzen asistan başlatıcısı", () => {
  it("sayfa kaydırılınca yalnız ikona küçülür (ad aria-label'da kalır); tepede adıyla", async () => {
    await oturumAc("analist");
    uygulama(YOL);
    const b = await screen.findByRole("button", { name: "Asistanı aç" });
    expect(b).not.toHaveClass("kucuk");
    Object.defineProperty(window, "scrollY", { value: 400, configurable: true });
    window.dispatchEvent(new Event("scroll"));
    await waitFor(() => expect(b).toHaveClass("kucuk"));
    expect(b).toHaveAccessibleName("Asistanı aç");
    Object.defineProperty(window, "scrollY", { value: 0, configurable: true });
    window.dispatchEvent(new Event("scroll"));
    await waitFor(() => expect(b).not.toHaveClass("kucuk"));
  });
});

describe("birleştirme turu 2: çekirdek örnek girdisi metin sayı", () => {
  it("eşik satırı çekirdeğin '750.00' metniyle de bulunur (gerçek portal ekran turu)", () => {
    expect(sayiDegeri("750.00")).toBe(750);
    expect(sayiDegeri(" 749.99 ")).toBe(749.99);
    expect(sayiDegeri(7)).toBe(7);
    expect(sayiDegeri("yedi")).toBeNull();
    expect(sayiDegeri(true)).toBeNull();
  });
});

describe("birleştirme turu 2: çekirdeğin çok girdili ayırt edici örneği", () => {
  it("'adet = 14, ara_toplam = 350,00' → ilk sayısal girdi (adet 14)", () => {
    expect(ayirtEdiciGirdi("adet = 14, ara_toplam = 350,00")).toEqual({ ad: "adet", deger: 14 });
    expect(ayirtEdiciGirdi("kampanyali_sepet = yanlış, sepet_tutari = 750,00")).toEqual({ ad: "sepet_tutari", deger: 750 });
    expect(ayirtEdiciGirdi("adet = 14")).toEqual({ ad: "adet", deger: 14 });
    expect(ayirtEdiciGirdi("")).toBeNull();
  });
});
