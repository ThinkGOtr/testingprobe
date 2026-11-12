// UX ikinci tur bulguları (B1–B17; feat/case-gen-v3 review-portal): story'siz gereksinimde kartın
// "PO'ya gönder"i, doğrulanan varsayımın diğer case'lere ve panele yansıması, axe definition-list,
// CL tekniği, PO yanıtı sonrası tek mesaj, sayaç/gerekçe, CQ kimliği, durum şeridi, P9 ortak ölçek,
// dar ekran etiketi, örneklem notu, hedeflerde güncel değer, terimler, PO yazarının görünen adı.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import type { AcikSoruKaydi } from "../api/acikSoruTipleri";
import { api } from "../api/client";
import { V3_GEREKSINIM_ID } from "../api/mock/caseV3";
import { mockCaseKalitesi as hamKalite } from "../api/mock/caseKalitesi";
import { caseKalitesiUyarla } from "../api/uyumCaseKalitesi";
import { mockVerisi } from "../api/mock/handlers";
import type { TestCase } from "../api/types";
import { caseUyarla } from "../api/uyum";
import { OturumProvider } from "../auth";
import {
  acikSoruSayimi,
  dogrulamayiYay,
  hazirlikYonlendirmesi,
  TEKNIK_ONEK_IPUCU,
  tutarlilikSorunlari,
} from "../lib/caseV3";
import { CASE_TEKNIGI } from "../lib/etiketler";
import { oturumAc, sar } from "../test/yardimci";
import { AcikSorularPaneli, panelSayimi, PoYanitiMetni, PoyaGonderEylemi } from "./AcikSorular";
import { BildirimProvider } from "./Bildirim";
import { CaseDurumSeridi, acikSoruSeritDurumu } from "./CaseDurumSeridi";
import { CaseKalitesiIcerik, DagilimCubuklari, KARAR_ETIKETI, hedefGuncelDegeri } from "./CaseKalitesi";
import { CaseKarti, TeknikRozeti } from "./CaseKarti";

const mockCaseKalitesi = () => caseKalitesiUyarla(hamKalite(null));

const SAYFA = `/gereksinimler/${V3_GEREKSINIM_ID}/caseler`;

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

function jiraStorysiVer(anahtar = "TPD-9") {
  mockVerisi().gereksinimler.find((g) => g.id === V3_GEREKSINIM_ID)!.jira_key = anahtar;
}

async function v3Case(id: string): Promise<TestCase> {
  return (await api.caseler(V3_GEREKSINIM_ID)).find((c) => c.id === id)!;
}

describe("B1: story'si olmayan gereksinimde kartın 'PO'ya gönder'i", () => {
  it("düğme çizilmez; kutu metni nedenini ve yapılacak işi söyler", async () => {
    await oturumAc("analist");
    const tc = await v3Case("case-v3-3");
    expect(tc.jira_key).toBeNull();
    sar(<CaseKarti tc={tc} guncellendi={() => {}} poyaGonder={<PoyaGonderEylemi tc={tc} />} />);
    const kutu = within(screen.getByTestId("hazirlik-yonlendirme"));
    expect(kutu.getByTestId("hazirlik-yonlendirme-metin")).toHaveTextContent(
      "Q1 PO yanıtı gerektiriyor. Bu gereksinimin Jira story'si olmadığı için soru portaldan gönderilemez; yanıtı PO'dan alıp 'Düzelt' ile beklenen sonucu yazın.",
    );
    expect(kutu.queryByRole("button", { name: "Açık soruları PO'ya gönder" })).not.toBeInTheDocument();
  });

  it("story varsa düğme çizilir ve gönderim sonrası bildirimde PO kimliği (CQ1) yazılır", async () => {
    await oturumAc("analist");
    jiraStorysiVer();
    const tc = await v3Case("case-v3-3");
    const u = userEvent.setup();
    sar(<CaseKarti tc={tc} guncellendi={() => {}} poyaGonder={<PoyaGonderEylemi tc={tc} />} />);
    await u.click(within(screen.getByTestId("hazirlik-yonlendirme")).getByRole("button", { name: "Açık soruları PO'ya gönder" }));
    expect(await screen.findByText(/Açık sorular PO'ya gönderildi \(CQ1\)/)).toBeInTheDocument();
  });
});

describe("B2: doğrulanan varsayım diğer case'lere ve panele yansır", () => {
  it("core alanı `dogrulama` uyarlanır", () => {
    const c = caseUyarla({
      id: "c1",
      icerik: { title: "x", readiness: "assumption_dependent", assumption_refs: ["A1"] },
      varsayimlar: [{ id: "A1", statement: "V", owner: "analyst", dogrulama: { case_id: "c0", sira_no: 2, kimlik: "A1", kim: "analist", zaman: "2026-11-12T10:00:00Z" } }],
    });
    expect(c.varsayimlar?.[0].dogrulama).toEqual({ case_id: "c0", sira_no: 2, kimlik: "A1", kim: "analist", zaman: "2026-11-12T10:00:00Z" });
    expect(caseUyarla({ id: "c2", icerik: { title: "y" }, varsayimlar: [{ id: "A1", statement: "V", owner: "" }] }).varsayimlar?.[0].dogrulama).toBeUndefined();
  });

  it("örnek veri: #2'de doğrulanan A1, #6'nın A1 kaydında; kutu metni 'doğrulanmadı' demez", async () => {
    await oturumAc("analist");
    const iki = await v3Case("case-v3-2");
    await api.varsayimDogrulandi(iki.id, { icerik_hash: iki.icerik_hash, varsayim_id: "A1" });
    const alti = await v3Case("case-v3-6");
    expect(alti.durum).toBe("draft");
    expect(alti.varsayimlar?.[0].dogrulama).toMatchObject({ case_id: "case-v3-2", sira_no: 2, kimlik: "A1", kim: "analist" });
    const y = hazirlikYonlendirmesi(alti, (ad) => (ad === "analist" ? "Cengizhan G." : ad ?? ""))!;
    expect(y.metin).toMatch(/^A1, #2 numaralı case'te doğrulandı \(Cengizhan G\., .+\)\. Bu case için de onaylamak üzere 'Varsayım doğrulandı' düğmesini kullanın/);
    expect(y.metin).not.toContain("doğrulanmadı.");
    expect(y.dogrulanacak).toEqual(["A1"]);
    // Taslağa alınan case'in doğrulaması sayılmaz.
    const onayli = await v3Case("case-v3-2");
    await api.caseYenidenAc(onayli);
    expect((await v3Case("case-v3-6")).varsayimlar?.[0].dogrulama).toBeUndefined();
  });

  it("iyimser güncelleme: aynı metinli varsayıma dayanan case'ler işaretlenir, diğerleri aynı kalır", async () => {
    await oturumAc("analist");
    const liste = await api.caseler(V3_GEREKSINIM_ID);
    const onceki = liste.find((c) => c.id === "case-v3-2")!;
    const yeni: TestCase = { ...onceki, durum: "approved", varsayimlar: [], karar_veren: "analist", karar_zamani: "2026-11-12T10:00:00Z" };
    const sonra = dogrulamayiYay(liste, onceki, yeni, ["A1"]);
    expect(sonra.find((c) => c.id === "case-v3-2")).toBe(yeni);
    expect(sonra.find((c) => c.id === "case-v3-6")!.varsayimlar![0].dogrulama).toEqual({
      case_id: "case-v3-2",
      sira_no: 2,
      kimlik: "A1",
      kim: "analist",
      zaman: "2026-11-12T10:00:00Z",
    });
    expect(sonra.find((c) => c.id === "case-v3-1")).toBe(liste.find((c) => c.id === "case-v3-1"));
  });

  it("sayfada: #2'de 'Varsayım doğrulandı' → #6'nın kutusu ve rozeti, paneldeki A1 satırı güncellenir", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama(SAYFA);
    // case-v3-2 ve case-v3-6 aynı A1'e dayanır; #2 = case-v3-2.
    const kart = (id: string) => within(document.getElementById(`case-${id}`)!);
    await waitFor(() => expect(document.getElementById("case-case-v3-6")).not.toBeNull());
    expect(kart("case-v3-6").getByTestId("hazirlik-yonlendirme-metin")).toHaveTextContent(/^A1 varsayımı doğrulanmadı\./);
    await u.click(kart("case-v3-2").getByRole("button", { name: "Varsayım doğrulandı" }));
    await u.click(within(screen.getByTestId("varsayim-dogrulama-onayi")).getByRole("button", { name: "Evet, doğrulandı — onayla" }));
    await waitFor(() => expect(kart("case-v3-6").getByTestId("hazirlik-yonlendirme-metin")).toHaveTextContent(/^A1, #2 numaralı case'te doğrulandı/));
    expect(within(kart("case-v3-6").getByTestId("case-varsayimlar")).getByTestId("varsayim-dogrulandi")).toHaveTextContent("✓ Doğrulandı (#2)");
    const panel = within(screen.getByRole("region", { name: "Açık sorular ve PO yanıtları" }));
    const a1 = (await panel.findAllByTestId("acik-soru-satiri")).find((s) => s.textContent?.includes("250 karakter sınırı"))!;
    await waitFor(() => expect(within(a1).getByTestId("varsayim-dogrulandi")).toHaveTextContent("✓ Doğrulandı (#2)"));
    expect(within(a1).queryByText("PO'ya gönderilmedi")).not.toBeInTheDocument();
  });
});

describe("B3: PO yanıtı sonrası kart tek mesaj verir", () => {
  it("öneri kutusu yok, birincil 'Düzelt' kutuda, açık sorular bilgi tonunda, beklenen sonuç satırı ve Onayla ipucu", async () => {
    await oturumAc("analist");
    jiraStorysiVer();
    await api.acikSorulariGonder(V3_GEREKSINIM_ID);
    await api.acikSoruYanitlariniOku(V3_GEREKSINIM_ID);
    const tc = await v3Case("case-v3-3");
    expect(tc.po_yanit_onerisi).toBeTruthy();
    const u = userEvent.setup();
    sar(<CaseKarti tc={tc} guncellendi={() => {}} poyaGonder={<PoyaGonderEylemi tc={tc} />} />);
    const kutu = within(screen.getByTestId("hazirlik-yonlendirme"));
    expect(kutu.getByTestId("hazirlik-yonlendirme-metin")).toHaveTextContent("CQ1: PO yanıtladı. 'Düzelt' ile beklenen sonucu yanıta göre yazın");
    expect(screen.queryByTestId("po-yanit-onerisi")).not.toBeInTheDocument();
    const sorular = screen.getByTestId("case-acik-sorular");
    expect(within(sorular).getByText("Açık sorular ve PO yanıtı")).toBeInTheDocument();
    expect(sorular.querySelector(".uyari-bilgi")).not.toBeNull();
    expect(screen.queryByText(/yanıtlanmadan bu case hazır olamaz/)).not.toBeInTheDocument();
    expect(screen.getByText("— (PO yanıtına göre yazılacak)")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Onayla" })).not.toHaveAttribute("data-yetkisiz"));
    expect(screen.getByRole("button", { name: "Onayla" })).toHaveAttribute("title", "PO yanıtladı: önce 'Düzelt' ile beklenen sonucu yanıta göre yazın.");
    const duzelt = kutu.getByTestId("yonlendirme-duzelt");
    expect(duzelt).toHaveClass("dugme-birincil");
    await u.click(duzelt);
    expect(await screen.findByTestId("duzeltme-kaynaklari")).toBeInTheDocument();
    // B7: düzeltme formunda atıf kimliği ile PO kimliğinin eşlemesi.
    expect(screen.getByTestId("soru-kimlik-ipucu")).toHaveTextContent("Q1 = CQ1");
  });
});

describe("B5: CL (kontrol listesi) tekniği", () => {
  it("sözlükte, rozette ve kapsam öğesi ipucunda; CL- öğesi yoksa tutarlılık uyarısı", async () => {
    expect(CASE_TEKNIGI.CL).toBe("kontrol listesi");
    expect(TEKNIK_ONEK_IPUCU).toContain("CL → CL-");
    sar(<TeknikRozeti teknik="CL" />);
    expect(screen.getByTitle("kontrol listesi")).toHaveTextContent("CL (kontrol listesi)");
    const tc = await (async () => {
      await oturumAc("analist");
      return v3Case("case-v3-1");
    })();
    expect(tutarlilikSorunlari({ ...tc.icerik, technique: ["CL"], covers: ["EP-V1"] })).toContain("Teknik CL için kapsam öğesi yok (CL-… bekleniyor).");
  });

  it("düzeltme formunda onay kutusu 'CL (kontrol listesi)'", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    sar(<CaseKarti tc={await v3Case("case-v3-1")} guncellendi={() => {}} />);
    await u.click(screen.getByRole("button", { name: "Düzelt" }));
    const grup = screen.getByRole("group", { name: "Test tasarım teknikleri" });
    expect(within(grup).getByText("(kontrol listesi)")).toBeInTheDocument();
    expect(grup).not.toHaveTextContent("CL ()");
  });
});

const kayit = (tur: "soru" | "varsayim", durum: AcikSoruKaydi["durum"], sahip = "PO"): AcikSoruKaydi => ({
  etiket: null,
  kaynak_id: tur === "soru" ? "Q1" : "A1",
  tur,
  metin: "m",
  sahip,
  durum,
  gonderim: null,
  yanit: null,
  bekleyen_caseler: [],
  oneri: null,
});

describe("B6: sayaç ve gönder gerekçesi", () => {
  it("sorular ve varsayımlar ayrı sayılır; gerekçe durumla eşleşir", () => {
    const l = [kayit("soru", "gonderildi"), kayit("soru", "yanitlandi"), kayit("varsayim", "gonderilmedi", "analyst")];
    const s = panelSayimi(l, false, null);
    expect(s.metin).toBe("Sorular: 0 gönderilmedi · 1 yanıt bekleniyor · 1 yanıtlandı | Varsayımlar: 1 gönderilmedi");
    expect(s.neden).toBe(
      `Gönderilmemiş soru yok; 1 varsayım gönderilmedi. Göndermek için "Case'lerin dayandığı varsayımları da doğrulama için gönder" kutusunu işaretleyin.`,
    );
    expect(panelSayimi(l, true, null).neden).toBeUndefined();
    expect(panelSayimi([kayit("soru", "gonderildi")], false, null)).toEqual({ metin: "Sorular: 0 gönderilmedi · 1 yanıt bekleniyor · 0 yanıtlandı", gonderilecek: 0, neden: "Gönderilmemiş soru ya da varsayım yok." });
    expect(panelSayimi(l, false, "Story yok.").neden).toBe("Story yok.");
  });

  it("panelde: soru gönderildikten sonra varsayım kalınca gerekçe kutuyu işaret eder (B6), B15 rozeti", async () => {
    await oturumAc("analist");
    jiraStorysiVer();
    await api.acikSorulariGonder(V3_GEREKSINIM_ID);
    sar(<AcikSorularPaneli requirementId={V3_GEREKSINIM_ID} />);
    const panel = await screen.findByRole("region", { name: "Açık sorular ve PO yanıtları" });
    expect(await within(panel).findByTestId("acik-soru-sayim")).toHaveTextContent("Sorular: 0 gönderilmedi · 1 yanıt bekleniyor · 0 yanıtlandı | Varsayımlar: 1 gönderilmedi");
    expect(within(panel).getByText(/^Gönderim: Gönderilmemiş soru yok; 1 varsayım gönderilmedi/)).toBeInTheDocument();
    // B15: analistin varsayımı "PO'ya gönderilmedi" değil "Doğrulanmadı".
    const a1 = within(panel).getAllByTestId("acik-soru-satiri").find((s) => s.textContent?.includes("Varsayım"))!;
    expect(within(a1).getByText("Doğrulanmadı")).toBeInTheDocument();
    expect(within(a1).queryByText("PO'ya gönderilmedi")).not.toBeInTheDocument();
    // B7: gönderilen soru CQ1 ile, üretimdeki kimlik ipucuyla.
    const q1 = within(panel).getAllByTestId("acik-soru-satiri").find((s) => s.textContent?.includes("Açık soru"))!;
    expect(within(q1).getByText("CQ1")).toHaveAttribute("title", "Üretimdeki kimlik: Q1");
    expect(within(q1).getByText("üretimdeki kimlik: Q1")).toBeInTheDocument();
  });
});

describe("B8: durum şeridinde açık soru öğesi", () => {
  it("metin sıradaki eylemi öne alır; soru yoksa öğe yok", () => {
    expect(acikSoruSeritDurumu(null)).toBeNull();
    expect(acikSoruSeritDurumu({ gonderilmedi: 0, gonderildi: 0, yanitlandi: 0 })).toBeNull();
    expect(acikSoruSeritDurumu({ gonderilmedi: 1, gonderildi: 0, yanitlandi: 0 })).toEqual({ metin: "1 soru PO'ya gönderilmedi", ton: "uyari" });
    expect(acikSoruSeritDurumu({ gonderilmedi: 0, gonderildi: 1, yanitlandi: 0 })).toEqual({ metin: "1 PO yanıtı bekleniyor", ton: "notr" });
    expect(acikSoruSeritDurumu({ gonderilmedi: 0, gonderildi: 1, yanitlandi: 2 })!.metin).toBe("2 PO yanıtı geldi · 1 PO yanıtı bekleniyor");
  });

  it("şeritte #acik-sorular bağlantısı; PO yanıtı gelince 'PO yanıtı geldi'", async () => {
    await oturumAc("analist");
    jiraStorysiVer();
    let liste = await api.caseler(V3_GEREKSINIM_ID);
    expect(acikSoruSayimi(liste)).toEqual({ gonderilmedi: 1, gonderildi: 0, yanitlandi: 0 });
    const { unmount } = sar(<CaseDurumSeridi caseler={liste} denetim={null} yayinYolu="/y" />);
    const oge = screen.getByTestId("serit-acik-sorular");
    expect(oge).toHaveTextContent("1 soru PO'ya gönderilmedi");
    expect(oge.getAttribute("href")).toMatch(/#acik-sorular$/);
    unmount();
    await api.acikSorulariGonder(V3_GEREKSINIM_ID);
    await api.acikSoruYanitlariniOku(V3_GEREKSINIM_ID);
    liste = await api.caseler(V3_GEREKSINIM_ID);
    sar(<CaseDurumSeridi caseler={liste} denetim={null} yayinYolu="/y" />);
    expect(screen.getByTestId("serit-acik-sorular")).toHaveTextContent("1 PO yanıtı geldi");
  });
});

describe("B9–B13: Kontrol Kulesi case kalitesi", () => {
  it("B9: P9 kod ve model dağılımı ortak ölçekle çizilir", () => {
    const k = mockCaseKalitesi();
    sar(<CaseKalitesiIcerik k={k} baslikId="ck" />);
    const genislik = (testId: string, etiket: string) =>
      (within(screen.getByTestId(testId)).getByText(etiket).closest("li")!.querySelector(".ck-dagilim-cubuk") as HTMLElement).style.width;
    // Kod: Kabul 3, model: Kabul 4 → ortak en büyük 4: %75 ve %100.
    expect(genislik("denetim-kod", KARAR_ETIKETI.KABUL)).toBe("75%");
    expect(genislik("denetim-model", KARAR_ETIKETI.KABUL)).toBe("100%");
  });

  it("B10: tekniğin tam adı etiketin içinde (değer sütununda değil)", () => {
    sar(<DagilimCubuklari etiket="t" satirlar={[{ etiket: "EP", n: 3, ek: "Eşdeğerlik bölümleme" }]} />);
    const etiket = document.querySelector(".ck-dagilim-etiket")!;
    expect(etiket).toHaveTextContent("EP · Eşdeğerlik bölümleme");
    expect(document.querySelector(".ck-dagilim-deger")).not.toHaveTextContent("Eşdeğerlik");
  });

  it("B10/B5: teknik dağılımında CL tek kaynaktan 'Kontrol listesi'", () => {
    sar(<CaseKalitesiIcerik k={mockCaseKalitesi()} baslikId="ck" />);
    expect(within(screen.getByTestId("ck-teknik")).getByText(/Kontrol listesi/)).toBeInTheDocument();
  });

  it("B11: n<20 iken n her zaman yazılı küçük örneklem notu", () => {
    sar(<CaseKalitesiIcerik k={mockCaseKalitesi()} baslikId="ck" />);
    const notlar = screen.getAllByTestId("kucuk-orneklem").map((n) => n.textContent);
    expect(notlar).toContain("n=6 review · küçük örneklem: dağılım yön göstermez, karşılaştırma için erken.");
    expect(notlar).toContain("n=6 denetim · küçük örneklem: dağılım yön göstermez, karşılaştırma için erken.");
  });

  it("B12: hedefin güncel değeri (renksiz)", () => {
    const k = mockCaseKalitesi();
    expect(hedefGuncelDegeri(k, "review.ortalama")).toBe("%79,2");
    expect(hedefGuncelDegeri(k, "tekrar.oran")).toBe("%7,9");
    expect(hedefGuncelDegeri(k, "yok.boyle")).toBeNull();
    expect(hedefGuncelDegeri({ ...k, review: { ...k.review, ortalama: null } }, "review.ortalama")).toBe("ölçülmedi");
    sar(<CaseKalitesiIcerik k={k} baslikId="ck" />);
    const madde = screen.getAllByTestId("hedef-maddesi")[0];
    expect(madde).toHaveTextContent("Case seti review ortalaması: hedef ≥ %80 · şu an %79,2");
    expect(madde.querySelector(".cip, [class*='basari'], [class*='hata']")).toBeNull();
  });

  it("B13: karar terimi tek ('Engelle'): P9, içerik kontrolü ve sürüm tablosu", () => {
    sar(<CaseKalitesiIcerik k={mockCaseKalitesi()} baslikId="ck" />);
    expect(within(screen.getByTestId("denetim-kod")).getByText("Engelle")).toBeInTheDocument();
    expect(within(screen.getByTestId("ck-icerik")).getByText("Engelle")).toBeInTheDocument();
    expect(within(screen.getByTestId("ck-icerik")).queryByText("Engel")).not.toBeInTheDocument();
    expect(within(screen.getByTestId("case-kalitesi-surumler")).getByRole("columnheader", { name: "Engelle" })).toBeInTheDocument();
  });
});

describe("B17: PO yanıtının yazarı görünen adıyla", () => {
  it("kullanıcı adı eşlenirse görünen ad, eşlenmezse (Jira görünen adı) aynen", async () => {
    await oturumAc("analist");
    const { unmount } = sar(<PoYanitiMetni yanit={{ metin: "5 deneme", yazar: "po", zaman: null }} />);
    await waitFor(() => expect(screen.getByTestId("po-yaniti-kaynak")).toHaveTextContent("— PO yanıtı (Cengizhan Gunaydin · PO)"));
    expect(screen.getByTestId("po-yaniti-kaynak")).not.toHaveTextContent("(po");
    unmount();
    sar(<PoYanitiMetni yanit={{ metin: "x", yazar: "Ayşe Yılmaz", zaman: null }} />);
    expect(screen.getByTestId("po-yaniti-kaynak")).toHaveTextContent("— PO yanıtı (Ayşe Yılmaz)");
  });
});
