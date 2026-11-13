// Canlı UI testi düzeltmeleri (fix/canli-portal-b): Jira çekim onayı, gereksinim sıralaması,
// rol adı tutarlılığı, yetkisiz çağrıların koşullanması, 422 → bulunamadı, takılmış koşu uyarısı vb.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Rotalar } from "../App";
import { yapilandir } from "../api/http";
import { mockIstek } from "../api/mock/handlers";
import type { Gereksinim } from "../api/types";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { izinRolleriMetni } from "../lib/yetki";
import { oturumAc } from "../test/yardimci";
import { gereksinimSirala, jiraCekimMetni, jiraProjeleri } from "./Gereksinimler";

export function uygulama(yol: string) {
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

type Cagri = { method: string; path: string; govde: unknown };
export function izle(ozel?: (c: Cagri) => unknown) {
  const cagrilar: Cagri[] = [];
  yapilandir({
    mock: async (method, path, q, govde) => {
      const c = { method, path, govde };
      cagrilar.push(c);
      const o = ozel?.(c);
      if (o !== undefined) return o;
      return mockIstek(method, path, q, govde);
    },
  });
  return cagrilar;
}

describe("Jira'dan çek: onay penceresi", () => {
  it("düğme hemen POST göndermez; proje adıyla onay sorar, İptal çekmez, Çek çeker", async () => {
    const cagrilar = izle();
    await oturumAc("analist");
    uygulama("/gereksinimler");
    const dugme = await screen.findByRole("button", { name: "Jira'dan çek" });
    await userEvent.click(dugme);
    const onay = await screen.findByTestId("jira-cek-onay");
    expect(cagrilar.some((c) => c.path === "/requirements/sync")).toBe(false);
    expect(within(onay).getByText(/Jira'ya bir şey yazılmaz/)).toBeInTheDocument();
    expect(within(onay).getByText(/\(TPD\)/)).toBeInTheDocument();
    await userEvent.click(within(onay).getByRole("button", { name: "İptal" }));
    expect(screen.queryByTestId("jira-cek-onay")).toBeNull();
    expect(cagrilar.some((c) => c.path === "/requirements/sync")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Jira'dan çek" }));
    await userEvent.click(within(await screen.findByTestId("jira-cek-onay")).getByRole("button", { name: "Çek" }));
    await waitFor(() => expect(cagrilar.some((c) => c.method === "POST" && c.path === "/requirements/sync")).toBe(true));
  });

  it("proje anahtarı listeden türetilir; yoksa genel metin", () => {
    expect(jiraProjeleri([{ jira_key: "TPD-1" }, { jira_key: null }, { jira_key: "TPD-12" }, { jira_key: "ABC-3" }])).toEqual(["ABC", "TPD"]);
    expect(jiraCekimMetni([])).toMatch(/^Yapılandırılmış Jira projesindeki/);
    expect(jiraCekimMetni(["TPD"])).toMatch(/\(TPD\)/);
  });
});

describe("gereksinim tablosu sıralaması", () => {
  const g = (jira_key: string | null, baslik: string, bulgu = 0): Gereksinim =>
    ({
      id: baslik,
      jira_key,
      baslik,
      durum: "new",
      ac_missing: false,
      po: { durum: "not_requested" },
      sayaclar: { bulgu_acik: bulgu, case_toplam: 0, case_onayli: 0 },
      cekim_zamani: "2026-11-01T00:00:00Z",
    }) as unknown as Gereksinim;

  it("anahtar sayı farkında, başlık tr-TR, yön değişir", () => {
    const l = [g("TPD-10", "Ç"), g("TPD-2", "A"), g(null, "B")];
    expect(gereksinimSirala(l, { alan: "anahtar", yon: "artan" }).map((x) => x.jira_key)).toEqual([null, "TPD-2", "TPD-10"]);
    expect(gereksinimSirala(l, { alan: "baslik", yon: "azalan" }).map((x) => x.baslik)).toEqual(["Ç", "B", "A"]);
  });

  it("başlıklar düğmedir ve aria-sort taşır", async () => {
    await oturumAc("analist");
    uygulama("/gereksinimler");
    const anahtar = await screen.findByRole("button", { name: /^Anahtar/ });
    const th = anahtar.closest("th")!;
    expect(th).toHaveAttribute("aria-sort", "none");
    await userEvent.click(anahtar);
    expect(th).toHaveAttribute("aria-sort", "ascending");
    await userEvent.click(anahtar);
    expect(th).toHaveAttribute("aria-sort", "descending");
  });
});

describe("rol adı tutarlılığı", () => {
  it("izin rolleri metni rol etiketlerinden gelir (Automation Engineer)", () => {
    expect(izinRolleriMetni("automation.manage")).toBe("Analist ve Automation Engineer");
    expect(izinRolleriMetni("testdata.manage")).toBe("Analist, Testçi ve Automation Engineer");
    expect(izinRolleriMetni("automation.jira_status")).toBe("Automation Engineer");
  });
});

describe("bulunamadı görünümü: Tekrar dene yok", () => {
  it("HataKutusu 404 kaynakta yeniden deneme düğmesi çizmez, diğer hatada çizer", async () => {
    const { HataKutusu } = await import("../components/ui");
    const { ApiError } = await import("../api/http");
    const { rerender } = render(<HataKutusu hata="Kayıt bulunamadı." kaynak={new ApiError(404, "Kayıt bulunamadı.")} yenile={() => {}} />);
    expect(screen.queryByRole("button", { name: "Tekrar dene" })).toBeNull();
    rerender(<HataKutusu hata="Çekirdek servise ulaşılamıyor." kaynak={new ApiError(502, "x")} yenile={() => {}} />);
    expect(screen.getByRole("button", { name: "Tekrar dene" })).toBeInTheDocument();
  });

  it("olmayan gereksinim kimliği: Türkçe mesaj, Tekrar dene yok", async () => {
    izle((c) => {
      if (c.path === "/requirements/olmayan-id") {
        return (async () => {
          const { ApiError } = await import("../api/http");
          throw new ApiError(404, "Kayıt bulunamadı.", { kod: "gecersiz_kimlik" });
        })();
      }
      return undefined;
    });
    await oturumAc("analist");
    uygulama("/gereksinimler/olmayan-id");
    expect(await screen.findByText("Kayıt bulunamadı.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tekrar dene" })).toBeNull();
  });
});

describe("bug taslağı: kısıtlı rol ve salt okunur form", () => {
  it("Developer, yayınlanmamış taslağa bağlantı görmez; açıklama görür", async () => {
    const { mockVerisi } = await import("../api/mock/handlers");
    const v = mockVerisi();
    const bulgu = v.bulgular.find((b) => b.bug_draft_id && b.karar && v.bugTaslaklari.find((t) => t.id === b.bug_draft_id)?.durum !== "published")!;
    expect(bulgu).toBeTruthy();
    await oturumAc("gelistirici");
    uygulama(`/gereksinimler/${bulgu.requirement_id}`);
    const notlar = await screen.findAllByTestId("bug-taslagi-kisitli");
    expect(notlar[0]).toHaveTextContent("Bu rol yayınlanmamış bug taslaklarını göremez.");
    expect(screen.queryByRole("link", { name: "Bug taslağına git" })).toBeNull();
  });

  it("Sistem Yöneticisi taslak formunu salt okunur görür (alanlar pasif)", async () => {
    const { mockVerisi } = await import("../api/mock/handlers");
    const taslak = mockVerisi().bugTaslaklari.find((t) => t.durum === "draft")!;
    await oturumAc("sunucu");
    uygulama(`/bug-taslaklari/${taslak.id}`);
    expect(await screen.findByTestId("bug-salt-okunur")).toBeInTheDocument();
    expect(screen.getByLabelText("Özet")).toBeDisabled();
    expect(screen.getByLabelText("Beklenen")).toBeDisabled();
    expect(screen.getByLabelText("Ret gerekçesi")).toHaveAttribute("readonly");
  });

  it("Testçi taslak formunu düzenleyebilir", async () => {
    const { mockVerisi } = await import("../api/mock/handlers");
    const taslak = mockVerisi().bugTaslaklari.find((t) => t.durum === "draft")!;
    await oturumAc("testci");
    uygulama(`/bug-taslaklari/${taslak.id}`);
    expect(await screen.findByLabelText("Özet")).toBeEnabled();
    expect(screen.queryByTestId("bug-salt-okunur")).toBeNull();
  });
});

describe("Otomasyon: yetkisiz rolde tüm alanlar aynı biçimde pasif", () => {
  it("PO'da onay kutuları, sorgu aralığı ve durum alanı kendi disabled özniteliğini taşır", async () => {
    await oturumAc("po");
    uygulama("/otomasyon");
    const aralik = await screen.findByLabelText("Sorgu aralığı (saniye)");
    expect(aralik).toHaveAttribute("disabled");
    expect(screen.getByLabelText("Tetikleyen Jira durumu")).toHaveAttribute("disabled");
    expect(screen.getByLabelText("Tetik açık")).toHaveAttribute("disabled");
    expect(screen.getByLabelText("PO onayından sonra case'leri otomatik üret")).toHaveAttribute("disabled");
    expect(screen.getByLabelText("Onaylanan case için kodu otomatik üret")).toHaveAttribute("disabled");
  });
});

describe("yetkisi olmayan uç çağrılmaz (403 / sahte authz.denied yok)", () => {
  it("Testçi ve Analist /kod'da GET /code/languages çağırmaz; Automation Engineer çağırır", async () => {
    for (const k of ["testci", "analist"]) {
      const c = izle();
      await oturumAc(k);
      const { unmount } = uygulama("/kod");
      await screen.findByRole("heading", { name: "Kod üretimi", level: 1 });
      await waitFor(() => expect(c.some((x) => x.path === "/scripts")).toBe(true));
      expect(c.some((x) => x.path === "/code/languages"), k).toBe(false);
      unmount();
    }
    const c = izle();
    await oturumAc("muhendis");
    uygulama("/kod");
    await waitFor(() => expect(c.some((x) => x.path === "/code/languages")).toBe(true));
  });

  it("Developer Kontrol Kulesi'nde GET /scripts çağırmaz", async () => {
    const c = izle();
    await oturumAc("gelistirici");
    uygulama("/kontrol-kulesi");
    await screen.findByRole("heading", { name: "Kontrol Kulesi", level: 1 });
    await waitFor(() => expect(c.some((x) => x.path === "/control-tower")).toBe(true));
    expect(c.some((x) => x.path === "/scripts")).toBe(false);
  });

  it("Developer gereksinim detayında tasarım modeli ve script listesini istemez", async () => {
    const { mockVerisi } = await import("../api/mock/handlers");
    const g = mockVerisi().gereksinimler.find((x) => x.durum === "done") ?? mockVerisi().gereksinimler[0];
    const c = izle();
    await oturumAc("gelistirici");
    uygulama(`/gereksinimler/${g.id}`);
    await waitFor(() => expect(c.some((x) => x.path === `/requirements/${g.id}`)).toBe(true));
    await screen.findByRole("heading", { level: 1 });
    expect(c.some((x) => x.path.endsWith("/design-model"))).toBe(false);
    expect(c.some((x) => x.path === "/scripts")).toBe(false);
  });
});

describe("/demo/status önbelleği", () => {
  it("eş zamanlı ve 60 sn içindeki çağrılar tek isteğe iner; taze ve demo yazımı yeniden okur", async () => {
    const { api } = await import("../api/client");
    const c = izle();
    await oturumAc("sunucu");
    const sayi = () => c.filter((x) => x.path === "/demo/status").length;
    await Promise.all([api.demoDurumu(), api.demoDurumu(), api.demoDurumu()]);
    await api.demoDurumu();
    expect(sayi()).toBe(1);
    await api.demoDurumu(true);
    expect(sayi()).toBe(2);
    await api.demoSifirla().catch(() => undefined);
    await api.demoDurumu();
    expect(sayi()).toBe(3);
  });
});

describe("/kod: pasif Java kartı", () => {
  it("teknik neden görünür metinde yok, ipucunda; kullanıcı metni anlaşılır", async () => {
    const { dilNedeni, JAVA_WEB_KAPALI } = await import("../components/Dil");
    const ham = "GitHub kipinde Java web hattı etkin değil (TP_WEB_DILLERI java içermiyor; web-java iş akışı zorunlu check değil)";
    expect(dilNedeni(ham)).toEqual({ metin: JAVA_WEB_KAPALI, ayrinti: ham });
    expect(dilNedeni("Depo okunamadı")).toEqual({ metin: "Depo okunamadı", ayrinti: null });
    izle((c) =>
      c.path === "/code/languages"
        ? {
            platform: "web",
            algilanan: "ts",
            kaynak: "algilandi",
            secenekler: [
              { dil: "ts", etiket: "TypeScript", cati: "Playwright Test", kullanilabilir: true, neden: null, hat: "tam" },
              { dil: "java", etiket: "Java", cati: "Playwright for Java + TestNG", kullanilabilir: false, neden: ham, hat: "tam" },
            ],
          }
        : undefined,
    );
    await oturumAc("muhendis");
    uygulama("/kod");
    const neden = await screen.findByText(/Kullanılamıyor: Java web hattı bu kurulumda etkin değil/);
    expect(document.body.textContent).not.toContain("TP_WEB_DILLERI");
    expect(neden.closest("label")).toHaveAttribute("title", ham);
  });
});

describe("tutarlılık kartı: güncelliğini yitirmiş bulgular ayrı", () => {
  it("eskimiş engelleyici bulgu ayrı bölümde; not yalnız güncel bulgulara bakar", async () => {
    const { mockVerisi, mockIstek: ham } = await import("../api/mock/handlers");
    const g = mockVerisi().gereksinimler.find((x) => x.jira_key === "TPD-1")!;
    izle((c) => {
      if (c.path === `/requirements/${g.id}/findings`) {
        return (ham("GET", c.path, new URLSearchParams(), undefined) as Promise<Record<string, unknown>[]>).then((l) => {
          const [ilk, ...geri] = l;
          return [{ ...ilk, severity: "blocking", durum: "stale", kontrol_turu: 1 }, ...geri.map((b) => ({ ...b, severity: "warning", durum: "resolved" }))];
        });
      }
      return undefined;
    });
    await oturumAc("analist");
    uygulama(`/gereksinimler/${g.id}`);
    const eski = await screen.findByTestId("eskimis-bulgular");
    expect(within(eski).getByText(/Güncelliğini yitirmiş bulgular \(1\)/)).toBeInTheDocument();
    expect(within(eski).getByText("Engelleyiciydi")).toBeInTheDocument();
    const not = screen.queryByTestId("son-hal-notu");
    if (not) expect(not).toHaveTextContent("güncel engelleyici bulgu kalmadı");
  });
});
