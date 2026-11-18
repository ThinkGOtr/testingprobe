// 014 test dilleri portal davranışı: `/code/languages` `hat` + `durum` (dil kapısı, "Yakında"), müşteri CI
// hattı (rozet, "kırarak doğrulanmadı" notu, check kartı), kurulum PR'ı ve uyum katmanı.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ayar } from "../api/mock/handlers";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { kodDilleriUyarla, kurulumUyarla, musteriCiUyarla, scriptUyarla } from "../api/uyumDemoB";
import { mergeOnayNotu, mergeUyarilari, mergeEngelleri } from "../lib/kapi";
import { oturumAc, sekmeAc } from "../test/yardimci";

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

describe("uyum katmanı (014)", () => {
  it("`durum: yakinda` seçilemez (core `kullanilabilir` true gönderse bile); tanınmayan durum güvenli tarafta yakında", () => {
    const d = kodDilleriUyarla(
      {
        platform: "android",
        algilanan: "java",
        kaynak: "algilandi",
        secenekler: [
          { dil: "java", hat: "tam", durum: "acik", kullanilabilir: true },
          { dil: "python", hat: "tam", durum: "yakinda", kullanilabilir: true },
          { dil: "kotlin", hat: "musteri_ci", durum: "beta", kullanilabilir: true, kurulum: { durum: "open", number: 7, eksikler: ["iş akışı"] } },
        ],
      },
      "android",
    )!;
    expect(d.secenekler.map((s) => [s.dil, s.hat, s.durum, s.kullanilabilir, s.neden])).toEqual([
      ["java", "tam", "acik", true, null],
      ["python", "tam", "yakinda", false, "Değerlendirme sürüyor"],
      ["kotlin", "musteri_ci", "yakinda", false, "Değerlendirme sürüyor"],
    ]);
    expect(d.secenekler[2].kurulum).toEqual({ durum: "acik", number: 7, url: null, baslik: null, eksikler: ["iş akışı"], elle_adimlar: [] });
    // `hat` yoksa çiftin hattı: kotlin müşteri CI, web python (014 öncesi core) doğrulanmamış.
    expect(kodDilleriUyarla({ secenekler: [{ dil: "kotlin" }] }, "android")!.secenekler[0].hat).toBe("musteri_ci");
    expect(kodDilleriUyarla({ secenekler: [{ dil: "python" }] }, "android")!.secenekler[0].hat).toBe("tam");
    expect(kodDilleriUyarla({ secenekler: [{ dil: "python" }] }, "web")!.secenekler[0].hat).toBe("dogrulanmamis");
  });

  it("müşteri CI ve kurulum PR'ı: toleranslı eşleme; adı/durumu tanınmayan null (uydurulmaz)", () => {
    expect(musteriCiUyarla({ check: "mobil-ios-swift", durum: "success", sonuc: { toplam: 2, gecen: 2 }, artefakt: "alindi", url: "https://github.com/a/b/actions/runs/1" })).toEqual({
      check_adi: "mobil-ios-swift",
      saglayici: "github_actions",
      durum: "gecti",
      head_sha: null,
      run_url: "https://github.com/a/b/actions/runs/1",
      tamamlanma: null,
      sonuc: { toplam: 2, gecen: 2, kalan: 0, atlanan: 0 },
      artefakt: "alindi",
      neden: null,
    });
    expect(musteriCiUyarla({ durum: "gecti" })).toBeNull();
    expect(musteriCiUyarla({ check_adi: "x", durum: "tuhaf" })!.durum).toBe("bilinmiyor");
    expect(musteriCiUyarla({ check_adi: "x", durum: "derleme" })!.durum).toBe("derleme_hatasi");
    expect(kurulumUyarla({ durum: "merged", number: 40 })).toMatchObject({ durum: "birlesti", number: 40 });
    expect(kurulumUyarla({ durum: "belki" })).toBeNull();
    expect(kurulumUyarla(null)).toBeNull();
  });

  it("script hattı: core `hat`; yoksa doğrulanmamış kayıt ya da çiftin hattı", () => {
    expect(scriptUyarla({ id: "s", platform: "android", dil: "kotlin" }).hat).toBe("musteri_ci");
    expect(scriptUyarla({ id: "s", platform: "web", dil: "python" }).hat).toBe("tam");
    expect(scriptUyarla({ id: "s", platform: "web", dil: "python", durum: "unverified" }).hat).toBe("dogrulanmamis");
    expect(scriptUyarla({ id: "s", platform: "ios", dil: "swift", hat: "musteri_ci" }).hat).toBe("musteri_ci");
    expect(scriptUyarla({ id: "s", platform: "web", dil: "swift" }).hat).toBeNull();
  });

  it("merge kapısı: müşteri CI hattında kırarak doğrulama uyarısı/kabul notu yok; bekleyen check adı müşteri iş akışı", () => {
    const temel = {
      durum: "pr_open" as const,
      zayif_test: false,
      yerel_sinif: null,
      break_verify: { durum: "not_started" as const, asamalar: [] },
      pr: { durum: "open", ci: "pending", checks: [] } as never,
    };
    expect(mergeUyarilari(temel)).toHaveLength(1);
    const mc = { ...temel, hat: "musteri_ci" as const, musteri_ci: musteriCiUyarla({ check_adi: "mobil-ios-swift", durum: "kosuyor" }) };
    expect(mergeUyarilari(mc)).toEqual([]);
    expect(mergeOnayNotu(mc)).toBeNull();
    expect(mergeEngelleri(mc)).toEqual(["Müşteri CI sonucu bekleniyor (zorunlu check: mobil-ios-swift)."]);
  });
});

describe("örnek arka uç: dil kapısı", () => {
  it("varsayılan (rules/diller.yaml): ts/java açık, diğerleri yakında; müşteri CI hattı çiftten", async () => {
    await oturumAc("muhendis");
    const web = (await api.kodDilleri("web"))!;
    expect(web.secenekler.map((s) => [s.dil, s.hat, s.durum, s.kullanilabilir])).toEqual([
      ["ts", "tam", "acik", true],
      ["java", "tam", "acik", true],
      ["csharp", "tam", "yakinda", false],
      ["python", "tam", "yakinda", false],
    ]);
    const and = (await api.kodDilleri("android"))!;
    expect(and.secenekler.map((s) => [s.dil, s.hat, s.durum])).toEqual([
      ["java", "tam", "acik"],
      ["python", "tam", "yakinda"],
      ["kotlin", "musteri_ci", "yakinda"],
    ]);
    // POST /code/generate kapıyı uygular (422).
    await expect(api.kodUret(["case-1-4"], "web", "python")).rejects.toMatchObject({ status: 422, message: expect.stringContaining("Değerlendirme sürüyor") });
    await expect(api.kodUret(["case-1-4"], "android", "kotlin")).rejects.toMatchObject({ status: 422 });
  });

  it("`diller-acik`: kotlin/swift açık, kurulum PR'ı örnekleri", async () => {
    await oturumAc("muhendis");
    ayar.senaryolar.add("diller-acik");
    const ios = (await api.kodDilleri("ios"))!;
    const swift = ios.secenekler.find((s) => s.dil === "swift")!;
    expect(swift).toMatchObject({ hat: "musteri_ci", durum: "acik", kullanilabilir: true, cati: "XCUITest" });
    expect(swift.kurulum).toMatchObject({ durum: "acik", number: 41 });
  });
});

describe("Kod üretimi: dil seçici (014)", () => {
  it("yakında seçenek pasif: 'Yakında' rozeti ve nedeni okunur, seçim değişmez", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    uygulama("/kod");
    const grup = await screen.findByRole("group", { name: "Dil" });
    // IA-13: iki ve daha çok kullanılamayan dil seçicide kart olmaz; tek satırda toplanır, neden açılırda.
    expect(within(grup).queryByRole("radio", { name: "Python" })).toBeNull();
    const kapali = screen.getByTestId("dil-kapalilar");
    expect(kapali).toHaveTextContent(/Bu projede kullanılamıyor: .*Python/);
    await u.click(within(kapali).getByText(/Bu projede kullanılamıyor/));
    expect(kapali).toHaveTextContent(/Python \(yakında\): .*Değerlendirme sürüyor/);
    expect(within(grup).getByRole("radio", { name: "TypeScript" })).toBeChecked();
    expect(screen.queryByTestId("dogrulanmamis-dil-uyarisi")).toBeNull();
  });

  it("müşteri CI dili: rozet, 'kırarak doğrulanmadı' notu düğmeye bağlı, kurulum PR'ı gerekli", async () => {
    await oturumAc("muhendis");
    ayar.senaryolar.add("diller-acik");
    const u = userEvent.setup();
    uygulama("/kod");
    await u.click(await screen.findByRole("radio", { name: /^Android/ }));
    const kotlin = await screen.findByRole("radio", { name: "Kotlin" });
    expect(kotlin).toHaveAccessibleDescription(/Müşteri CI.*Espresso \(AndroidX Test\) · koşu müşteri CI'da, kırarak doğrulama yok/);
    expect(screen.queryByTestId("musteri-ci-notu")).toBeNull();
    await u.click(kotlin);
    const not = screen.getByTestId("musteri-ci-notu");
    expect(not).toHaveTextContent("Müşteri CI hattı: Kotlin · Kırarak doğrulanmadı");
    const kurulum = screen.getByTestId("kurulum-pr");
    expect(kurulum).toHaveAttribute("data-durum", "gerekli");
    expect(within(kurulum).getByRole("list", { name: "Kurulumun eklediği" })).toHaveTextContent("mobil-android-kotlin iş akışı");
    const dugme = screen.getByRole("button", { name: /^Seçilenler için kod üret \(\d+\) · Android · Kotlin$/ });
    expect(dugme).toHaveAccessibleDescription(expect.stringContaining("kırarak doğrulama yapılmaz"));
  });
});

describe("Script detayı: müşteri CI (014)", () => {
  it("Kotlin: rozetler, statik koruma + GitHub Actions check kartı, kırarak doğrulama yerine not, merge kapısı uyarısız", async () => {
    await oturumAc("muhendis");
    ayar.senaryolar.add("diller-acik");
    uygulama("/kod/scr-kt?sekme=kontrol");
    const kart = await screen.findByTestId("musteri-ci-karti");
    expect(screen.getByTestId("kirarak-dogrulanmadi-rozeti")).toHaveTextContent("Kırarak doğrulanmadı");
    expect(screen.getAllByTestId("dil-rozeti")[0]).toHaveTextContent("Dil: Kotlin (Espresso (AndroidX Test))");
    const liste = within(kart).getByRole("list", { name: "Müşteri CI adımları" });
    expect(liste).toHaveTextContent("Kotlin koruması (tree-sitter) (TP)");
    const check = within(kart).getByTestId("musteri-ci-check");
    expect(check).toHaveAttribute("data-durum", "gecti");
    expect(check).toHaveTextContent("GitHub Actions · mobil-android-kotlin");
    expect(check).toHaveTextContent("1/1 geçti");
    expect(within(check).getByRole("link", { name: /koşu/ })).toHaveAttribute("href", expect.stringContaining("/actions/runs/1180042"));
    expect(screen.getByTestId("kurulum-pr")).toHaveTextContent("Kotlin kurulumu tamam (kurulum PR'ı #40 birleşti).");
    expect(screen.queryByRole("heading", { name: "Yerel kontrol" })).toBeNull();
    expect(screen.getByRole("tab", { name: "Müşteri CI" })).toBeInTheDocument();
    await sekmeAc("Kırarak doğrula");
    expect(screen.getByTestId("kirarak-dogrulanmadi")).toHaveTextContent("kırarak doğrulama yapılmaz");
    expect(screen.queryByRole("button", { name: "Kırarak doğrula" })).toBeNull();
    await sekmeAc("Pull request");
    expect(screen.queryByTestId("merge-uyarilari")).toBeNull();
    expect(screen.getByRole("button", { name: "Merge et" })).toBeEnabled();
    await sekmeAc("Kod");
    expect([...document.querySelectorAll(".kod .tk-ek")].map((e) => e.textContent)).toEqual(expect.arrayContaining(["@RunWith", "@Test"]));
  });

  it("Swift: kurulum PR'ı açık (elle adım: UI test hedefi), check koşuyor, merge kapısı müşteri CI'ı bekler", async () => {
    await oturumAc("muhendis");
    ayar.senaryolar.add("diller-acik");
    uygulama("/kod/scr-sw?sekme=kontrol");
    const kurulum = await screen.findByTestId("kurulum-pr");
    expect(kurulum).toHaveAttribute("data-durum", "acik");
    expect(within(kurulum).getByRole("list", { name: "Elle yapılacak adımlar" })).toHaveTextContent("UI Testing Bundle");
    expect(within(kurulum).getByRole("link", { name: /#41/ })).toBeInTheDocument();
    expect(screen.getByTestId("musteri-ci-check")).toHaveAttribute("data-durum", "kosuyor");
    await sekmeAc("Pull request");
    await waitFor(() => expect(screen.getByTestId("merge-kapisi")).toHaveTextContent("Müşteri CI sonucu bekleniyor (zorunlu check: mobil-ios-swift)."));
    expect(screen.getByRole("button", { name: "Merge et" })).toHaveAttribute("aria-disabled", "true");
    await sekmeAc("Kod");
    expect(document.querySelector(".kod .tk-ek")).toHaveTextContent("@MainActor");
  });
});
