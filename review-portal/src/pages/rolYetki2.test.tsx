// 012 inceleme bulguları (portal turu 2): case sözleşmesi (core `son_onay`/`testci`/`kisitli`),
// Analist görüntüleme ölçümü, izinsiz rotaya bağlantı yok, maskeli koşu, yeni okuma izinleri,
// demo kipi kapalıyken menü/açılış, PO geri çevirme (T04), mock okuma izinleri.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ApiError, DEMO_KAPALI } from "../api/http";
import { mockOrtam, mockVerisi } from "../api/mock/handlers";
import { caseUyarla } from "../api/uyum";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { durumNotu, goruntulenenleriSifirla } from "../components/CaseKarti";
import { IZINLER, rotaDeseni } from "../lib/yetki";
import { oturumAc } from "../test/yardimci";
import { ARTEFAKT_MASKELI, MANUEL_PROD_ENGELI } from "./Kosular";

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

async function girisYap(k: string) {
  await api.logout().catch(() => undefined);
  return api.login(k, "Demo123!");
}

const CASELER = "/gereksinimler/req-tpd-1/caseler";
const kart = (sira: number) => screen.getAllByRole("article").find((a) => within(a).queryByText(new RegExp(`^#${sira}$`)))!;

/** core `serialize_cases` çıktısı (cases/service.py): son karar Analist'in, Testçi kararı ayrı alanda. */
const CEKIRDEK_CASE = {
  id: "c-1",
  requirement_id: "r-1",
  jira_key: "TPD-1",
  sira_no: 1,
  uretim_no: 1,
  kanal: "portal",
  surum: 2,
  icerik: { title: "T", type: "positive", risk: "high", acceptance_criteria_refs: ["AC1"], preconditions: [], steps: [], expected_result: "x", tags: [] },
  durum: "draft",
  karar: "send_back",
  ret_nedeni: null,
  karar_veren: "analist",
  karar_zamani: "2026-11-12T10:05:00Z",
  testci_karari: "edit",
  testci: "testci",
  son_onay: { karar: "send_back", veren: "analist", zaman: "2026-11-12T10:05:00Z", gerekce: "Adım 2 eksik" },
  duzeltme_olcusu: 0.1,
  kucuk_duzeltme: true,
  icerik_hash: "sha256:a",
  onaylanan_hash: null,
  ai_generated: true,
  ai_sure_ms: 100,
  review_sure_ms: 2000,
  maliyet_usd: 0,
  jira_test_key: null,
  jira_test_url: null,
  mode: "replay",
  uyarilar: [],
  onceki_icerik: false,
  ai_icerik: null,
  fark: [],
  duzeltme_nedeni: null,
  olusturma: "2026-11-12T10:00:00Z",
};

describe("case sözleşmesi: core `son_onay` / `testci` / `kisitli`", () => {
  it("geri gönderilmiş case: gerekçe son_onay'dan, onaylayan yok, Testçi kararı ayrı", () => {
    const c = caseUyarla(CEKIRDEK_CASE);
    expect(c).toMatchObject({
      karar: "send_back",
      karar_veren: "analist",
      testci_karari: "edit",
      testci: "testci",
      gerekce: "Adım 2 eksik",
      onaylayan: null,
      onay_zamani: null,
      son_onay: { karar: "send_back", veren: "analist", gerekce: "Adım 2 eksik" },
    });
  });

  it("onaylı case: onaylayan/onay_zamani son_onay'dan; eski 'approve' Testçi kararı kabul edilir", () => {
    const c = caseUyarla({
      ...CEKIRDEK_CASE,
      durum: "approved",
      karar: "approve",
      testci_karari: "approve",
      testci: "analist",
      son_onay: { karar: "approve", veren: "analist2", zaman: "2026-11-12T11:00:00Z", gerekce: null },
    });
    expect(c).toMatchObject({ testci_karari: "approve", onaylayan: "analist2", onay_zamani: "2026-11-12T11:00:00Z", gerekce: null });
  });

  it("kısıtlı (developer) yanıt: geçmiş alanları yok, `kisitli: true`", () => {
    const { karar: _k, karar_veren: _v, karar_zamani: _z, testci: _t, testci_karari: _tk, son_onay: _s, ...ham } = CEKIRDEK_CASE;
    const c = caseUyarla({ ...ham, durum: "approved", kisitli: true });
    expect(c.kisitli).toBe(true);
    expect(c.karar).toBeNull();
    expect(c.son_onay).toBeUndefined();
    expect(c.testci).toBeUndefined();
  });

  it("mock core biçimini üretir: düz gerekce/onaylayan yok; developer'a geçmiş alanları gitmez", async () => {
    await girisYap("testci");
    const ham = (await import("../api/mock/handlers")).mockIstek;
    const liste = (await ham("GET", "/cases", new URLSearchParams({ requirement_id: "req-tpd-1" }), null)) as Record<string, unknown>[];
    for (const c of liste) {
      expect(c).toHaveProperty("son_onay");
      expect(c).toHaveProperty("testci");
      expect(c).toHaveProperty("testci_karari");
      expect(c).not.toHaveProperty("onaylayan");
      expect(c).not.toHaveProperty("onay_zamani");
      expect(c).not.toHaveProperty("gerekce");
    }
    await girisYap("gelistirici");
    const kisitli = (await ham("GET", "/cases", new URLSearchParams({ requirement_id: "req-tpd-1" }), null)) as Record<string, unknown>[];
    expect(kisitli.length).toBeGreaterThan(0);
    for (const c of kisitli) {
      expect(c.kisitli).toBe(true);
      for (const a of ["karar", "karar_veren", "karar_zamani", "testci", "testci_karari", "son_onay", "fark", "ai_icerik", "review_sure_ms"]) {
        expect(c, a).not.toHaveProperty(a);
      }
    }
  });

  it("geri gönderme son_onay'a yazılır (karar_veren Analist); taslağa alma son_onay'ı düşürür", async () => {
    const c = mockVerisi().caseler.find((x) => x.id === "case-1-7")!;
    await girisYap("testci");
    let tc = await api.caseKarari(c.id, { icerik_hash: c.icerik_hash, karar: "accept" });
    expect(tc).toMatchObject({ durum: "ready", testci: "testci", testci_karari: "accept", son_onay: null });
    await girisYap("analist");
    tc = await api.caseKarari(c.id, { icerik_hash: tc.icerik_hash, karar: "send_back", gerekce: "Eksik adım" });
    expect(tc).toMatchObject({ durum: "draft", karar: "send_back", karar_veren: "analist", testci: "testci", gerekce: "Eksik adım" });
    expect(tc.son_onay).toMatchObject({ karar: "send_back", veren: "analist", gerekce: "Eksik adım" });
    await girisYap("testci");
    tc = await api.caseKarari(c.id, { icerik_hash: tc.icerik_hash, karar: "accept" });
    await girisYap("analist");
    tc = await api.caseKarari(c.id, { icerik_hash: tc.icerik_hash, karar: "approve" });
    expect(tc.son_onay?.karar).toBe("approve");
    await girisYap("testci");
    tc = await api.caseYenidenAc(tc);
    expect(tc).toMatchObject({ durum: "draft", son_onay: null, onaylayan: null });
  });

  it("görevler ayrılığı: Testçi kararını veren hesap onaylayamaz → 403 `onay_yetkisi_yok`", async () => {
    const c = mockVerisi().caseler.find((x) => x.id === "case-1-7")!;
    c.durum = "ready";
    c.karar = "accept";
    c.testci_karari = "accept";
    c.testci = "analist";
    c.karar_veren = "analist";
    await girisYap("analist");
    await expect(api.caseKarari(c.id, { icerik_hash: c.icerik_hash, karar: "approve" })).rejects.toMatchObject({
      status: 403,
      kod: "onay_yetkisi_yok",
    });
  });

  it("kart: Analist geri gönderimi ve Testçi kararı ayrı etiketli satırlar (karar_veren etiketsiz yok)", async () => {
    const c = mockVerisi().caseler.find((x) => x.id === "case-1-7")!;
    c.durum = "draft";
    c.karar = "send_back";
    c.karar_veren = "analist";
    c.karar_zamani = "2026-11-12T10:05:00Z";
    c.testci_karari = "accept";
    c.testci = "testci";
    c.son_onay = { karar: "send_back", veren: "analist", zaman: "2026-11-12T10:05:00Z", gerekce: "Adım 3 eksik" };
    await oturumAc("testci");
    uygulama(CASELER);
    await screen.findAllByRole("article");
    const k = kart(6);
    expect(within(k).getByTestId("case-geri-gonderildi")).toHaveTextContent("Adım 3 eksik");
    expect(within(k).getByTestId("case-testci-karari")).toHaveTextContent("Testçi kararı: kabul · Fatih Arslan");
    expect(within(k).getByTestId("case-testci-karari")).not.toHaveTextContent("2026");
    expect(within(k).getByTestId("case-son-onay")).toHaveTextContent(/Analist son onayı: geri gönderildi · Cengizhan Gunaydin · /);
  });
});

describe("case kartı: Analist görüntüleme ölçümü ve metinler", () => {
  it("Analist onaya hazır case'i görüntüleyince `viewed` bildirilir (case kimliği + durum başına bir kez)", async () => {
    goruntulenenleriSifirla();
    const c = mockVerisi().caseler.find((x) => x.id === "case-1-7")!;
    c.durum = "ready";
    c.karar = "accept";
    c.testci_karari = "accept";
    c.testci = "testci";
    const casus = vi.spyOn(api, "caseGoruntulendi");
    await oturumAc("analist");
    uygulama(CASELER);
    await screen.findAllByRole("article");
    await waitFor(() => expect(casus).toHaveBeenCalledWith("case-1-7"));
    expect(casus.mock.calls.filter(([id]) => id === "case-1-7")).toHaveLength(1);
    // Taslaktaki case'ler Analist için ölçülmez.
    const taslaklar = mockVerisi().caseler.filter((x) => x.requirement_id === "req-tpd-1" && x.durum === "draft").map((x) => x.id);
    for (const id of taslaklar) expect(casus).not.toHaveBeenCalledWith(id);
  });

  it("durum notu: 'taslağa alın' yalnız Testçiye; Analist onaya hazırda 'Geri gönderin'", () => {
    expect(durumNotu("ready", true, false)).toContain("taslağa alın");
    expect(durumNotu("ready", false, true)).toContain("Değişiklik gerekiyorsa gerekçeyle Geri gönderin");
    expect(durumNotu("ready", false, true)).not.toContain("taslağa");
    expect(durumNotu("approved", false, true)).not.toContain("taslağa");
  });

  it("geri gönderme alanı: en çok 2000 karakter; boşken aria-invalid ve hata bağlı", async () => {
    const c = mockVerisi().caseler.find((x) => x.id === "case-1-7")!;
    c.durum = "ready";
    c.karar = "accept";
    c.testci_karari = "accept";
    c.testci = "testci";
    await oturumAc("analist");
    const u = userEvent.setup();
    uygulama(CASELER);
    await screen.findAllByRole("article");
    const k = kart(6);
    await waitFor(() => expect(within(k).getByRole("button", { name: "Geri gönder" })).toBeEnabled());
    await u.click(within(k).getByRole("button", { name: "Geri gönder" }));
    const alan = within(k).getByLabelText("Geri gönderme gerekçesi");
    expect(alan).toHaveAttribute("maxLength", "2000");
    await u.click(within(within(k).getByTestId("geri-gonder-formu")).getByRole("button", { name: "Geri gönder" }));
    expect(alan).toHaveAttribute("aria-invalid", "true");
    expect(alan).toHaveAccessibleDescription(/Geri gönderme gerekçesi zorunludur/);
  });
});

describe("izinsiz rotaya bağlantı verilmez", () => {
  it("rota deseni: adres ROTA_IZINLERI kalıbına eşlenir", () => {
    expect(rotaDeseni("/hatalar/fail-1")).toBe("/hatalar/:id");
    expect(rotaDeseni("/kod/scr-1?x=1")).toBe("/kod/:id");
    expect(rotaDeseni("/gereksinimler/r/yayin")).toBe("/gereksinimler/:id/yayin");
    expect(rotaDeseni("/bilinmeyen")).toBeNull();
  });

  it("Görüntüleyici koşu detayında triage ve üretilen test bağlantısı yerine düz metin görür", async () => {
    await oturumAc("izleyici");
    uygulama("/kosular/run-107");
    const metin = await screen.findByText("Triage sonucunu aç");
    expect(metin.closest("a")).toBeNull();
  });

  it("Testçi aynı koşuda triage bağlantısını görür", async () => {
    await oturumAc("testci");
    uygulama("/kosular/run-107");
    expect(await screen.findByRole("link", { name: "Triage sonucunu aç" })).toBeInTheDocument();
  });
});

describe("maskeli koşu (run.artifacts yok)", () => {
  it("mock: Görüntüleyici için artefakt alanları null, ekler boş, `maskeli: true`; Kontrol Kulesi son koşuları da", async () => {
    const k = mockVerisi().kosular.find((x) => x.id === "run-107")!;
    k.rapor_url = "/api/artifacts/runs/run-107/index.html";
    await girisYap("izleyici");
    const d = await api.kosu("run-107");
    expect(d.maskeli).toBe(true);
    expect(d.rapor_url).toBeNull();
    expect(d.sonuclar.every((s) => (s.ekler ?? []).length === 0)).toBe(true);
    expect((await api.kosular()).every((x) => x.maskeli)).toBe(true);
    expect((await api.kontrolKulesi()).son_kosular.every((x) => x.maskeli)).toBe(true);
    await girisYap("testci");
    const t = await api.kosu("run-107");
    expect(t.maskeli).toBeUndefined();
    expect(t.rapor_url).toBe("/api/artifacts/runs/run-107/index.html");
  });

  it("ekran: 'yok' yerine 'Ham artefaktlar bu rolde görünmez'", async () => {
    await oturumAc("denetci");
    uygulama("/kosular/run-107");
    expect(await screen.findByTestId("artefakt-maskeli")).toHaveTextContent(ARTEFAKT_MASKELI);
    expect(screen.queryByText("Playwright HTML raporu")).toBeNull();
  });
});

describe("yeni okuma izinleri ve demo kipi", () => {
  it("katalog: publish.preview, claude_code.read, demo.read, requirement.po_reject_free_text", () => {
    expect([...IZINLER["publish.preview"]].sort()).toEqual(["admin", "analyst", "engineer", "po", "tester"]);
    expect([...IZINLER["claude_code.read"]].sort()).toEqual(["admin", "analyst", "engineer", "tester"]);
    expect([...IZINLER["demo.read"]].sort()).toEqual(["admin", "analyst", "engineer", "po", "tester"]);
    expect([...IZINLER["requirement.po_reject_free_text"]]).toEqual(["po"]);
  });

  it("Analist Demo yol haritasını görür (demo.read); Demo kontrolleri menüde yok", async () => {
    await oturumAc("analist");
    uygulama("/yol-haritasi");
    const menu = await screen.findByRole("navigation", { name: "Ana menü" });
    await waitFor(() => expect(within(menu).getByText("Demo yol haritası")).toBeInTheDocument());
    expect(within(menu).queryByText("Demo kontrolleri")).toBeNull();
    expect(screen.queryByText("Bu ekran için yetkiniz yok.")).toBeNull();
  });

  it("demo kipi kapalıyken iki demo menü öğesi gizlenir; Sistem Yöneticisi Kontrol Kulesi'nde açılır", async () => {
    mockOrtam.demoModu = false;
    await oturumAc("sunucu");
    uygulama("/");
    expect(await screen.findByRole("heading", { name: "Kontrol Kulesi", level: 1 })).toBeInTheDocument();
    const menu = screen.getByRole("navigation", { name: "Ana menü" });
    await waitFor(() => expect(within(menu).queryByText("Demo kontrolleri")).toBeNull());
    expect(within(menu).queryByText("Demo yol haritası")).toBeNull();
  });

  it("demo kipinde Sistem Yöneticisi Demo yol haritasında açılır", async () => {
    await oturumAc("sunucu");
    uygulama("/");
    expect(await screen.findByRole("heading", { name: "Demo yol haritası", level: 1 })).toBeInTheDocument();
  });

  it("demo kapalı: yazan uç 403 `demo_kapali` ve core iletisi", async () => {
    mockOrtam.demoModu = false;
    await girisYap("muhendis");
    await expect(api.demoSifirla()).rejects.toMatchObject({ status: 403, kod: "demo_kapali", detail: DEMO_KAPALI });
  });

  it("Developer prod ortamında 'Manuel koşu başlat' pasif ve nedeni yazılı", async () => {
    mockOrtam.ortam = "prod";
    await oturumAc("gelistirici");
    uygulama("/kosular");
    const d = await screen.findByRole("button", { name: "Manuel koşu başlat" });
    await waitFor(() => expect(d).toBeDisabled());
    expect(d).toHaveAccessibleDescription(new RegExp(MANUEL_PROD_ENGELI.replace(/[().]/g, "\\$&")));
  });

  it("Developer prod dışında manuel koşu başlatabilir", async () => {
    await oturumAc("gelistirici");
    uygulama("/kosular");
    const d = await screen.findByRole("button", { name: "Manuel koşu başlat" });
    expect(d).toBeEnabled();
  });
});

describe("PO geri çevirme (T04, serbest metin)", () => {
  const bekleyen = () => {
    const g = mockVerisi().gereksinimler.find((x) => x.id === "req-ft-1")!;
    g.durum = "pending_po";
    g.po = { durum: "pending", onaylayan: null, zaman: null, kanal: "portal" };
    return g;
  };

  it("mock: PO gerekçeyle geri çevirir → new; gerekçesiz 422; Jira story 410; Analist 403", async () => {
    const g = bekleyen();
    await girisYap("analist");
    await expect(api.poReddet(g, "x")).rejects.toMatchObject({ status: 403 });
    await girisYap("po");
    await expect(api.poReddet(g, "  ")).rejects.toMatchObject({ status: 422 });
    const jira = mockVerisi().gereksinimler.find((x) => x.kaynak === "jira")!;
    await expect(api.poReddet(jira, "x")).rejects.toMatchObject({ status: 410, kod: "po_onayi_jira" });
    const y = await api.poReddet(g, "AC2 belirsiz");
    expect(y.durum).toBe("new");
    expect(mockVerisi().denetim.some((d) => d.eylem === "po.reject" && d.ozet.includes("AC2 belirsiz"))).toBe(true);
  });

  it("ekran: 'Geri çevir' gerekçe ister (≤2000), gönderince gereksinim yeni durumuna döner", async () => {
    bekleyen();
    await oturumAc("po");
    const u = userEvent.setup();
    const casus = vi.spyOn(api, "poReddet");
    uygulama("/gereksinimler/req-ft-1");
    await u.click(await screen.findByRole("button", { name: "Geri çevir" }));
    const form = screen.getByTestId("po-ret-formu");
    const alan = within(form).getByLabelText("Geri çevirme gerekçesi");
    expect(alan).toHaveAttribute("maxLength", "2000");
    await u.click(within(form).getByRole("button", { name: "Geri çevir" }));
    expect(await within(form).findByText("Geri çevirme gerekçesi zorunludur.")).toBeInTheDocument();
    expect(casus).not.toHaveBeenCalled();
    await u.type(alan, "AC2 belirsiz");
    await u.click(within(form).getByRole("button", { name: "Geri çevir" }));
    await waitFor(() => expect(casus).toHaveBeenCalledWith(expect.objectContaining({ id: "req-ft-1" }), "AC2 belirsiz"));
    await waitFor(() => expect(mockVerisi().gereksinimler.find((x) => x.id === "req-ft-1")!.durum).toBe("new"));
  });

  it("Analist 'Geri çevir'i pasif görür (gerekçe: PO)", async () => {
    bekleyen();
    await oturumAc("analist");
    uygulama("/gereksinimler/req-ft-1");
    const d = await screen.findByRole("button", { name: "Geri çevir" });
    expect(d).toBeDisabled();
    expect(d).toHaveAccessibleDescription("Bu işlem için gereken rol: PO");
  });
});

describe("mock okuma uçları core gibi izin ister", () => {
  it.each([
    ["izleyici", "/failures"],
    ["izleyici", "/bug-drafts"],
    ["izleyici", "/requirements"],
    ["izleyici", "/scripts"],
    ["gelistirici", "/scripts"],
    ["po", "/scripts/scr-1"],
  ])("%s GET %s → 403", async (hesap, yol) => {
    await girisYap(hesap);
    const { mockIstek } = await import("../api/mock/handlers");
    await expect(mockIstek("GET", yol, new URLSearchParams(), null)).rejects.toMatchObject({ status: 403 });
  });

  it("`/cases/:id/viewed` yalnız case.decide | case.approve", async () => {
    await girisYap("po");
    await expect(api.caseGoruntulendi("case-1-7")).rejects.toBeInstanceOf(ApiError);
    await girisYap("analist");
    await expect(api.caseGoruntulendi("case-1-7")).resolves.toBeTruthy();
  });
});

describe("Demo yol haritası: rolün okuyamadığı kaynak istenmez (012)", () => {
  it("PO kod üretimini göremez: 403 uyarısı değil, sessiz not", async () => {
    await oturumAc("po");
    const spy = vi.spyOn(api, "scriptler");
    uygulama("/yol-haritasi");
    expect(await screen.findByTestId("yh-rol-kapali")).toHaveTextContent("Kod üretimi");
    expect(screen.queryByText(/yetkiniz yok/i)).toBeNull();
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("Automation Engineer tüm kaynakları okur, not çıkmaz", async () => {
    await oturumAc("muhendis");
    uygulama("/yol-haritasi");
    await screen.findByText("Demo yol haritası", { selector: "h1" });
    await waitFor(() => expect(screen.queryByTestId("yh-rol-kapali")).toBeNull());
  });
});
