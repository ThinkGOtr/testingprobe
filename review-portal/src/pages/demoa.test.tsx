// Demo-A ekranlarının çekirdek API'ye bağlanan davranışları (örnek veri arka ucuyla; çekirdek
// şekli uyum.demoa.test.ts'te). Ölçüm, yeniden açma, kanıt eleme, tur sayacı, yayın, token.
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ApiError } from "../api/http";
import { mockVerisi } from "../api/mock/handlers";
import { mockOlayYayinla } from "../api/mock/olaylar";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { goruntulenenleriSifirla } from "../components/CaseKarti";
import { gozlemciKur } from "../test/gorunurluk";
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

beforeEach(() => goruntulenenleriSifirla());

describe("gereksinim detayı", () => {
  it("kanıtı doğrulanmamış ve elenen bulgular gösterilmez, yalnızca sayılır; tur sayacı düğmede", async () => {
    const b = mockVerisi().bulgular.filter((x) => x.requirement_id === "req-ft-1");
    b[0].durum = "unverified";
    mockVerisi().bulgular.push({ ...b[1], id: "fnd-elenen", durum: "discarded", ozet: "Elenen bulgu metni" });
    await oturumAc("analist");
    uygulama("/gereksinimler/req-ft-1");
    const sayac = await screen.findByTestId("bulgu-sayaclari");
    expect(sayac).toHaveTextContent("Kontrol turu 1/3");
    expect(sayac).toHaveTextContent("Gösterilen 2");
    expect(sayac).toHaveTextContent("Kanıt doğrulanıyor 1");
    expect(sayac).toHaveTextContent("Kanıtı doğrulanamadığı için elenen 1");
    expect(screen.getAllByRole("article")).toHaveLength(2);
    expect(screen.queryByText("Elenen bulgu metni")).toBeNull();
    expect(screen.getByRole("button", { name: /Düzeltmeleri uygula · tur 1\/3/ })).toBeDisabled();
  });

  it("tur sınırında düzeltme düğmesi kapanır ve insan kararı istenir", async () => {
    await oturumAc("analist");
    const g = mockVerisi().gereksinimler.find((x) => x.id === "req-ft-1")!;
    const hash = (id: string) => mockVerisi().bulgular.find((x) => x.id === id)!.icerik_hash;
    await api.bulguKarari("fnd-5", { icerik_hash: hash("fnd-5"), karar: "fix_doc" });
    g.kontrol_turu = 3;
    uygulama("/gereksinimler/req-ft-1");
    expect(await screen.findByText(/Kontrol turu sınırına ulaşıldı \(3\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Düzeltmeleri uygula \(1\) · tur 3\/3/ })).toBeDisabled();
  });

  it("PO onayı kimin/ne zaman ve onaylanan içerik hash'iyle görünür; finding.verified ekranı yeniler", async () => {
    await oturumAc("analist");
    const g = mockVerisi().gereksinimler.find((x) => x.id === "req-tpd-1")!;
    g.po.onaylanan_hash = "sha256:0123456789abcdef0123";
    uygulama("/gereksinimler/req-tpd-1");
    expect(await screen.findByText("po@sim.local")).toBeInTheDocument();
    expect(screen.getByText("sha256:0123456789ab…")).toBeInTheDocument();
    // İçerik onaydan sonra değişti (hash farklı): yeniden PO teyidi gerektiği söylenir.
    expect(screen.getByText(/yeniden PO teyidi gerekir/)).toBeInTheDocument();
    const once = screen.getAllByRole("article").length;
    mockVerisi().bulgular.push({ ...mockVerisi().bulgular.find((x) => x.requirement_id === "req-tpd-1")!, id: "fnd-yeni", ozet: "SSE ile gelen bulgu" });
    await act(async () => {
      mockOlayYayinla({ type: "finding.verified", id: "fnd-yeni", data: { requirement_id: "req-tpd-1" } });
    });
    expect(await screen.findByText("SSE ile gelen bulgu")).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(once + 1);
  });
});

describe("PO teyidi insan kapısı şeridi", () => {
  it("onaylı ve içerik değişmemişse kapi-gecti; içerik onaydan sonra değiştiyse ya da onay yoksa kapi-bekliyor", async () => {
    await oturumAc("analist");
    const g = mockVerisi().gereksinimler.find((x) => x.id === "req-tpd-1")!;
    g.po = { ...g.po, durum: "approved" };
    g.po.onaylanan_hash = g.icerik_hash ?? null;
    const { unmount } = uygulama("/gereksinimler/req-tpd-1");
    const kart = await screen.findByRole("region", { name: "PO teyidi" });
    expect(kart).toHaveClass("insan-kapisi", "kapi-gecti");
    expect(kart).not.toHaveClass("kapi-bekliyor");
    unmount();

    g.po.onaylanan_hash = "sha256:0123456789abcdef0123";
    const ikinci = uygulama("/gereksinimler/req-tpd-1");
    await screen.findByText(/yeniden PO teyidi gerekir/);
    expect(screen.getByRole("region", { name: "PO teyidi" })).toHaveClass("kapi-bekliyor");
    ikinci.unmount();

    const bekleyen = mockVerisi().gereksinimler.find((x) => x.po.durum !== "approved")!;
    uygulama(`/gereksinimler/${bekleyen.id}`);
    const k3 = await screen.findByRole("region", { name: "PO teyidi" });
    expect(k3).toHaveClass("kapi-bekliyor");
    expect(k3).not.toHaveClass("kapi-gecti");
  });
});

describe("case review", () => {
  it("karar bekleyen case'ler 3 sn görünür kalınca görüntülendi olarak bir kez bildirilir; review süresi bundan ölçülür", async () => {
    const g = gozlemciKur();
    await oturumAc("analist");
    const casus = vi.spyOn(api, "caseGoruntulendi");
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const u = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    uygulama("/gereksinimler/req-tpd-1/caseler");
    await screen.findByText("Case review");
    // K13: gözlenen (karar bekleyen) kartlar görünür olur, 3 sn dolar.
    await waitFor(() => expect(g.gozlenenler().length).toBe(2));
    for (const el of g.gozlenenler()) g.goster(el);
    await act(async () => void (await vi.advanceTimersByTimeAsync(3000)));
    await waitFor(() => expect(casus).toHaveBeenCalledTimes(2));
    const bildirilen = casus.mock.calls.map((c) => c[0]).sort();
    // Yalnızca taslak (karar bekleyen) case'ler: case-1-5, 1-7 (C8 ve C9 yayınlandı: 011 dil örnekleri)
    expect(bildirilen).toEqual(["case-1-5", "case-1-7"]);
    await waitFor(() => expect(mockVerisi().caseler.find((c) => c.id === "case-1-7")!.goruntulenme).toBeTruthy());
    const kart = screen.getAllByRole("article").find((a) => within(a).queryByText(/^#6$/))!;
    await u.click(within(kart).getByRole("button", { name: "Onayla" }));
    await waitFor(() => expect(mockVerisi().caseler.find((c) => c.id === "case-1-7")!.review_sure_ms).not.toBeNull());
    expect(casus).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("analist olmayan rol görüntüleme bildirmez (ölçüm yalnızca karar verenin süresi)", async () => {
    await oturumAc("muhendis");
    const casus = vi.spyOn(api, "caseGoruntulendi");
    uygulama("/gereksinimler/req-tpd-1/caseler");
    await screen.findAllByRole("article");
    expect(casus).not.toHaveBeenCalled();
  });

  it("reddedilen case yeniden açılır: taslağa döner ve kararlar yeniden açılır; sayaçlar güncellenir", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-tpd-1/caseler");
    await screen.findByText("Reddedilen (2)");
    const red = screen.getAllByRole("article").find((a) => within(a).queryByText("Reddedildi"))!;
    expect(within(red).queryByRole("button", { name: "Onayla" })).toBeNull();
    await u.click(within(red).getByRole("button", { name: "Yeniden aç" }));
    await waitFor(() => expect(within(red).getByRole("button", { name: "Onayla" })).toBeEnabled());
    expect(mockVerisi().caseler.find((c) => c.id === "case-1-6")).toMatchObject({ durum: "draft" });
    expect(within(red).getByText(/taslağa alındı \(önceki karar: ret\)/)).toBeInTheDocument();
    expect(screen.getByText("Reddedilen (1)")).toBeInTheDocument();
    // Yayınlanmış case için yeniden açma yok (son durum).
    const yayinda = screen.getAllByRole("article").find((a) => within(a).queryByText("TPD-9"))!;
    expect(within(yayinda).queryByRole("button", { name: "Yeniden aç" })).toBeNull();
  });

  it("özet: AI + review süresi ve ölçülen case sayısı", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler/req-tpd-1/caseler");
    expect(await screen.findByText("AI + review")).toBeInTheDocument();
    expect(screen.getByText(/8 case · ort\./)).toBeInTheDocument();
    // Çekirdek ölçümü geldiğinde kabul oranı ilk karara göre etiketlenir.
    expect(await screen.findByText("Kabul oranı (ilk karar: onay + küçük düzeltme / üretilen)")).toBeInTheDocument();
  });
});

describe("yayın", () => {
  it("hedef, kısmi başarı ve jira-sim bağlantılı dış anahtarlar", async () => {
    await oturumAc("analist");
    const hash = (id: string) => mockVerisi().caseler.find((c) => c.id === id)!.icerik_hash;
    await api.caseKarari("case-1-7", { icerik_hash: hash("case-1-7"), karar: "approve" });
    const gercek = api.yayinla;
    // Kısmi sonuç: biri oluşturuldu, biri başarısız (ör. Jira 5xx sonrası).
    vi.spyOn(api, "yayinla").mockImplementation(async (ids) => {
      const s = await gercek(ids);
      return { ...s, sonuclar: [...s.sonuclar, { case_id: "case-x", durum: "failed", external_key: null, url: null, hata: "Jira 503" }] };
    });
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-tpd-1/yayin");
    expect(await screen.findByTestId("yayin-hedefi")).toHaveTextContent("Jira (Test issue) · proje TPD · http://127.0.0.1:8090");
    // Önizlemedeki mevcut anahtar jira-sim'e bağlanır.
    expect(screen.getByRole("link", { name: /TPD-9/ })).toHaveAttribute("href", "http://127.0.0.1:8090/browse/TPD-9");
    // case-1-4 (zaten onaylı) + case-1-7 (az önce onaylandı)
    await u.click(screen.getByRole("button", { name: /Seçilenleri yayınla \(2\)/ }));
    const ozet = await screen.findByTestId("yayin-ozeti");
    expect(ozet).toHaveTextContent("2 oluşturuldu");
    expect(ozet).toHaveTextContent("1 başarısız");
    expect(screen.getByText("Kısmi başarı")).toBeInTheDocument();
    const anahtar = mockVerisi().caseler.find((c) => c.id === "case-1-7")!.jira_test_key!;
    const linkler = screen.getAllByRole("link", { name: new RegExp(anahtar) });
    expect(linkler[0]).toHaveAttribute("href", `http://127.0.0.1:8090/browse/${anahtar}`);
    expect(screen.getByText(/Jira 503/)).toBeInTheDocument();
  });

  it("yayın arka plan işi döndürürse olaylarla tamamlanır", async () => {
    await oturumAc("analist");
    const hash = (id: string) => mockVerisi().caseler.find((c) => c.id === id)!.icerik_hash;
    await api.caseKarari("case-1-7", { icerik_hash: hash("case-1-7"), karar: "approve" });
    vi.spyOn(api, "yayinla").mockResolvedValue({ hedef: "jira", sonuclar: [], job_id: "job-9" });
    const u = userEvent.setup();
    uygulama("/gereksinimler/req-tpd-1/yayin");
    await u.click(await screen.findByRole("button", { name: /Seçilenleri yayınla/ }));
    expect(await screen.findByText(/Yayın işi sürüyor/)).toBeInTheDocument();
    await act(async () => {
      mockOlayYayinla({ type: "publish.completed", data: { requirement_id: "req-tpd-1" } });
    });
    await waitFor(() => expect(screen.queryByText(/Yayın işi sürüyor/)).toBeNull());
  });
});

describe("Claude Code kanalı", () => {
  it(".mcp.json token'ı ortam değişkeninden okur; token listesi ve iptal", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama("/claude-code");
    expect(await screen.findByText("Henüz token yok.")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "8 saatlik token oluştur" }));
    const blok = await screen.findByLabelText(".mcp.json (ortam değişkeniyle)");
    const json = JSON.parse(blok.textContent ?? "{}");
    expect(json.mcpServers["testing-probe"]).toEqual({
      type: "http",
      url: "http://127.0.0.1:8000/mcp",
      headers: { Authorization: "Bearer ${TP_MCP_TOKEN}" },
    });
    expect(screen.getByLabelText("Ortam değişkeni komutu")).toHaveTextContent(/^export TP_MCP_TOKEN=tpk_mock_[0-9a-f]{48}$/);
    expect(screen.getByLabelText("claude mcp add komutu")).toHaveTextContent(
      'claude mcp add --transport http --scope project testing-probe http://127.0.0.1:8000/mcp --header "Authorization: Bearer ${TP_MCP_TOKEN}"',
    );
    const tablo = await screen.findByRole("region", { name: "Token listesi" });
    expect(within(tablo).getByText("Etkin")).toBeInTheDocument();
    await u.click(within(tablo).getByRole("button", { name: "submit token'ını iptal et" }));
    expect(await within(tablo).findByText("İptal")).toBeInTheDocument();
  });

  it("core 501 (MCP ucu bağlı değil): token ve .mcp.json gösterilmez, nedeni yazılır", async () => {
    await oturumAc("analist");
    vi.spyOn(api, "tokenOlustur").mockRejectedValue(new ApiError(501, "IDE (MCP) kanalı henüz etkin değil; token üretilemez"));
    const u = userEvent.setup();
    uygulama("/claude-code");
    await u.click(await screen.findByRole("button", { name: "8 saatlik token oluştur" }));
    expect(await screen.findByText("IDE (MCP) kanalı henüz etkin değil")).toBeInTheDocument();
    expect(screen.queryByLabelText(/\.mcp\.json/)).toBeNull();
  });
});
