import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { KAYNAK } from "../api/mock/fixtures";
import { mockOlayYayinla } from "../api/mock/olaylar";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { oturumAc } from "../test/yardimci";

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

describe("oturum ve yönlendirme", () => {
  it("oturumsuz kullanıcıyı girişe yönlendirir; girişten sonra role göre açılış ekranına gider", async () => {
    const u = userEvent.setup();
    uygulama("/kosular");
    expect(await screen.findByRole("heading", { name: "Oturum aç" })).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Giriş yap" }));
    expect(screen.getByRole("alert")).toHaveTextContent("zorunlu");
    await u.type(screen.getByLabelText("Kullanıcı adı"), "yok");
    await u.type(screen.getByLabelText("Parola"), "x");
    await u.click(screen.getByRole("button", { name: "Giriş yap" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Kullanıcı adı veya parola hatalı.");
    await u.clear(screen.getByLabelText("Kullanıcı adı"));
    await u.type(screen.getByLabelText("Kullanıcı adı"), "sunucu");
    await u.click(screen.getByRole("button", { name: "Giriş yap" }));
    // Geldiği sayfaya (koşular) döner
    expect(await screen.findByRole("heading", { name: "Koşular", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("ÖRNEK VERİ")).toBeInTheDocument();
  });

  it("menü role duyarlı: Claude Code kanalı yalnızca analiste görünür", async () => {
    await oturumAc("muhendis");
    uygulama("/");
    expect(await screen.findByRole("heading", { name: "Kod üretimi", level: 1 })).toBeInTheDocument();
    const menu = screen.getByRole("navigation", { name: "Ana menü" });
    expect(within(menu).queryByText("Claude Code kanalı")).toBeNull();
    expect(within(menu).getByText("Kontrol Kulesi")).toBeInTheDocument();
  });

  it("yetkisiz rolde Claude Code ekranı erişim mesajı verir", async () => {
    await oturumAc("testci");
    uygulama("/claude-code");
    expect(await screen.findByText("Bu ekran için yetkiniz yok.")).toBeInTheDocument();
  });

  it("çıkış oturumu kapatır", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama("/denetim");
    await screen.findByRole("heading", { name: "Denetim", level: 1 });
    await u.click(screen.getByRole("button", { name: "Çıkış" }));
    expect(await screen.findByRole("heading", { name: "Oturum aç" })).toBeInTheDocument();
  });
});

describe("ekranlar", () => {
  it("gereksinim listesi durum çiplerini ve serbest metin satırını gösterir", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler");
    expect(await screen.findByText("Kampanyalı sepet ve sipariş onayı")).toBeInTheDocument();
    expect(screen.getByText("AC eksik")).toBeInTheDocument();
    // TPD-1: core durumu `done`, akış ipucu 6 (Review + kırma)
    expect(screen.getByText("Case'ler yayınlandı")).toBeInTheDocument();
    expect(screen.getByText("Review + kırma")).toBeInTheDocument();
    // TPD-1 case sayacı: 9 üretildi, 1 reddedildi → süitte 8; 4'ü onaylı/yayında
    expect(screen.getByText("4/8")).toBeInTheDocument();
    expect(screen.getByText("Serbest metin")).toBeInTheDocument();
  });

  it("serbest metin formu gereksinim oluşturup detaya gider", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama("/gereksinimler");
    await screen.findByText("Kampanyalı sepet ve sipariş onayı");
    await u.click(screen.getByRole("button", { name: "Serbest metin gereksinim" }));
    await u.type(screen.getByLabelText("Başlık"), "Sipariş iptali");
    await u.type(screen.getByLabelText("Açıklama"), "Bayi onaylanmamış siparişi iptal edebilmeli.");
    await u.type(screen.getByLabelText("AC1"), "İptal edilen sipariş geçmişte 'İptal' görünür.");
    await u.click(screen.getByRole("button", { name: "Gereksinimi oluştur" }));
    expect(await screen.findByRole("heading", { level: 1, name: /Sipariş iptali/ })).toBeInTheDocument();
    expect(screen.getByText("Serbest metin gereksinim")).toBeInTheDocument();
  });

  it("TPD-1 detayı: 4 bilinçli uyumsuzluk (+2. tur uyarısı) kanıtlı ve kararlı görünür", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler/req-tpd-1");
    // Golden TPD-1 F2 "observed" metni aynen.
    const f2 = KAYNAK.consistency_check["TPD-1"].findings.find((x) => x.id === "F2")!.observed;
    expect(await screen.findByText(f2)).toBeInTheDocument();
    const bulgular = await screen.findAllByRole("article");
    expect(bulgular).toHaveLength(5);
    expect(screen.getByText("api/src/demoapp_api/campaign.py:23")).toBeInTheDocument();
    expect(screen.getAllByText("api/src/demoapp_api/pricing.py:97").length).toBeGreaterThan(0);
    expect(screen.getAllByText("SELECT anahtar, deger FROM ayar WHERE anahtar = 'min_siparis_tutari'").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/kanıt doğrulandı/)).toHaveLength(5);
    expect(screen.getByText("Doküman ↔ kod")).toBeInTheDocument();
    expect(screen.getByText("Doküman ↔ veri")).toBeInTheDocument();
    expect(screen.getAllByText("Kodda eksik")).toHaveLength(2);
    expect(screen.getByText("İç çelişki")).toBeInTheDocument();
    expect(screen.getByText("po@sim.local")).toBeInTheDocument();
  });

  it("serbest metin: PO rolü portalda onaylar", async () => {
    // Önce analist bulguları kapatır
    const { api } = await import("../api/client");
    await oturumAc("analist");
    const bulgular = await api.bulgular("req-ft-1");
    const hash = (id: string) => bulgular.find((b) => b.id === id)!.icerik_hash;
    await api.bulguKarari("fnd-5", { icerik_hash: hash("fnd-5"), karar: "fix_doc" });
    await api.bulguKarari("fnd-6", { icerik_hash: hash("fnd-6"), karar: "accept_difference", gerekce: "ok" });
    await api.duzeltmeleriUygula("req-ft-1");
    await new Promise((r) => setTimeout(r, 20));
    await api.logout();
    await oturumAc("po");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    const dugme = await screen.findByRole("button", { name: "PO olarak onayla" });
    await u.click(dugme);
    expect(await screen.findByText("Onaylı")).toBeInTheDocument();
  });

  it("PO onayı: içerik ekranda görüldükten sonra değiştiyse 409 → yeniden yükler, ikinci denemede onaylar", async () => {
    const { mockVerisi } = await import("../api/mock/handlers");
    const g = mockVerisi().gereksinimler.find((x) => x.id === "req-ft-1")!;
    g.durum = "pending_po";
    g.po = { durum: "pending", onaylayan: null, zaman: null, kanal: "portal" };
    await oturumAc("po");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-ft-1");
    const dugme = await screen.findByRole("button", { name: "PO olarak onayla" });
    // PO ekrana baktıktan sonra açıklama değişti (ör. analist düzeltme yazdı).
    g.aciklama = `${g.aciklama} Ek cümle.`;
    await u.click(dugme);
    expect(await screen.findByRole("alert")).toHaveTextContent("İçerik değişti, yeniden inceleyin.");
    expect(g.durum).toBe("pending_po");
    expect(await screen.findByText(/Ek cümle\./)).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "PO olarak onayla" }));
    expect(await screen.findByText("Onaylı")).toBeInTheDocument();
    expect(g.durum).toBe("po_approved");
  });

  it("script listesi: core durumu + türetilmiş işaret (merge'e hazır / zayıf test)", async () => {
    await oturumAc("muhendis");
    uygulama("/kod");
    const hazir = (await screen.findByRole("link", { name: /7 adet kampanyalı/ })).closest("tr")!;
    expect(within(hazir).getByText("PR açık")).toBeInTheDocument();
    expect(within(hazir).getByText("Merge'e hazır")).toBeInTheDocument();
    const zayif = screen.getByRole("link", { name: /sepet sayacı/ }).closest("tr")!;
    expect(within(zayif).getByText("PR açık")).toBeInTheDocument();
    expect(within(zayif).getByText("Zayıf test")).toBeInTheDocument();
  });

  it("merge: PR incelendikten sonra koda commit geldiyse 409 → yeniden yükler, merge olmaz", async () => {
    const { mockVerisi } = await import("../api/mock/handlers");
    await oturumAc("muhendis");
    const u = userEvent.setup();
    uygulama("/kod/scr-2");
    const dugme = await screen.findByRole("button", { name: "Merge et" });
    await waitFor(() => expect(dugme).toBeEnabled());
    mockVerisi().scriptler.find((s) => s.id === "scr-2")!.kod += "\n// sonradan\n";
    await u.click(dugme);
    expect(await screen.findByText("İçerik değişti, yeniden inceleyin.")).toBeInTheDocument();
    expect(mockVerisi().scriptler.find((s) => s.id === "scr-2")!.durum).toBe("pr_open");
    await u.click(screen.getByRole("button", { name: "Merge et" }));
    await waitFor(() => expect(mockVerisi().scriptler.find((s) => s.id === "scr-2")!.durum).toBe("merged"));
  });

  it("kod üretimi detayı canlı agent.step olayını ekler", async () => {
    await oturumAc("muhendis");
    uygulama("/kod/scr-2");
    expect(await screen.findByText("Test hata yakalıyor ✓")).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: /ekran görüntüsü/ })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Merge et" })).toBeEnabled();
    // Olay yolu abonelikten önce yayınlanan olayı kaçırır: önce bağlantının kurulmasını bekle.
    expect(await screen.findByText("Olaylar: örnek veri")).toBeInTheDocument();
    await act(async () => {
      mockOlayYayinla({
        type: "agent.step",
        id: "scr-2",
        data: { sira: 9, step_id: "S4", arac: "browser_snapshot", aciklama: "Canlı yeni adım", po: null, method: null, args: [], verified: true, ekran_goruntusu_url: null, zaman: "2026-10-30T12:00:00Z" },
      });
    });
    expect(await screen.findByText("Canlı yeni adım")).toBeInTheDocument();
  });

  it("triage: sınıf, sinyaller ve locator onarım önerisi", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    uygulama("/hatalar/fail-2");
    expect(await screen.findByText("Test bakımı")).toBeInTheDocument();
    expect(screen.getByText("getByTestId('add-to-cart') 0 eleman döndürdü")).toBeInTheDocument();
    expect(screen.getByText('"cart-add"')).toBeInTheDocument();
    expect(screen.queryByText(/%\s*\d|güven(:|i\s*%)/i)).toBeNull();
    await u.click(screen.getByRole("button", { name: "Onarım PR'ı aç" }));
    expect(await screen.findByText("PR açık")).toBeInTheDocument();
  });

  it("bug taslağı: mükerrer adayıyla bağlanır", async () => {
    await oturumAc("testci");
    const u = userEvent.setup();
    uygulama("/bug-taslaklari/bug-1");
    expect(await screen.findByText("TPD-5")).toBeInTheDocument();
    expect(screen.getByLabelText("Jira anahtarı")).toHaveValue("TPD-5");
    // Artifact sunucusu yok: kanıtlar tıklanamaz metin (ölü bağlantı yok)
    expect(screen.getByText("Playwright trace (run-107)").closest("a")).toBeNull();
    await u.click(screen.getByRole("button", { name: "Mevcut kayda bağla" }));
    expect(await screen.findByText("Bağlandı: TPD-5")).toBeInTheDocument();
  });

  it("bug taslağı: değişen taslakta 409 → yeniden yükler; reddedilen taslak Jira'ya yazılmaz", async () => {
    const { mockVerisi } = await import("../api/mock/handlers");
    await oturumAc("testci");
    const u = userEvent.setup();
    uygulama("/bug-taslaklari/bug-1");
    const dugme = await screen.findByRole("button", { name: "Taslağı reddet" });
    await waitFor(() => expect(dugme).toBeEnabled());
    mockVerisi().bugTaslaklari.find((b) => b.id === "bug-1")!.icerik.actual = "Triage yeniden çalıştı: indirim 5,00 TL";
    await u.click(dugme);
    expect(await screen.findByRole("alert")).toHaveTextContent("İçerik değişti, yeniden inceleyin.");
    expect(await screen.findByDisplayValue("Triage yeniden çalıştı: indirim 5,00 TL")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Taslağı reddet" }));
    expect(await screen.findByText("Reddedildi")).toBeInTheDocument();
    expect(mockVerisi().bugTaslaklari.find((b) => b.id === "bug-1")!).toMatchObject({ durum: "dismissed", jira_key: null });
  });

  it("Kontrol Kulesi: kabul oranı, flaky, karne, erişilebilirlik", async () => {
    await oturumAc("sunucu");
    uygulama("/kontrol-kulesi");
    expect(await screen.findByText("Case kabul oranı")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Flaky testler" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Karne/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Erişilebilirlik" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Demoyu sıfırla" })).toBeInTheDocument();
  });

  it("denetim: zincir doğrulama sonucu", async () => {
    await oturumAc("analist");
    uygulama("/denetim");
    expect(await screen.findByText("✓ Zincir doğrulandı")).toBeInTheDocument();
  });

  it("Claude Code kanalı: token ve .mcp.json", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama("/claude-code");
    await u.click(await screen.findByRole("button", { name: "8 saatlik token oluştur" }));
    const blok = await screen.findByLabelText(".mcp.json içeriği");
    const json = JSON.parse(blok.textContent ?? "{}");
    expect(json.mcpServers["testing-probe"].url).toBe("http://127.0.0.1:8000/mcp");
    expect(json.mcpServers["testing-probe"].headers.Authorization).toMatch(/^Bearer tpk_mock_[0-9a-f]{48}$/);
  });

  it("koşu detayı test sonuçlarını ve triage bağlantısını gösterir", async () => {
    await oturumAc("analist");
    uygulama("/kosular/run-107");
    expect(await screen.findByText(/Gerçekleşen: "0,00 TL"/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Triage sonucu" })).toHaveAttribute("href", "/hatalar/fail-1");
    await waitFor(() => expect(screen.getByText(/BREAK_CAMPAIGN=1 ile açıldı/)).toBeInTheDocument());
  });

  it("bilinmeyen sayfa", async () => {
    await oturumAc("analist");
    uygulama("/yok-boyle-bir-sayfa");
    expect(await screen.findByText("Sayfa bulunamadı.")).toBeInTheDocument();
  });
});
