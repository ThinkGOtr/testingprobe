// Portal asistan paneli (AI-ASISTAN-PLANI §11, §13 "Portal (vitest)"): yetenek kapısı, yerleşim,
// başlık rozet kuralı, soru/cevap akışı, bekleme/iptal/yoklama/yeniden bağlanma, otomatik
// yükseltme, Jira/CI kaynakları, "Asistana sor", "? Bu ne?" ve data-asistan-gizli kuralı.
import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../../App";
import { asistanApi, oneriApi } from "../../api/asistan";
import { api } from "../../api/client";
import { ApiError, yapilandir } from "../../api/http";
import { asistanMockAyarla, asistanMockBaslat, asistanMockBekleyenler, asistanMockIsle } from "../../api/mock/asistan";
import { OturumProvider } from "../../auth";
import { hataKaydet, sonHatayiSifirla } from "../../lib/sonHata";
import { ClaudeCode } from "../../pages/ClaudeCode";
import { oturumAc } from "../../test/yardimci";
import { BildirimProvider } from "../Bildirim";
import { AsistanaSorDugmesi, HataKutusu } from "../ui";
import { AsistanPaneli } from "./AsistanPaneli";
import { elemanTanimi } from "./buNe";
import { acSekme, asistanKontrolSifirla, useAsistanKontrol } from "./kontrol";
import { sohbetAyar } from "./SohbetSekmesi";

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

/** Panel tek başına (OlayProvider yok → olay akışı "kapalı": yoklama dalı). */
function yalnizPanel(yol = "/kosular", ek?: ReactNode) {
  return render(
    <MemoryRouter initialEntries={[yol]}>
      <OturumProvider>
        <BildirimProvider>
          {ek}
          <AsistanPaneli />
        </BildirimProvider>
      </OturumProvider>
    </MemoryRouter>,
  );
}

const panel = () => screen.getByTestId("asistan-paneli");

async function paneliAc(u: ReturnType<typeof userEvent.setup>) {
  await u.click(await screen.findByRole("button", { name: "Asistanı aç" }));
  return panel();
}

async function sor(u: ReturnType<typeof userEvent.setup>, metin: string) {
  const alan = within(panel()).getByLabelText("Sorunuz");
  await u.clear(alan);
  await u.type(alan, metin);
  await u.click(within(panel()).getByRole("button", { name: "Asistana sor" }));
  await waitFor(() => expect(asistanMockBekleyenler().length).toBeGreaterThan(0));
  return asistanMockBekleyenler().at(-1)!;
}

function isle(id: string) {
  act(() => asistanMockIsle(id));
}

beforeEach(() => {
  asistanKontrolSifirla();
  sonHatayiSifirla();
  asistanMockAyarla({ otomatikIsle: false });
  // Olay akışı olmayan (yalnizPanel) testlerde cevap yoklamayla gelir: kısa aralık.
  Object.assign(sohbetAyar, { yoklamaMs: 30, uzunSurerMs: 25_000 });
});

afterEach(() => {
  vi.unstubAllGlobals();
  asistanKontrolSifirla();
  Object.assign(sohbetAyar, { yoklamaMs: 3000, uzunSurerMs: 25_000 });
});

describe("yerleşim ve yetenek kapısı", () => {
  it("oturumlu ekranda sağ altta düğme; /giris'te yok", async () => {
    uygulama("/giris");
    expect(await screen.findByRole("heading", { name: "Oturum aç" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Asistanı aç" })).toBeNull();
  });

  it("panel OlayProvider içinde: mock olayı gelince cevap kendiliğinden görünür (yoklamasız)", async () => {
    sohbetAyar.yoklamaMs = 60_000;
    await oturumAc("muhendis");
    const u = userEvent.setup();
    uygulama("/kosular");
    expect(await screen.findByRole("heading", { name: "Koşular", level: 1 })).toBeInTheDocument();
    await paneliAc(u);
    expect(screen.getByRole("complementary", { name: "Asistan" })).toBeInTheDocument();
    const id = await sor(u, "Kırarak doğrula neden gri?");
    isle(id);
    expect(await within(panel()).findByText("Kaynakla doğrulandı")).toBeInTheDocument();
  });

  it("canlı derlemede uç listesi okunurken gizli; uç yoksa gizli", async () => {
    yapilandir({ mockZorunlu: false, mockOtomatik: false, yetenekKesfi: true });
    let coz: (r: Response) => void = () => undefined;
    const f = vi.fn().mockImplementation((url: string) => {
      if (url === "/api/openapi.json") return new Promise<Response>((r) => (coz = r));
      return Promise.resolve(new Response("{}", { status: 404 }));
    });
    vi.stubGlobal("fetch", f);
    yalnizPanel();
    await act(async () => undefined);
    expect(screen.queryByRole("button", { name: /Asistan/ })).toBeNull();
    await act(async () => coz(new Response(JSON.stringify({ paths: { "/runs": { get: {} } } }), { status: 200 })));
    await act(async () => undefined);
    expect(screen.queryByRole("button", { name: /Asistan/ })).toBeNull();
    expect(f.mock.calls.map((c) => c[0])).not.toContain("/api/assistant/status");
  });

  it("uç listesi bilinmiyorsa (null) görünür; status 'bu fazda yok' → gizli", async () => {
    await oturumAc("analist");
    const { unmount } = yalnizPanel();
    expect(await screen.findByRole("button", { name: "Asistanı aç" })).toBeInTheDocument();
    unmount();
    asistanMockAyarla({ statusYok: true });
    yalnizPanel();
    await act(async () => undefined);
    await act(async () => undefined);
    expect(screen.queryByRole("button", { name: /Asistan/ })).toBeNull();
  });

  it("etkin=false → düğme pasif görünür ve nedeni söyler; tıklamak paneli nedeni gösteren uyarıyla açar", async () => {
    asistanMockAyarla({ etkin: false, neden: "maskeleme_kapali" });
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel();
    const d = await screen.findByRole("button", { name: /Asistan \(kapalı/ });
    expect(d).toHaveAccessibleName("Asistan (kapalı)");
    expect(d).toHaveClass("pasif");
    expect(d.getAttribute("title")).toMatch(/maskeleme/);
    // Neden düğmenin dışında görünür yazılır (dokunmatik/klavye title okumaz) ve açıklama olarak bağlıdır.
    expect(d).toHaveAccessibleDescription(/maskeleme/);
    const neden = document.getElementById(d.getAttribute("aria-describedby") ?? "");
    expect(neden).toHaveClass("dugme-neden", "asistan-baslatici-neden");
    expect(neden).toBeVisible();
    expect(neden).toHaveTextContent(/maskeleme/);
    expect(d.contains(neden)).toBe(false);
    await u.click(d);
    // Dokunmatikte title görünmez: neden panelde, Sohbet sekmesinde okunur; soru alanı yok.
    const p = panel();
    expect(within(p).getByText("Asistan kullanılamıyor")).toBeInTheDocument();
    expect(within(p).queryByLabelText("Sorunuz")).toBeNull();
  });

  it("Öneri düğmesi paneli Öneriler sekmesinde açar (acSekme); sekmeler tablist", async () => {
    await oturumAc("analist");
    yalnizPanel("/gereksinimler");
    await screen.findByRole("button", { name: "Asistanı aç" });
    act(() => acSekme("oneriler", { oneriKuralId: "r01" }));
    expect(screen.getByRole("tablist", { name: "Asistan sekmeleri" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Öneriler" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("oneriler-sekmesi")).toBeInTheDocument();
    // Yalnız seçili sekmenin paneli DOM'da: aria-controls var olan id'ye işaret eder.
    const secili = screen.getByRole("tab", { name: "Öneriler" });
    expect(document.getElementById(secili.getAttribute("aria-controls")!)).toHaveAttribute("role", "tabpanel");
    expect(screen.getByRole("tab", { name: "Sohbet" })).not.toHaveAttribute("aria-controls");
  });
});

describe("dar ekran", () => {
  it("< 760 px tam ekran modal dialog; Git paneli kapatır", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn((q: string) => ({ matches: q.includes("max-width"), media: q, addEventListener: () => undefined, removeEventListener: () => undefined })),
    );
    await oturumAc("muhendis");
    const u = userEvent.setup();
    yalnizPanel();
    await u.click(await screen.findByRole("button", { name: "Asistanı aç" }));
    const d = screen.getByRole("dialog", { name: "Asistan" });
    expect(d).toHaveAttribute("aria-modal", "true");
    isle(await sor(u, "Kırarak doğrula neden gri?"));
    await u.click(await within(d).findByRole("link", { name: "Git: Kod üretimi" }, { timeout: 3000 }));
    expect(screen.queryByTestId("asistan-paneli")).toBeNull();
  });

  it("dialog açılınca odak içeride, Tab panelde döner, odak dışarıdayken Esc kapatır, odak başlatıcıya döner", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn((q: string) => ({ matches: q.includes("max-width"), media: q, addEventListener: () => undefined, removeEventListener: () => undefined })),
    );
    await oturumAc("muhendis");
    const u = userEvent.setup();
    yalnizPanel();
    await u.click(await screen.findByRole("button", { name: "Asistanı aç" }));
    const d = screen.getByRole("dialog", { name: "Asistan" });
    expect(d).toContainElement(document.activeElement as HTMLElement);
    // Tab ve Shift+Tab odağı dışarı kaçırmaz.
    for (let i = 0; i < 25; i++) {
      await u.tab();
      expect(d).toContainElement(document.activeElement as HTMLElement);
    }
    await u.tab({ shift: true });
    expect(d).toContainElement(document.activeElement as HTMLElement);
    // Odak body'deyken de Esc kapatır (belge düzeyinde dinlenir).
    (document.activeElement as HTMLElement).blur();
    expect(document.activeElement).toBe(document.body);
    await u.keyboard("{Escape}");
    expect(screen.queryByTestId("asistan-paneli")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Asistanı aç" }));
  });

  it("dışarıdan (Öneri düğmesi gibi) açılan panel kapanınca odak açan öğeye döner", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel(
      "/gereksinimler",
      <button type="button" onClick={() => acSekme("sohbet")}>
        Dış açıcı
      </button>,
    );
    await screen.findByRole("button", { name: "Asistanı aç" });
    await u.click(screen.getByRole("button", { name: "Dış açıcı" }));
    expect(panel()).toContainElement(document.activeElement as HTMLElement);
    await u.click(within(panel()).getByRole("button", { name: "Asistanı kapat" }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Dış açıcı" }));
  });
});

describe("masaüstü odak", () => {
  it("masaüstü (< 1440 px): odak panelin altındaki sayfa öğesindeyken Esc paneli kapatır, odak o öğede kalır", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel(
      "/gereksinimler",
      <button type="button" data-testid="alttaki">
        Alttaki
      </button>,
    );
    await u.click(await screen.findByRole("button", { name: "Asistanı aç" }));
    const kutu = (left: number, right: number) => () => ({ left, right, top: 100, bottom: 140, width: right - left, height: 40, x: left, y: 100, toJSON: () => ({}) }) as DOMRect;
    const alttaki = screen.getByTestId("alttaki");
    vi.spyOn(panel(), "getBoundingClientRect").mockImplementation(kutu(860, 1280));
    vi.spyOn(alttaki, "getBoundingClientRect").mockImplementation(kutu(913, 966));
    act(() => alttaki.focus());
    expect(document.activeElement).toBe(alttaki);
    await u.keyboard("{Escape}");
    expect(screen.queryByTestId("asistan-paneli")).toBeNull();
    expect(document.activeElement).toBe(alttaki);
  });
});

describe("başlık", () => {
  it("canlı kipte rozet yok ve CANLI/live metni görünmez; denetim notu ve ÖRNEK VERİ var", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    expect(within(p).queryByText("HAZIR CEVAPLAR")).toBeNull();
    expect(p.textContent).not.toMatch(/\bCANLI\b|\blive\b/i);
    expect(within(p).getByText("Sorular denetim kaydına girer; sohbet 90 gün saklanır.")).toBeInTheDocument();
    expect(within(p).getAllByText("ÖRNEK VERİ").length).toBeGreaterThan(0);
  });

  it("kapalı kipte 'HAZIR CEVAPLAR' rozeti; soru önerileri yalnız modelsiz olanlar", async () => {
    asistanMockAyarla({ mod: "off" });
    await oturumAc("muhendis");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    expect(within(p).getByText("HAZIR CEVAPLAR")).toBeInTheDocument();
    const oneriler = within(p).getByRole("list", { name: "Soru önerileri" });
    expect(within(oneriler).getByText("Bugün ne yapmalıyım?")).toBeInTheDocument();
    expect(within(oneriler).queryByText("Son koşu neden düştü?")).toBeNull();
  });
});

describe("soru ve cevap", () => {
  it("bağlam çipi rotadan; gönderilen bağlam varlığı matchPath ile taşır; kart blokları düz metin", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    const casus = vi.spyOn(asistanApi, "soruGonder");
    yalnizPanel("/hatalar/f-77");
    const p = await paneliAc(u);
    expect(within(p).getByText(/Bu ekran: Hata analizi/)).toBeInTheDocument();
    const id = await sor(u, "Kırarak doğrula neden gri?");
    expect(casus.mock.calls[0][1].baglam).toMatchObject({ rota_kalibi: "/hatalar/:id", ekran: "Hata analizi", varlik: { tur: "failure", id: "f-77" } });
    expect(within(p).getByTestId("asistan-bekleme")).toHaveTextContent("Sırada bekliyor…");
    isle(id);
    const kart = await within(p).findByRole("article", { name: "Asistan cevabı" }, { timeout: 5000 });
    // Bloklar: kod bloğu metin olarak (HTML üretilmez).
    expect(within(kart).getByText(/<IslemDugmesi roller=/)).toBeInTheDocument();
    expect(kart.querySelector("islemdugmesi")).toBeNull();
    expect(within(kart).getByText("Kaynakla doğrulandı")).toBeInTheDocument();
    expect(within(kart).getByText("Bilgi amaçlıdır; kararı ilgili ekranda verin.")).toBeInTheDocument();
    // Doğrulanmamış kaynak soluk + uyarı.
    const dogrulanmamis = within(kart).getByText("docs/DEMO-AKISI.md:88").closest("li")!;
    expect(dogrulanmamis).toHaveClass("soluk-kaynak");
    expect(within(dogrulanmamis).getByText("doğrulanmadı")).toBeInTheDocument();
    expect(within(kart).getByRole("link", { name: "Git: Kod üretimi" })).toHaveAttribute("href", "/kod");
    expect(within(kart).getByText(/Bu saat kalan soru hakkı ≈ 29/)).toBeInTheDocument();
    expect(within(kart).getByText(/Maliyet: ≈/)).toBeInTheDocument();
    await u.click(within(kart).getByRole("button", { name: "Faydalı" }));
    await waitFor(() => expect(within(kart).getByRole("button", { name: "Faydalı" })).toHaveAttribute("aria-pressed", "true"));
    // Ürün kodu satırları modalda.
    await u.click(within(kart).getAllByRole("button", { name: "Satırları göster" })[0]);
    expect(screen.getByRole("dialog", { name: /ScriptDetay/ })).toHaveTextContent('roller={["engineer"]}');
  });

  it("sözlük/şablon cevabında maliyet 'ölçülmedi'; 2000 karakter sayacı gönderimi kilitler", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    const id = await sor(u, "Bugün ne yapmalıyım?");
    isle(id);
    const kart = await within(p).findByRole("article", {}, { timeout: 5000 });
    expect(within(kart).getByText("Maliyet: ölçülmedi")).toBeInTheDocument();
    expect(within(kart).getByText("Yapay zekâ kullanılmadı; hazır açıklama.")).toBeVisible();
    const alan = within(p).getByLabelText("Sorunuz");
    fireEvent.change(alan, { target: { value: "a".repeat(2001) } });
    expect(within(p).getByText("2001 / 2000")).toBeInTheDocument();
    expect(within(p).getByRole("button", { name: "Asistana sor" })).toBeDisabled();
  });

  it("Jira ve CI kaynakları: 'Jira yorumu (TPD-3, 2 gün önce)', 'CI logu (koşu #7, satır 412–418)', Jira'da aç yeni sekmede", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    const id = await sor(u, "TPD-3 yorumu ve lint logu ne söylüyor?");
    isle(id);
    const kart = await within(p).findByRole("article", {}, { timeout: 5000 });
    expect(within(kart).getByText("Jira yorumu (TPD-3, 2 gün önce)")).toBeInTheDocument();
    expect(within(kart).getByText("CI logu (koşu #7, satır 412–418)")).toBeInTheDocument();
    const jira = within(kart).getByRole("link", { name: /Jira'da aç/ });
    expect(jira).toHaveAttribute("target", "_blank");
    expect(jira.getAttribute("rel")).toMatch(/noopener/);
    await u.click(within(kart).getAllByRole("button", { name: "Alıntıyı göster" })[1]);
    expect(screen.getByRole("dialog")).toHaveTextContent("never used");
  });

  it("eylem isteği reddedilir ve ilgili ekrana yönlendirir", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    isle(await sor(u, "Bu case'i onayla"));
    const kart = await within(p).findByRole("article", {}, { timeout: 5000 });
    expect(within(kart).getByText("Asistan işlem yapmaz; bu işlemi ilgili ekranda siz yaparsınız.")).toBeInTheDocument();
    expect(within(kart).getByRole("link", { name: "Git: Gereksinimler" })).toBeInTheDocument();
  });

  it("409 bekleyen_var: başka sekmedeki bekleyen soru", async () => {
    await oturumAc("analist");
    const s = await asistanApi.sohbetOlustur(null);
    await asistanApi.soruGonder(s.id, { soru: "diğer sekme" });
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    await u.type(within(p).getByLabelText("Sorunuz"), "yeni soru");
    await u.click(within(p).getByRole("button", { name: "Asistana sor" }));
    expect(await within(p).findByText(/Yanıt bekleyen bir sorunuz var \(bu ya da başka bir sekmede\)/)).toBeInTheDocument();
  });

  it("yanıt bekleyen soru varken 'Neden? Sor' sohbetten ayrılmaz, boş sohbet açmaz; soru girdide kalır", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel("/gereksinimler");
    const p = await paneliAc(u);
    await sor(u, "ilk soru");
    const olustur = vi.spyOn(asistanApi, "sohbetOlustur");
    act(() => acSekme("sohbet", { oneriKuralId: "r01", soru: "Bu öneri neden çıktı?" }));
    expect(await within(p).findByText(/Yanıt bekleyen bir sorunuz var \(bu ya da başka bir sekmede\)/)).toBeInTheDocument();
    expect(olustur).not.toHaveBeenCalled();
    expect(within(p).getByTestId("asistan-bekleme")).toBeInTheDocument();
    expect(within(p).getByText("ilk soru")).toBeInTheDocument();
    expect(within(p).getByLabelText("Sorunuz")).toHaveValue("Bu öneri neden çıktı?");
  });

  it("yeni sohbette soru reddedilirse (409) önceki sohbet kalır ve açılan boş sohbet silinir", async () => {
    await oturumAc("analist");
    const s0 = await asistanApi.sohbetOlustur(null);
    await asistanApi.soruGonder(s0.id, { soru: "diğer sekme" });
    const u = userEvent.setup();
    yalnizPanel("/gereksinimler");
    const p = await paneliAc(u);
    const sil = vi.spyOn(asistanApi, "sohbetSil");
    act(() => acSekme("sohbet", { oneriKuralId: "r01", soru: "Bu öneri neden çıktı?" }));
    expect(await within(p).findByText(/Yanıt bekleyen bir sorunuz var/)).toBeInTheDocument();
    await waitFor(() => expect(sil).toHaveBeenCalledTimes(1));
    expect(within(p).getByLabelText("Sorunuz")).toHaveValue("Bu öneri neden çıktı?");
  });

  it("mesaj hatası: girdi_tavani → 'Soru çok geniş' daraltma önerisi", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    const id = await sor(u, "her şeyi anlat");
    const { asistanMockHata } = await import("../../api/mock/asistan");
    act(() => asistanMockHata(id, "girdi_tavani"));
    expect(await within(p).findByText(/Soru çok geniş/, {}, { timeout: 3000 })).toBeInTheDocument();
  });
});

describe("bekleme, iptal, yoklama, yeniden bağlanma", () => {
  it("Beklemeyi bırak: başlamamışsa ücret yok; başlamışsa işlenen kısım ücretlendi", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    await sor(u, "bir");
    await u.click(within(p).getByRole("button", { name: "Beklemeyi bırak" }));
    expect(await within(p).findByText(/İşlenmeye başlamadığı için ücret yok/)).toBeInTheDocument();
    const id = await sor(u, "iki");
    act(() => asistanMockBaslat(id));
    await u.click(within(p).getByRole("button", { name: "Beklemeyi bırak" }));
    expect(await within(p).findByText(/İşlenen kısım ücretlendi/)).toBeInTheDocument();
  });

  it("SSE kopukken ve yoklama henüz gelmeden 'running' mesaj durdurulursa not 'ücretlendi' der (core mesajı basladi taşımaz)", async () => {
    sohbetAyar.yoklamaMs = 60_000;
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    const id = await sor(u, "uzun soru");
    // Worker işi aldı; portal bunu ne olayla ne yoklamayla gördü (listede hâlâ `pending`).
    act(() => void asistanMockBaslat(id));
    const m = await asistanApi.mesaj(id);
    expect(m.durum).toBe("running");
    expect(m).not.toHaveProperty("basladi");
    expect(m).not.toHaveProperty("adim_kodu");
    await u.click(within(p).getByRole("button", { name: "Beklemeyi bırak" }));
    expect(await within(p).findByText(/İşlenen kısım ücretlendi/)).toBeInTheDocument();
  });

  it("bayat dış istek (Sohbet o sırada çizilemedi) sonradan gönderilmez", async () => {
    await oturumAc("analist");
    const gonder = vi.spyOn(asistanApi, "soruGonder");
    const simdi = Date.now();
    const saat = vi.spyOn(Date, "now").mockReturnValue(simdi - 60_000);
    act(() => acSekme("sohbet", { soru: "eski soru" }));
    saat.mockRestore();
    yalnizPanel();
    expect(await screen.findByTestId("asistan-paneli")).toBeInTheDocument();
    await act(async () => undefined);
    expect(gonder).not.toHaveBeenCalled();
    expect(renderHook(() => useAsistanKontrol()).result.current.istek).toBeNull();
  });

  it("asistan pasifken Sohbet'e yönelik dış istek tüketilir (hazıra dönünce gönderilmez)", async () => {
    await oturumAc("analist");
    asistanMockAyarla({ etkin: false, neden: "worker_yok" });
    const gonder = vi.spyOn(asistanApi, "soruGonder");
    yalnizPanel();
    act(() => acSekme("sohbet", { soru: "pasifken soru" }));
    expect(within(await screen.findByTestId("asistan-paneli")).getByText(/Asistan kullanılamıyor/)).toBeInTheDocument();
    await waitFor(() => expect(renderHook(() => useAsistanKontrol()).result.current.istek).toBeNull());
    expect(gonder).not.toHaveBeenCalled();
  });

  it("öneri sorusu 409 oneri_gecersiz alınca bu ekranın önerileri zorla yenilenir", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel("/gereksinimler/req-ft-1");
    const p = await paneliAc(u);
    const liste = vi.spyOn(oneriApi, "liste");
    vi.spyOn(asistanApi, "soruGonder").mockRejectedValueOnce(new ApiError(409, "geçersiz", { kod: "oneri_gecersiz" }));
    act(() => acSekme("sohbet", { oneriKuralId: "r01", soru: "Bu öneri neden çıktı?" }));
    expect(await within(p).findByText(/öneriler yenilendi/)).toBeInTheDocument();
    await waitFor(() => expect(liste).toHaveBeenCalledWith(expect.objectContaining({ varlik_id: "req-ft-1" })));
  });

  it("geçen süre sayacı canlı bölgede duyurulmaz (aria-hidden); adım metni duyurulur", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    await sor(u, "bir");
    const b = within(p).getByTestId("asistan-bekleme");
    const sayac = within(b).getByText(/· \d+ sn/);
    expect(sayac).toHaveAttribute("aria-hidden", "true");
    expect(sayac.closest('[role="status"]')).toBe(b);
  });

  it("SSE yokken yoklama; 25 sn sonra 'Uzun sürüyor'", async () => {
    sohbetAyar.uzunSurerMs = 0;
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    const id = await sor(u, "Kırarak doğrula neden gri?");
    expect(within(p).getByText("Uzun sürüyor")).toBeInTheDocument();
    act(() => asistanMockIsle(id));
    expect(await within(p).findByRole("article", {}, { timeout: 3000 })).toBeInTheDocument();
  });

  it("sayfa yenilenince açık panel ve bekleyen mesaja yeniden bağlanır", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    const ilk = yalnizPanel();
    await paneliAc(u);
    const id = await sor(u, "Kırarak doğrula neden gri?");
    ilk.unmount();
    yalnizPanel();
    const p = await screen.findByTestId("asistan-paneli");
    expect(await within(p).findByTestId("asistan-bekleme")).toBeInTheDocument();
    act(() => asistanMockIsle(id));
    expect(await within(p).findByRole("article", {}, { timeout: 3000 })).toBeInTheDocument();
  });

  it("geçmiş: sohbet listesi, silme onayı", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    isle(await sor(u, "Bugün ne yapmalıyım?"));
    // Bekleyen soru varken Geçmiş pasiftir: cevap gelince açılır.
    await waitFor(() => expect(within(p).getByRole("button", { name: "Geçmiş" })).toBeEnabled());
    await u.click(within(p).getByRole("button", { name: "Geçmiş" }));
    const sil = await within(p).findByRole("button", { name: /sohbetini sil/ });
    await u.click(sil);
    await u.click(within(within(p).getByRole("group", { name: "Silme onayı" })).getByRole("button", { name: "Sil" }));
    expect(await within(p).findByText("Henüz sohbet yok.")).toBeInTheDocument();
  });
});

describe("Daha ayrıntılı incele ve otomatik yükseltme", () => {
  it("elle: çocuk kart 'Ayrıntılı inceleme'; derin cevapta düğme yok", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    isle(await sor(u, "Kırarak doğrula neden gri?"));
    await u.click(await within(p).findByRole("button", { name: "Daha ayrıntılı incele" }, { timeout: 5000 }));
    await waitFor(() => expect(asistanMockBekleyenler()).toHaveLength(1));
    isle(asistanMockBekleyenler()[0]);
    const derin = await within(p).findByRole("article", { name: "Ayrıntılı inceleme" }, { timeout: 5000 });
    expect(within(derin).queryByRole("button", { name: "Daha ayrıntılı incele" })).toBeNull();
    expect(within(p).queryByRole("button", { name: "Daha ayrıntılı incele" })).toBeNull();
  });

  it("otomatik: 'Ön cevap' + 'Ayrıntılı inceleme sürüyor…' + Durdur; bu sırada yeni soru sorulabilir; bitince ön cevap daraltılır", async () => {
    await oturumAc("testci");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    isle(await sor(u, "Bundan emin değilim, neden?"));
    expect(await within(p).findByRole("article", { name: "Ön cevap (kaynakla doğrulanamadı)" }, { timeout: 5000 })).toBeInTheDocument();
    const bekleme = await within(p).findByTestId("asistan-bekleme");
    expect(bekleme).toHaveTextContent("Ayrıntılı inceleme sürüyor…");
    expect(within(bekleme).getByRole("button", { name: "Durdur" })).toBeInTheDocument();
    await u.type(within(p).getByLabelText("Sorunuz"), "başka");
    expect(within(p).getByRole("button", { name: "Asistana sor" })).toBeEnabled();
    isle(asistanMockBekleyenler()[0]);
    expect(await within(p).findByRole("article", { name: "Ayrıntılı inceleme" }, { timeout: 5000 })).toBeInTheDocument();
    const ozet = within(p).getByText("Ön cevap (kaynakla doğrulanamadı)", { selector: "summary" });
    expect(ozet.closest("details")).not.toHaveAttribute("open");
  });

  it("otomatik inceleme durdurulursa ön cevap kalır ve yeniden başlatılamaz notu görünür", async () => {
    await oturumAc("testci");
    const u = userEvent.setup();
    yalnizPanel();
    const p = await paneliAc(u);
    isle(await sor(u, "Bundan emin değilim, neden?"));
    await u.click(await within(p).findByRole("button", { name: "Durdur" }, { timeout: 5000 }));
    expect(await within(p).findByText("Ayrıntılı inceleme durduruldu; bu soru için yeniden başlatılamaz.")).toBeInTheDocument();
    expect(within(p).getByRole("article", { name: "Ön cevap (kaynakla doğrulanamadı)" })).toBeInTheDocument();
  });
});

describe("Asistana sor ve son hata", () => {
  it("HataKutusu kaynak verilince 'Asistana sor' paneli o kaydın bağlamıyla açar", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    const casus = vi.spyOn(asistanApi, "soruGonder");
    const hata = new ApiError(409, "İçerik değişti", { kod: "onay_hash_uyusmuyor", method: "POST", yol: "/cases/:id/review" });
    hataKaydet(hata);
    yalnizPanel("/gereksinimler", <HataKutusu hata="İçerik değişti, yeniden inceleyin." kaynak={hata} />);
    await u.click(await screen.findByRole("button", { name: "Asistana sor" }));
    const p = panel();
    expect(within(p).getByText(/Son hata: İçerik değişti, yeniden inceleyin\./)).toBeInTheDocument();
    expect(within(p).getByLabelText("Sorunuz")).toHaveValue("Bu hata ne demek, ne yapmalıyım?");
    await u.click(within(p).getByRole("button", { name: "Asistana sor" }));
    await waitFor(() => expect(casus).toHaveBeenCalled());
    expect(casus.mock.calls[0][1].baglam).toMatchObject({
      son_hata: { uc: "POST /cases/:id/review", status: 409, kod: "onay_hash_uyusmuyor", gorunen_metin: "İçerik değişti, yeniden inceleyin." },
    });
  });

  it("gerçek sayfa: yükleme hatasında HataKutusu 'Asistana sor' gösterir (kaynak=hataNesnesi)", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama("/gereksinimler/boyle-bir-gereksinim-yok");
    // Canlı bölge yalnız metindir; düğme kutuda kardeş öğedir.
    const kutu = (await screen.findByRole("alert", {}, { timeout: 5000 })).parentElement!;
    await u.click(within(kutu).getByRole("button", { name: "Asistana sor" }));
    expect(within(panel()).getByLabelText("Sorunuz")).toHaveValue("Bu hata ne demek, ne yapmalıyım?");
    expect(within(panel()).getByText(/Son hata:/)).toBeInTheDocument();
  });

  it("karar ekranlarının satır içi 409 uyarısında 'Asistana sor' (AsistanaSorDugmesi)", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    const hata = new ApiError(409, "Durum değişti", { kod: "durum_degisti", method: "POST", yol: "/findings/:id/decision" });
    hataKaydet(hata);
    yalnizPanel(
      "/gereksinimler",
      <p className="alan-hata" role="alert">
        İçerik değişti. <AsistanaSorDugmesi hata="İçerik değişti." kaynak={hata} />
      </p>,
    );
    await u.click(await screen.findByRole("button", { name: "Asistana sor" }));
    expect(within(panel()).getByText(/Son hata: İçerik değişti\./)).toBeInTheDocument();
  });

  it("kaynaksız HataKutusu'nda 'Asistana sor' yok", async () => {
    await oturumAc("analist");
    yalnizPanel("/gereksinimler", <HataKutusu hata="Bir şey oldu" />);
    await screen.findByRole("button", { name: "Asistanı aç" });
    expect(screen.queryByRole("button", { name: "Asistana sor" })).toBeNull();
  });
});

describe('"? Bu ne?"', () => {
  function sayfa() {
    return (
      <section className="kart">
        <div className="kart-baslik">
          <h2>Doğrulama</h2>
        </div>
        <span title="Yalnızca mühendis rolü">
          <button type="button" disabled data-yetkisiz>
            Kırarak doğrula
          </button>
        </span>
        <input aria-label="Ara" />
        <pre>
          <code>gizli kod</code>
        </pre>
        <div data-asistan-gizli>
          <span>gizli alan</span>
        </div>
      </section>
    );
  }

  it("bindirme elementsFromPoint ile disabled düğmeyi bulur; bağlama secili_eleman girer; input/pre/gizli yakalanmaz; Esc önce kipten çıkar", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    const casus = vi.spyOn(asistanApi, "soruGonder");
    yalnizPanel("/kod/s-1", sayfa());
    const p = await paneliAc(u);
    let hedef: Element = screen.getByRole("button", { name: "Kırarak doğrula" });
    const efp = vi.fn((_x: number, _y: number) => [screen.getByTestId("asistan-bune-bindirme"), hedef, document.body]);
    // jsdom elementsFromPoint uygulamaz: taklit edilir.
    Object.defineProperty(document, "elementsFromPoint", { configurable: true, value: efp });

    await u.click(within(p).getByRole("button", { name: "? Bu ne?" }));
    const bindirme = screen.getByTestId("asistan-bune-bindirme");
    hedef = screen.getByLabelText("Ara");
    fireEvent.click(bindirme, { clientX: 5, clientY: 5 });
    expect(screen.getByText(/Bu öğe asistana gönderilmez/)).toBeInTheDocument();
    hedef = screen.getByText("gizli kod");
    fireEvent.click(bindirme, { clientX: 5, clientY: 5 });
    expect(screen.getByText(/Bu öğe asistana gönderilmez/)).toBeInTheDocument();
    hedef = screen.getByText("gizli alan");
    fireEvent.click(bindirme, { clientX: 5, clientY: 5 });
    expect(screen.getByTestId("asistan-bune-bindirme")).toBeInTheDocument();

    hedef = screen.getByRole("button", { name: "Kırarak doğrula" });
    fireEvent.click(bindirme, { clientX: 10, clientY: 10 });
    expect(screen.queryByTestId("asistan-bune-bindirme")).toBeNull();
    expect(within(p).getByText(/Seçili: Kırarak doğrula/)).toBeInTheDocument();
    await u.type(within(p).getByLabelText("Sorunuz"), "Bu neden gri?");
    await u.click(within(p).getByRole("button", { name: "Asistana sor" }));
    await waitFor(() => expect(casus).toHaveBeenCalled());
    expect(casus.mock.calls[0][1].baglam).toMatchObject({
      secili_eleman: { ad: "Kırarak doğrula", rol: "button", devre_disi: true, ipucu: "Yalnızca mühendis rolü", kart_basligi: "Doğrulama" },
    });

    // Esc: önce "Bu ne?"den çıkar, sonra paneli kapatır.
    await u.click(within(p).getByRole("button", { name: "? Bu ne?" }));
    expect(screen.getByTestId("asistan-bune-bindirme")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("asistan-bune-bindirme")).toBeNull();
    expect(panel()).toBeInTheDocument();
    // Odak paneldeyken kipte Esc: olay panelin onKeyDown'una ulaşmamalı (gerçek tarayıcıda
    // dinleyiciler arasında mikro görev çalışır, panelTus güncel buNe=false ile paneli kapatırdı).
    await u.click(within(p).getByRole("button", { name: "? Bu ne?" }));
    const disari = vi.fn();
    window.addEventListener("keydown", disari);
    fireEvent.keyDown(within(p).getByLabelText("Sorunuz"), { key: "Escape" });
    await act(async () => {
      await Promise.resolve();
    });
    window.removeEventListener("keydown", disari);
    expect(disari).not.toHaveBeenCalled();
    expect(screen.queryByTestId("asistan-bune-bindirme")).toBeNull();
    expect(panel()).toBeInTheDocument();
    fireEvent.keyDown(within(p).getByLabelText("Sorunuz"), { key: "Escape" });
    expect(screen.queryByTestId("asistan-paneli")).toBeNull();
    delete (document as { elementsFromPoint?: unknown }).elementsFromPoint;
  });

  it("data-asistan-gizli kuralı: ClaudeCode token'ı yalnız pre/code/gizli alanlarda; kart tanımı token taşımaz", async () => {
    await oturumAc("analist");
    const u = userEvent.setup();
    const token = "tpk" + "_" + "mock_" + "0123456789abcdef0123456789abcdef01234567";
    vi.spyOn(api, "tokenOlustur").mockResolvedValue({ id: "tok-1", token, kapsam: "submit", son_kullanma: new Date(Date.now() + 3600_000).toISOString(), mcp_url: "http://127.0.0.1:8000/mcp" });
    const { container } = render(
      <MemoryRouter>
        <OturumProvider>
          <BildirimProvider>
            <ClaudeCode />
          </BildirimProvider>
        </OturumProvider>
      </MemoryRouter>,
    );
    await u.click(await screen.findByRole("button", { name: "8 saatlik token oluştur" }));
    await screen.findAllByText((_, el) => !!el && el.tagName === "CODE" && (el.textContent ?? "").includes(token));
    const yuruyucu = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    let bulunan = 0;
    for (let n = yuruyucu.nextNode(); n; n = yuruyucu.nextNode()) {
      if ((n.textContent ?? "").includes(token)) {
        bulunan += 1;
        expect(n.parentElement!.closest("[data-asistan-gizli], pre, code"), n.textContent ?? "").not.toBeNull();
      }
    }
    for (const el of container.querySelectorAll("*")) {
      for (const a of Array.from(el.attributes)) {
        if (a.value.includes(token)) expect(el.closest("[data-asistan-gizli], pre, code"), a.name).not.toBeNull();
      }
    }
    expect(bulunan).toBeGreaterThan(0);
    for (const kart of container.querySelectorAll(".kart")) {
      expect(JSON.stringify(elemanTanimi(kart))).not.toContain(token);
    }
  });
});

describe("cevap biçimi", () => {
  it("kaynak doğrulaması kaynak alanından, yoksa cevap.dogrulama[ref]'ten okunur; baglam 2 KB'a sığdırılır", async () => {
    const { kaynakDogrulandi, baglamiSigdir } = await import("../../api/asistan");
    const c = { dogrulama: { "a.ts:1": { dogrulandi: false }, k2: { dogrulandi: true } } };
    expect(kaynakDogrulandi(c, { tur: "urun_kodu", ref: "a.ts:1", alinti: "x" })).toBe(false);
    expect(kaynakDogrulandi(c, { tur: "jira", ref: "k2", alinti: "x" })).toBe(true);
    expect(kaynakDogrulandi(c, { tur: "jira", ref: "k2", alinti: "x", dogrulandi: false })).toBe(false);
    expect(kaynakDogrulandi(c, { tur: "genel_bilgi", ref: "", alinti: "" })).toBeUndefined();
    const b = baglamiSigdir({ rota_kalibi: "/kod/:id", son_hata: { detail: "x".repeat(5000) }, secili_eleman: { ad: "y".repeat(5000) } });
    expect(new TextEncoder().encode(JSON.stringify(b)).length).toBeLessThanOrEqual(2048);
    expect(b.rota_kalibi).toBe("/kod/:id");
  });
});
