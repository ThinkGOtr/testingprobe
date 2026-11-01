// Demo kontrolleri: onarım merge edilip main CI yeşile döndükten sonra sayfa "Main zaten kırık"
// demez (inceleme bulgusu: shots/sunucu-demo.png). Kırık/onarıldı kararı uygulama testId'sinin
// yanında test tarafından (core `e2e_testid` / `locator_durumu`) ya da main'deki son CI koşusundan verilir.
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ayar } from "../api/mock/handlers";
import type { DemoDurumu, Kosu } from "../api/types";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { oturumAc } from "../test/yardimci";
import { locatorDurumu, mainKosusu, onarimPrNo, shaEsit, zatenKirik } from "./DemoKontrolleri";

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
afterEach(() => {
  vi.restoreAllMocks();
});

const BASLA = Date.now() - 10 * 60_000;
const t = (dk: number) => new Date(BASLA + dk * 60_000).toISOString();

function kosu(p: Partial<Kosu> & Pick<Kosu, "id" | "tetik" | "commit" | "durum" | "baslangic">): Kosu {
  return {
    kaynak: "local",
    pr_no: null,
    sure_ms: 1000,
    toplam: 33,
    gecen: p.durum === "passed" ? 33 : 30,
    basarisiz: p.durum === "passed" ? 0 : 3,
    flaky: 0,
    atlanan: 0,
    allure_url: null,
    rapor_url: null,
    sauce_url: null,
    ci_url: null,
    break_campaign: false,
    script_id: null,
    saglik_hatasi: null,
    ...p,
  };
}

// Canlı durum (inceleme): kırılma add31d72 kırmızı, onarım PR #5 merge → main 94683fc, push f1e796b8 33/33.
const KIRMIZI = kosu({ id: "add31d72-0000-4000-8000-000000000001", tetik: "push", commit: "21b36dec0000", durum: "failed", baslangic: t(1) });
const ONARIM_PR = kosu({ id: "pr5-0000-4000-8000-000000000002", tetik: "pr", commit: "bbbbbbbb0000", durum: "passed", pr_no: 5, baslangic: t(4) });
const YESIL = kosu({ id: "f1e796b8-0000-4000-8000-000000000003", tetik: "push", commit: "94683fc00000", durum: "passed", baslangic: t(6) });
const KOSULAR = [YESIL, ONARIM_PR, KIRMIZI];

const ONARILDI: DemoDurumu = {
  forge: { main: "94683fc000001111222233334444555566667777", testid: "cart-add", baseline: "aaaa", main_baseline_mi: false },
  uygulama: { sha: "94683fc000001111222233334444555566667777", main_ile_eslesiyor: true },
  web_yenileme_istegi: { istek_id: "i1", eylem: "break", sha: "21b36dec0000", zaman: new Date(BASLA).toISOString(), isteyen: "sunucu" },
};
const KIRIK: DemoDurumu = {
  ...ONARILDI,
  forge: { ...ONARILDI.forge, main: "21b36dec0000aaaa" },
  uygulama: { sha: "21b36dec0000aaaa", main_ile_eslesiyor: true },
};

describe("locator durumu: kırık / onarıldı ayrımı", () => {
  it("sha önek eşleşmesi kısa ve tam sha'yı eşler, boş ya da çok kısa öneki eşlemez", () => {
    expect(shaEsit("94683fc00000", "94683fc000001111")).toBe(true);
    expect(shaEsit("94683f", "94683fc0")).toBe(false);
    expect(shaEsit(null, "94683fc0")).toBe(false);
    expect(shaEsit("21b36dec0000", "94683fc00000")).toBe(false);
  });

  it("main koşusu yeşil ve testId cart-add → onarıldı (kırık değil); PR numarası koşulardan bulunur", () => {
    expect(mainKosusu(KOSULAR, ONARILDI.forge.main)?.id).toBe(YESIL.id);
    expect(onarimPrNo(KOSULAR, YESIL)).toBe(5);
    const ld = locatorDurumu(ONARILDI, KOSULAR);
    expect(ld).toMatchObject({ hal: "onarildi", onarimPr: 5 });
    expect(zatenKirik(ONARILDI, KOSULAR)).toBe(false);
  });

  it("onarımdan sonra ortam hatasıyla düşen deploy koşusu (0/0) 'CI yeşil' metnini ve PR numarasını bozmaz", () => {
    const ortam = kosu({ id: "89b9f321-0000-4000-8000-000000000009", tetik: "deploy", commit: "94683fc00000", durum: "error", baslangic: t(9), toplam: 0, gecen: 0, basarisiz: 0 });
    const ld = locatorDurumu({ ...ONARILDI, locator_durumu: "onarildi" }, [ortam, ...KOSULAR]);
    expect(ld).toMatchObject({ hal: "onarildi", onarimPr: 5 });
    expect(ld.mainKosusu?.id).toBe(YESIL.id);
  });

  it("kırılma commit'inde kırmızı koşu ya da koşu yok → kırık; koşu sürüyorsa doğrulanıyor", () => {
    expect(locatorDurumu(KIRIK, KOSULAR).hal).toBe("kirik");
    expect(locatorDurumu(KIRIK, []).hal).toBe("kirik");
    const suruyor = kosu({ id: "r", tetik: "push", commit: "94683fc00000", durum: "running", baslangic: t(7) });
    expect(locatorDurumu(ONARILDI, [suruyor, ...KOSULAR]).hal).toBe("dogrulaniyor");
  });

  it("core e2e testId'si verirse o esas alınır: web ≠ e2e kırık, ikisi de cart-add onarıldı", () => {
    expect(locatorDurumu({ ...ONARILDI, forge: { ...ONARILDI.forge, e2e_testid: "add-to-cart" } }, KOSULAR).hal).toBe("kirik");
    expect(locatorDurumu({ ...ONARILDI, forge: { ...ONARILDI.forge, e2e_testid: "cart-add" } }, []).hal).toBe("onarildi");
    expect(locatorDurumu({ ...KIRIK, locator_durumu: "onarildi" }, []).hal).toBe("onarildi");
  });

  it("baseline ya da eski testId → kırılabilir", () => {
    expect(locatorDurumu({ ...ONARILDI, forge: { ...ONARILDI.forge, main_baseline_mi: true } }, KOSULAR).hal).toBe("baseline");
    expect(locatorDurumu({ ...ONARILDI, forge: { ...ONARILDI.forge, testid: "add-to-cart" } }, KOSULAR).hal).toBe("baseline");
    expect(locatorDurumu(null, null).hal).toBe("baseline");
  });
});

describe("/demo sayfası onarım sonrası", () => {
  it("'Main zaten kırık' demez; onarıldı + PR #5 + yeşil CI son adımlar olarak görünür, düğme sıfırlamayı ister", async () => {
    await oturumAc("sunucu");
    vi.spyOn(api, "demoDurumu").mockResolvedValue(ONARILDI);
    vi.spyOn(api, "kosular").mockResolvedValue(KOSULAR);
    vi.spyOn(api, "kosu").mockImplementation(async (id) => ({ ...(KOSULAR.find((k) => k.id === id) ?? KIRMIZI), testler: [] }) as never);
    uygulama("/demo");

    const dugme = await screen.findByRole("button", { name: "Önce demoyu sıfırlayın" });
    expect(dugme).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Locator zaten kırık" })).toBeNull();
    expect(screen.queryByTestId("zaten-kirik")).toBeNull();
    expect(screen.getByTestId("onarildi")).toHaveTextContent(/Onarım PR #5 merge edildi, CI yeşil \(33\/33\)/);

    const adimlar = await screen.findByRole("list", { name: "Locator kırılması ilerlemesi" });
    await waitFor(() => expect(within(adimlar).getByText(YESIL.id.slice(0, 8), { exact: false })).toBeInTheDocument());
    expect(adimlar).toHaveTextContent("Onarım PR'ı #5");
    expect(adimlar).toHaveTextContent("33/33 geçti");
  });

  it("onarım öncesi (kırılma commit'i kırmızı) hâlâ 'Locator zaten kırık' der", async () => {
    await oturumAc("sunucu");
    vi.spyOn(api, "demoDurumu").mockResolvedValue(KIRIK);
    vi.spyOn(api, "kosular").mockResolvedValue([KIRMIZI]);
    uygulama("/demo");
    expect(await screen.findByRole("button", { name: "Locator zaten kırık" })).toBeDisabled();
    expect(screen.getByTestId("zaten-kirik")).toHaveTextContent("cart-add");
    expect(screen.queryByTestId("onarildi")).toBeNull();
  });
});
