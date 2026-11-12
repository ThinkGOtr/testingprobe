// UX4 (ekran testi + demo provası) düzeltmeleri: iki turlu prova düğmesi, case'e bağlı olmayan açık soru
// (şerit + toplu onay uyarısı), toplu onayın review süresi, asistanın son kullanıcı metni, başlatıcı
// yerleşimi, varsayım doğrulama onayı, küçükler (öncelik, teknik adı, yuvarlama, PO yazarı, ortam adı).
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import type { AcikSoruKaydi, AcikSorularYaniti } from "../api/acikSoruTipleri";
import { api } from "../api/client";
import { ortamAdlariniGizle } from "../api/http";
import { V3_GEREKSINIM_ID } from "../api/mock/caseV3";
import { mockVerisi } from "../api/mock/handlers";
import type { CaseKalitesi, GereksinimDetay, TestCase } from "../api/types";
import { OturumProvider } from "../auth";
import { acikSoruSayimi, gonderilmemisSoruSayisi } from "../lib/caseV3";
import { kipDugmeMetni } from "../lib/uretimSecenekleri";
import { demoAdimlari, type YolGirdisi } from "../lib/yolHaritasi";
import { reviewSuresiAlti } from "../pages/CaseReview";
import { oturumAc, sar } from "../test/yardimci";
import { AcikSorularPaneli, panelSayimi, poYazarAdi } from "./AcikSorular";
import { BildirimProvider } from "./Bildirim";
import { acikSoruSeritDurumu } from "./CaseDurumSeridi";
import { hedefGuncelDegeri } from "./CaseKalitesi";
import { CaseKarti, TeknikRozeti } from "./CaseKarti";
import { degerlendirmeNotuMetni } from "./ui";

const kok = resolve(dirname(fileURLToPath(import.meta.url)), "..");
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

const soru = (p: Partial<AcikSoruKaydi> = {}): AcikSoruKaydi => ({
  etiket: null,
  kaynak_id: "Q1",
  tur: "soru",
  metin: "Kaç hatalı denemede hesap kilitlenir?",
  sahip: "PO",
  durum: "gonderilmedi",
  gonderim: null,
  yanit: null,
  bekleyen_caseler: [],
  oneri: null,
  ...p,
});

const yanit = (sorular: AcikSoruKaydi[]): AcikSorularYaniti => ({
  requirement_id: V3_GEREKSINIM_ID,
  jira_key: "TPD-9",
  sayim: { gonderilmedi: 0, gonderildi: 0, yanitlandi: 0 },
  gonderilebilir: true,
  gonderim_engeli: null,
  sorular,
});

describe("Bulgu 1: arayüz provası iki turlu akışı yürütür", () => {
  const spec = readFileSync(resolve(kok, "..", "..", "rehearsal", "ui", "prova.spec.ts"), "utf8");

  it("prova eski 'Case üret' düğmesini aramaz; iki tur düğmesinin adı portaldakiyle aynı", () => {
    expect(spec).not.toMatch(/name: "Case üret"/);
    expect(spec).toContain(`const IKI_TUR_DUGMESI = "${kipDugmeMetni("iki_tur")}";`);
    // Model onayı ve tur 2 (otomatik ya da "Case'leri üret") adımları yerinde.
    expect(spec).toContain('"Modeli onayla"');
    expect(spec).toContain(`"Case'leri üret"`);
  });

  it("yol haritası ipucu yeni düğme adını ve model onayını söyler", () => {
    const g = {
      id: "r1", jira_key: "TPD-1", durum: "po_approved", kaynak: "jira", kabul_kriterleri: [{ ref: "AC1", metin: "" }],
      kontrol_turu: 1, kontrol_turu_ust_sinir: 3, icerik_hash: "h",
      po: { durum: "approved", onaylayan: "po", zaman: null, kanal: "jira", onaylanan_hash: "h" },
      sayaclar: { bulgu_acik: 0, case_toplam: 0, case_onayli: 0 },
    } as unknown as GereksinimDetay;
    const girdi: YolGirdisi = { gereksinim: g, caseler: [], scriptler: [], kosular: [], hatalar: [], bugTaslaklari: [], kule: null, demo: null };
    const a4 = demoAdimlari(girdi)[3];
    expect(a4.ipucu).toContain("Tasarım modelini üret (iki tur)");
    expect(a4.ipucu).not.toContain('"Case üret"');
    const model = demoAdimlari({ ...girdi, gereksinim: { ...g, durum: "model_ready" } as GereksinimDetay })[3];
    expect(model.ipucu).toMatch(/Modeli onayla/);
  });
});

describe("Bulgu 2: case'e bağlı olmayan açık soru", () => {
  it("şeritte sayılır (yanıtlanan bağsız soru eylem gerektirmez; öneri core'dan gelir)", () => {
    expect(acikSoruSayimi([], null)).toBeNull();
    const s = acikSoruSayimi([], [soru(), soru({ kaynak_id: "Q2", durum: "gonderildi" }), soru({ kaynak_id: "Q3", durum: "yanitlandi" })]);
    expect(s).toEqual({ gonderilmedi: 1, gonderildi: 1, yanitlandi: 0 });
    expect(acikSoruSeritDurumu(s)?.metin).toBe("1 soru PO'ya gönderilmedi · 1 PO yanıtı bekleniyor");
    // Bekleyen case'i olan soru case kaydından sayılır; core listesinden ikinci kez sayılmaz.
    const bagli = soru({ bekleyen_caseler: [{ id: "c1", sira_no: 1, uretim_no: 1, title: "t", durum: "draft", readiness: "blocked" }] });
    expect(acikSoruSayimi([], [bagli])).toBeNull();
    // Varsayımlar şerit sayımına girmez; gönderilmemiş soru sayısı yalnız sorular.
    expect(gonderilmemisSoruSayisi([soru(), soru({ tur: "varsayim", kaynak_id: "A1" }), soru({ durum: "gonderildi" })])).toBe(1);
  });

  it("sayfada şerit ve toplu onay diyaloğu gönderilmemiş soruyu söyler; onay engellenmez", async () => {
    await oturumAc("analist");
    const spy = vi.spyOn(api, "acikSorular").mockResolvedValue(yanit([soru({ kaynak_id: "Q9", metin: "Hiçbir case'e bağlı olmayan soru" })]));
    const u = userEvent.setup();
    uygulama(SAYFA);
    expect(await screen.findByTestId("serit-acik-sorular", undefined, { timeout: 5000 })).toHaveTextContent("1 soru PO'ya gönderilmedi");
    await u.click(await screen.findByRole("checkbox", { name: /^Case 1'i seç/ }));
    await u.click(screen.getByRole("button", { name: "Seçilenleri onayla" }));
    const onay = within(screen.getByTestId("toplu-onay-onayi"));
    expect(onay.getByTestId("toplu-onay-soru-uyarisi")).toHaveTextContent("PO'ya gönderilmemiş 1 açık soru var. Onay engellenmez");
    await u.click(onay.getByRole("button", { name: "Evet, 1 case'i onayla" }));
    // Toplu onay sonucu sayfada kalıcı satır olarak kalır (bildirim kaybolsa da).
    expect(await screen.findByTestId("toplu-onay-sonuc")).toHaveTextContent("Toplu onay: 1 case onaylandı.");
    expect(mockVerisi().caseler.find((c) => c.id === "case-v3-1")!.durum).toBe("approved");
    spy.mockRestore();
  });
});

describe("Bulgu 4 / 9: açık soru paneli", () => {
  it("bağlı case'i olmayan yanıtlanmış soruda öneri metni core'dan; 'Açık soru' rozeti kalkar", async () => {
    const mesaj = "PO yanıtladı; bu soruya bağlı taslak case yok — yanıt ancak yeniden üretimle case'e döner.";
    const spy = vi.spyOn(api, "acikSorular").mockResolvedValue(
      yanit([soru({ etiket: "CQ1", durum: "yanitlandi", yanit: { metin: "5 deneme", yazar: "po@sim.local", zaman: null }, oneri: { eylem: "yeniden_uret", mesaj, case_ids: [] } })]),
    );
    sar(<AcikSorularPaneli requirementId={V3_GEREKSINIM_ID} />);
    const satir = within(await screen.findByTestId("acik-soru-satiri"));
    expect(satir.getByTestId("acik-soru-onerisi")).toHaveTextContent(mesaj);
    expect(satir.queryByText("Açık soru")).not.toBeInTheDocument();
    expect(satir.getByText("Soru")).toBeInTheDocument();
    // B17: e-posta gösterilmez.
    expect(satir.getByTestId("po-yaniti-kaynak")).toHaveTextContent(/— PO yanıtı$/);
    spy.mockRestore();
  });

  it("doğrulanmış varsayım 'gönderilmedi' sayılmaz", () => {
    const a1 = soru({ tur: "varsayim", kaynak_id: "A1", metin: "Parola büyük/küçük harf duyarlıdır", sahip: "" });
    const once = panelSayimi([a1], false, null);
    expect(once.metin).toBe("Sorular: 0 gönderilmedi · 0 yanıt bekleniyor · 0 yanıtlandı | Varsayımlar: 1 gönderilmedi");
    const sonra = panelSayimi([a1], false, null, () => true);
    expect(sonra.metin).toBe("Sorular: 0 gönderilmedi · 0 yanıt bekleniyor · 0 yanıtlandı | Varsayımlar: 1 doğrulandı");
    expect(sonra.neden).toBe("Gönderilmemiş soru ya da varsayım yok.");
  });
});

describe("Bulgu 5: toplu onay review süresinde ayrı kategori", () => {
  it("taban altı süre toplu onaysa 'betik/API onayı' denmez", () => {
    expect(reviewSuresiAlti({ reviewSure: 1000, topluOnay: 15 }, 5000, true)).toBe("ölçülmedi — toplu onay (15 case): kart başına review süresi ölçülmez");
    expect(reviewSuresiAlti({ reviewSure: 1000, topluOnay: 0 }, 5000, true)).toMatch(/betik\/API onayı/);
    expect(reviewSuresiAlti({ reviewSure: 0 }, 5000, false)).toBe("henüz ölçülmedi");
  });
});

describe("Bulgu 6: asistan değerlendirme notu son kullanıcıya sade", () => {
  it("içerik hash'i / sürüm ayrıntısı gösterilmez", () => {
    const n = degerlendirmeNotuMetni({ durum: "icerik_degisti" as never, etiket: "değerlendirme sonrası içerik değişti (içerik hash'i uyuşmuyor)" });
    expect(n?.metin).toBe("değerlendirme güncel değil");
    expect(`${n?.metin} ${n?.aciklama}`).not.toMatch(/hash|rules\/|sürüm/);
    expect(degerlendirmeNotuMetni({ durum: "pending", etiket: null })?.metin).toBe("canlı değerlendirme bekliyor");
    expect(degerlendirmeNotuMetni({ durum: "evaluated", etiket: null })).toBeNull();
  });
});

describe("Bulgu 7: asistan başlatıcısı içeriği örtmez", () => {
  it("her genişlikte yalnız ikon; içerik altında başlatıcı kadar boşluk", () => {
    const css = readFileSync(resolve(kok, "components/asistan/asistan.css"), "utf8");
    const son = css.slice(css.indexOf("UX4 Bulgu 7"));
    expect(son).toMatch(/\.asistan-baslatici-metin\s*\{\s*display:\s*none;/);
    expect(son).toMatch(/\.asistan-baslatici:focus-visible \.asistan-baslatici-metin/);
    expect(son).toMatch(/body:has\(\.asistan-baslatici-kap\) \.icerik\s*\{\s*padding-bottom:\s*96px;/);
  });
});

describe("Bulgu 8: varsayım doğrulama onayında varsayım metni", () => {
  it("onay kutusu doğrulanacak varsayımın metnini gösterir", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    const tc = (await api.caseler(V3_GEREKSINIM_ID)).find((c) => c.id === "case-v3-2")!;
    const metin = tc.varsayimlar?.find((a) => a.id === "A1")?.statement;
    expect(metin).toBeTruthy();
    sar(<CaseKarti tc={tc} guncellendi={() => {}} />);
    await u.click(screen.getByRole("button", { name: "Varsayım doğrulandı" }));
    const liste = within(screen.getByTestId("varsayim-dogrulama-onayi")).getByTestId("dogrulanacak-varsayimlar");
    expect(liste).toHaveTextContent(`A1 ${metin}`);
  });
});

describe("Bulgu 9 ve B16/B17 küçükleri", () => {
  it("teknik adı rozet yanında görünürken iki kez yazılmaz", () => {
    const { container } = render(<TeknikRozeti teknik="EP" adGorunur />);
    expect(container.textContent).toBe("EP");
    const { container: varsayilan } = render(<TeknikRozeti teknik="EP" />);
    expect(varsayilan.textContent).toMatch(/^EP \(/);
  });

  it("öncelik rozetinde iç içe parantez yok", async () => {
    await oturumAc("analist");
    const tc = (await api.caseler(V3_GEREKSINIM_ID)).find((c) => c.icerik.priority === "P1") as TestCase;
    sar(<CaseKarti tc={tc} guncellendi={() => {}} />);
    expect(screen.getByTestId("case-oncelik").textContent).toBe("P1 (Öncelik 1, en yüksek)");
  });

  it("ekip hedefi satırı KPI kartıyla aynı yuvarlanır", () => {
    const k = { kapsam: { gereksinim: 0.9167 }, tekrar: { oran: 0.079 }, review: { ortalama: 79.2 } } as unknown as CaseKalitesi;
    expect(hedefGuncelDegeri(k, "kapsam.gereksinim")).toBe("%92");
    expect(hedefGuncelDegeri(k, "tekrar.oran")).toBe("%7,9");
    expect(hedefGuncelDegeri(k, "review.ortalama")).toBe("%79,2");
  });

  it("dar ekranda şerit ayraçla başlamaz", () => {
    const css = readFileSync(resolve(kok, "styles.css"), "utf8");
    expect(css).toMatch(/@media \(max-width: 860px\) \{\s*\.durum-seridi ul \{[^}]*\}\s*\.durum-seridi li \+ li::before \{\s*content: none;/);
  });

  it("B16: son kullanıcı metninde ortam değişkeni adı görünmez", () => {
    expect(ortamAdlariniGizle("Kayıtlı REPLAY bu girdiyle eşleşmiyor (TP_REPLAY_STRICT=1, prova kipi).")).toBe(
      "Kayıtlı REPLAY bu girdiyle eşleşmiyor (prova kipi).",
    );
    expect(ortamAdlariniGizle("GitHub main için: `scripts/demo-web-sync.sh --main` (TP_FORGE_REMOTE_URL aynası gerekir).")).not.toMatch(/TP_/);
    expect(ortamAdlariniGizle("toolchain-worker'da TP_FORGE_REMOTE_URL (+ salt okunur TP_FORGE_REMOTE_TOKEN) gerekir.")).toBe(
      "toolchain-worker'da bir sunucu ayarı gerekir.",
    );
    expect(ortamAdlariniGizle("Ortam adı yok.")).toBe("Ortam adı yok.");
  });

  it("B16: yol haritası strict kartı ortam adı yazmaz", () => {
    const kaynak = readFileSync(resolve(kok, "pages/YolHaritasi.tsx"), "utf8");
    expect(kaynak).not.toMatch(/"[^"]*TP_REPLAY_STRICT[^"]*"/);
  });

  it("B17: PO yanıtı yazarı e-posta olarak gösterilmez", () => {
    const ayni = (k: string) => k;
    expect(poYazarAdi("Ürün Sahibi (PO)", ayni)).toBe("Ürün Sahibi (PO)");
    expect(poYazarAdi("po@sim.local", ayni)).toBe("");
    expect(poYazarAdi("PO", ayni)).toBe("");
    expect(poYazarAdi(null, ayni)).toBe("");
  });
});

describe("denetim kaydı özeti ortam adı göstermez (B16)", () => {
  it("Denetim sayfası özet sütununu ayıklar", async () => {
    await oturumAc("analist");
    const olaylar = await api.denetim();
    const ilk = olaylar.olaylar[0];
    const spy = vi.spyOn(api, "denetim").mockResolvedValue({
      ...olaylar,
      olaylar: [{ ...ilk, ozet: "Demo web: scripts/demo-web-sync.sh --main (TP_FORGE_REMOTE_URL aynası gerekir)." }],
    });
    uygulama("/denetim");
    await waitFor(() => expect(screen.getByText(/demo-web-sync\.sh --main/)).toBeInTheDocument());
    expect(document.body.textContent).not.toMatch(/TP_FORGE_REMOTE_URL/);
    spy.mockRestore();
  });
});
