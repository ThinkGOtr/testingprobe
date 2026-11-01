// Faz 4 ekranları: triage (locator / ürün hatası / ortam), onarım hattı, bug kararı (bağla / yeni),
// demo kontrolleri ve defect adayında kırarak doğrulamanın kapalı olması.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { ayar, mockVerisi } from "../api/mock/handlers";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { oturumAc } from "../test/yardimci";
import { demoOlayMetni, kirmaKosusu } from "./DemoKontrolleri";
import { kararKaynagiMetni, onarimAsamalari } from "./HataDetay";
import { kosuHatalari } from "./Kosular";

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

beforeEach(() => {
  ayar.isAdimiMs = 0;
});

describe("triage ekranı", () => {
  it("locator: sınıf, karar kaynağı (kural), probe + aria + sağlık kanıtı; onarım hattı → merge", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    uygulama("/hatalar/fail-2");
    const sinif = await screen.findByTestId("triage-sinif");
    expect(sinif).toHaveTextContent("Test bakımı");
    expect(sinif).toHaveTextContent("Karar kaynağı: kural · test_maintenance/locator");
    // Kanıt: locator-probe (kapsam + DOM testId + commit eşleşmesi), aria parçası, sağlık.
    const probe = screen.getByRole("region", { name: "Locator yoklaması (locator-probe)" });
    expect(probe).toHaveTextContent("product-card-P-001");
    expect(probe).toHaveTextContent("cart-add");
    expect(probe).toHaveTextContent("commit eşleşiyor");
    expect(screen.getByRole("region", { name: /Aria snapshot/ })).toHaveTextContent('button "Sepete ekle"');
    expect(screen.getByRole("region", { name: /Sağlık yoklaması/ })).toHaveTextContent("başarılı");
    // Sinyal kanıtı görünür.
    expect(within(screen.getByRole("list", { name: "Eşleşen sinyaller" })).getByText(/matches=1 · test_id=cart-add/)).toBeInTheDocument();
    // Öneri: yalnızca testId; kapsam değişmez.
    expect(screen.getByLabelText("Locator değişikliği")).toHaveTextContent('addToCart.testId"add-to-cart"→yeni değer"cart-add"');
    expect(screen.getByText("product-card-")).toBeInTheDocument();

    await u.click(screen.getByRole("button", { name: "Onarım PR'ı aç" }));
    const merge = await screen.findByRole("button", { name: "Onarımı onayla ve merge et" }, { timeout: 5000 });
    await waitFor(() => expect(merge).toBeEnabled());
    const hat = screen.getByRole("list", { name: "Onarım hattı" });
    expect(hat).toHaveTextContent("AST koruması (onarım modu: yalnızca testId değeri) (tamam)");
    expect(hat).toHaveTextContent("Yerel kontrol: etkilenen tüm testler (3) (tamam)");
    expect(hat).toHaveTextContent("3/3 geçti");
    expect(screen.getByLabelText("Onarım yaması")).toHaveTextContent("+ testId: 'cart-add'");
    await u.click(merge);
    expect(await screen.findByText(/Onarım birleşti/)).toBeInTheDocument();
    expect(mockVerisi().denetim.some((d) => d.eylem === "pr.merge" && d.ozet.includes("Locator onarımı"))).toBe(true);
  });

  it("ortam hatası: onarım/bug önerisi yok, sağlık başarısız gösterilir", async () => {
    await oturumAc("muhendis");
    uygulama("/hatalar/fail-3");
    expect(await screen.findByText("Ortam sorunu")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /Sağlık yoklaması/ })).toHaveTextContent("başarısız");
    expect(screen.getByRole("region", { name: /Sağlık yoklaması/ })).toHaveTextContent("bağlantı reddedildi");
    expect(screen.queryByRole("button", { name: "Onarım PR'ı aç" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Bug taslağına git" })).toBeNull();
  });

  it("ürün hatası (C3 defect adayı): bug taslağına bağlantı, kural kararı model rozeti taşımaz", async () => {
    await oturumAc("testci");
    uygulama("/hatalar/fail-4");
    expect(await screen.findByTestId("triage-sinif")).toHaveTextContent("Ürün hatası");
    expect(screen.queryByText("REPLAY")).toBeNull();
    expect(screen.getByRole("link", { name: "Bug taslağına git" })).toHaveAttribute("href", "/bug-taslaklari/bug-4");
    expect(screen.getByRole("link", { name: "Üretilen test" })).toHaveAttribute("href", "/kod/scr-3");
  });

  it("karar kaynağı metni ve onarım aşamaları (bilinmeyen = bekliyor, uydurma yeşil yok)", () => {
    expect(kararKaynagiMetni({ karar_kaynagi: "llm", kural: null })).toBe("Karar kaynağı: LLM (kural eşleşmedi)");
    expect(kararKaynagiMetni({ karar_kaynagi: "rule", kural: null })).toBe("Karar kaynağı: deterministik kural");
    const a = onarimAsamalari({
      tur: "locator_fix",
      dosya: "x",
      anahtar: "k",
      eski_test_id: "a",
      yeni_test_id: "b",
      rol: "button",
      ad: "n",
      dogrulama: [],
      durum: "proposed",
      pr: null,
    });
    expect(a.slice(1).map((x) => x.durum)).toEqual(["bekliyor", "bekliyor", "bekliyor", "bekliyor", "bekliyor"]);
  });
});

describe("bug taslağı kararı (testçi)", () => {
  it("C3 taslağı: TPD-5 yüksek olasılık + AI gerekçesi, REPLAY yanında 'canlı değerlendirme bekliyor'; bağla → Jira bağlantısı", async () => {
    await oturumAc("testci");
    const u = userEvent.setup();
    uygulama("/bug-taslaklari/bug-4");
    const liste = await screen.findByRole("list", { name: "Mükerrer adayları" });
    const tpd5 = within(liste).getAllByRole("listitem")[0];
    expect(tpd5).toHaveTextContent("yüksek olasılık");
    expect(tpd5).toHaveTextContent("AI gerekçesi: Aynı belirti");
    expect(within(tpd5).getByRole("link", { name: /^TPD-5/ })).toHaveAttribute("href", "http://127.0.0.1:8090/browse/TPD-5");
    expect(screen.getByTestId("mukerrer-onerisi")).toHaveTextContent("mevcut kayda bağla (TPD-5)");
    expect(screen.getAllByText("canlı değerlendirme bekliyor").length).toBeGreaterThan(0);
    await u.click(within(tpd5).getByRole("button", { name: "TPD-5 kaydına bağla" }));
    const sonuc = await screen.findByTestId("yayin-sonucu");
    expect(sonuc).toHaveTextContent(/^TPD-5 .*kaydına bağlandı; TPD-1 ve TPD-11 ile ilişkilendirildi\.$/);
    expect(within(sonuc).getByRole("link", { name: /^TPD-5/ })).toHaveAttribute("href", "http://127.0.0.1:8090/browse/TPD-5");
    expect(mockVerisi().bugTaslaklari.find((b) => b.id === "bug-4")).toMatchObject({ durum: "published", karar: "link", link_key: "TPD-5" });
  });

  it("kırma taslağı (bug-1): AI önerisi yeni kayıt; düzenle + kaydet, sonra yeni kayıt → yeni Jira anahtarı", async () => {
    await oturumAc("testci");
    const u = userEvent.setup();
    uygulama("/bug-taslaklari/bug-1");
    expect(await screen.findByTestId("mukerrer-onerisi")).toHaveTextContent("yeni kayıt aç");
    const ozet = screen.getByLabelText("Özet");
    await u.clear(ozet);
    await u.type(ozet, "Sepet: 7 adette bedava verilmiyor (kırma koşusu)");
    await u.click(screen.getByRole("button", { name: "Değişiklikleri kaydet" }));
    await waitFor(() => expect(mockVerisi().bugTaslaklari.find((b) => b.id === "bug-1")!.icerik.summary).toBe("Sepet: 7 adette bedava verilmiyor (kırma koşusu)"));
    expect(mockVerisi().bugTaslaklari.find((b) => b.id === "bug-1")!.durum).toBe("draft");
    await u.click(await screen.findByRole("button", { name: "Onayla ve Jira'da aç" }));
    const sonuc = await screen.findByTestId("yayin-sonucu");
    expect(sonuc).toHaveTextContent(/^TPD-\d+ .*açıldı; TPD-1 ve TPD-10 ile ilişkilendirildi\.$/);
    expect(within(sonuc).getByRole("link")).toHaveAttribute("href", expect.stringMatching(/^http:\/\/127\.0\.0\.1:8090\/browse\/TPD-\d+$/));
  });

  it("karar düğmeleri yalnızca testçide etkin", async () => {
    await oturumAc("muhendis");
    uygulama("/bug-taslaklari/bug-4");
    expect(await screen.findByRole("button", { name: "Onayla ve Jira'da aç" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "TPD-5 kaydına bağla" })).toBeDisabled();
  });
});

describe("koşu detayı → triage", () => {
  it("test sonucuna bağlı olmayan ortam hatası koşu düzeyinde listelenir", async () => {
    await oturumAc("sunucu");
    uygulama("/kosular/run-109");
    const liste = await screen.findByRole("list", { name: "Triage kayıtları" });
    expect(liste).toHaveTextContent("Ortam · saglik");
    expect(within(liste).getByRole("link", { name: "Triage sonucunu aç" })).toHaveAttribute("href", "/hatalar/fail-3");
  });

  it("aynı failure'a bağlı sonuçlar tek kayıtta toplanır", () => {
    const k = mockVerisi().kosular.find((x) => x.id === "run-106")!;
    const h = kosuHatalari(k);
    expect(h).toHaveLength(1);
    expect(h[0]).toMatchObject({ id: "fail-2", sinif: "test_maintenance", alt_tur: "locator" });
  });
});

describe("kod üretimi: defect adayı", () => {
  it("Kırarak doğrula kapalı ve triage bağlantısı var", async () => {
    await oturumAc("muhendis");
    uygulama("/kod/scr-3");
    expect(await screen.findByText("Kırarak doğrulama kapalı")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Kırarak doğrula" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Triage sonucu ve bug taslağı" })).toHaveAttribute("href", "/hatalar/fail-4");
  });
});

describe("demo kontrolleri (sunucu)", () => {
  it("onay → kırılma → CI koşusu → triage önerisi bağlantısı; ikinci kırma 409", async () => {
    await oturumAc("sunucu");
    const u = userEvent.setup();
    uygulama("/demo");
    expect(await screen.findByRole("heading", { name: "Demo kontrolleri", level: 1 })).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Locator'ı kır" }));
    const onay = screen.getByRole("group", { name: "Locator kırma onayı" });
    expect(onay).toHaveTextContent("Emin misiniz?");
    await u.click(within(onay).getByRole("button", { name: "Evet, locator'ı kır" }));
    const ilerleme = await screen.findByRole("list", { name: "Locator kırılması ilerlemesi" });
    await waitFor(() => expect(within(ilerleme).getByRole("link", { name: "onarım önerisini aç" })).toHaveAttribute("href", "/hatalar/fail-2"), {
      timeout: 8000,
    });
    expect(ilerleme).toHaveTextContent("Başarısız");
    expect(screen.getByRole("list", { name: "Demo olay günlüğü" })).toHaveTextContent("demo-admin bypass");
    expect(mockVerisi().denetim.some((d) => d.eylem === "demo.break_locator" && d.ozet.includes("demo kırılması"))).toBe(true);
  }, 15000);

  it("sıfırlama onay kutusu işaretlenmeden çalışmaz", async () => {
    await oturumAc("sunucu");
    const u = userEvent.setup();
    uygulama("/demo");
    await u.click(await screen.findByRole("button", { name: "Demo'yu sıfırla" }));
    const g = screen.getByRole("group", { name: "Sıfırlama onayı" });
    expect(within(g).getByRole("button", { name: "Sıfırla" })).toBeDisabled();
    await u.click(within(g).getByRole("checkbox"));
    await u.click(within(g).getByRole("button", { name: "Sıfırla" }));
    expect(await screen.findByText(/Forge ve demo uygulaması sıfırlandı/)).toBeInTheDocument();
  });

  it("yalnızca sunucu rolü görür", async () => {
    await oturumAc("analist");
    uygulama("/demo");
    expect(await screen.findByText("Bu ekran için yetkiniz yok.")).toBeInTheDocument();
  });

  it("core demo olayları Türkçe günlük satırına çevrilir; kırma koşusu seçimi", () => {
    expect(demoOlayMetni({ type: "demo.break", data: { merge_sha: "abcdef1234567" } })).toMatchObject({ islem: "break", mesaj: expect.stringContaining("demo-admin bypass") });
    expect(demoOlayMetni({ type: "demo.web_ready", data: { eylem: "break", uygulama_sha: "1234567890ab" } })?.mesaj).toContain("1234567890");
    expect(demoOlayMetni({ type: "demo.reset", data: {} })?.islem).toBe("reset");
    expect(demoOlayMetni({ type: "demo.bilinmez", data: {} })).toBeNull();
    const t0 = Date.parse("2026-10-31T10:00:00Z");
    const k = (id: string, tetik: string, dk: number) =>
      ({ id, tetik, baslangic: new Date(t0 + dk * 60000).toISOString() }) as unknown as Parameters<typeof kirmaKosusu>[0][number];
    const kosular = [k("eski", "push", -10), k("lc", "local_check", 1), k("yeni", "push", 2), k("sonra", "push", 5)];
    expect(kirmaKosusu(kosular, t0)?.id).toBe("yeni");
    expect(kirmaKosusu(kosular, t0, "sonra")?.id).toBe("sonra");
  });
});
