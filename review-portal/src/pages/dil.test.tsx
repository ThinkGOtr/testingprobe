// 011 üretim dili portal davranışı: uyum katmanı (script/kontrol/koşu/diller), istemci gövdesi, örnek
// arka uç (GET /code/languages, kodUret dil boyutu), Kod üretimi dil seçicisi ve doğrulanmamış script detayı.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Rotalar } from "../App";
import { api } from "../api/client";
import { ayar, mockVerisi } from "../api/mock/handlers";
import { OturumProvider } from "../auth";
import { BildirimProvider } from "../components/Bildirim";
import { DilRozeti } from "../components/Dil";
import { kodDilleriUyarla, kosuUyarla, scriptUyarla, yerelKontrolUyarla } from "../api/uyumDemoB";
import type { KodDilleri } from "../api/types";
import { SCRIPT_DURUMU } from "../lib/etiketler";
import { oturumAc } from "../test/yardimci";
import { indirmeAdi, kontrolSatirlari } from "./ScriptDetay";
import { DOGRULANMAMIS_UYARISI } from "./Kod";

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

const WEB_DILLERI: KodDilleri = {
  platform: "web",
  algilanan: "ts",
  kaynak: "algilandi",
  sayilar: { ts: 9, java: 0 },
  secenekler: [
    { dil: "ts", etiket: "TypeScript", cati: "Playwright Test", hat: "tam", kullanilabilir: true, neden: null },
    { dil: "java", etiket: "Java", cati: "Playwright for Java + TestNG", hat: "tam", kullanilabilir: false, neden: "Depoda Java web test projesi (e2e-java/pom.xml) yok" },
    { dil: "python", etiket: "Python", cati: "pytest-playwright", hat: "dogrulanmamis", kullanilabilir: true, neden: null },
  ],
};

describe("uyum katmanı (core şekli, §2.3)", () => {
  it("script: dil, dil_kaynagi, dogrulanmamis; alan yoksa platformun varsayılanı; tanınmayan null", () => {
    expect(scriptUyarla({ id: "s", platform: "web", dil: "java", dil_kaynagi: "secildi" })).toMatchObject({ dil: "java", dil_kaynagi: "secildi", dogrulanmamis: false });
    expect(scriptUyarla({ id: "s" })).toMatchObject({ platform: "web", dil: "ts", dil_kaynagi: null });
    expect(scriptUyarla({ id: "s", platform: "ios" }).dil).toBe("java");
    expect(scriptUyarla({ id: "s", dil: "kotlin" }).dil).toBeNull();
    // `unverified` portal durum kümesinde; dogrulanmamis core alanı ya da durumdan.
    expect(scriptUyarla({ id: "s", durum: "unverified", dil: "python" })).toMatchObject({ durum: "unverified", dogrulanmamis: true });
    expect(scriptUyarla({ id: "s", dogrulanmamis: true, dil: "csharp" }).dogrulanmamis).toBe(true);
    expect(SCRIPT_DURUMU.unverified).toEqual({ etiket: "Doğrulanmamış", ton: "uyari" });
  });

  it("yerel kontrol: `adimlar: [{ad, durum}]` listesi; yoksa eski tsc/eslint/ast_guard alanları", () => {
    const yeni = yerelKontrolUyarla({ adimlar: [{ ad: "deps", durum: true }, { ad: "guard", durum: "ok" }, { ad: "compile", durum: false }], run_status: "failed" })!;
    expect(yeni.adimlar).toEqual([
      { ad: "deps", durum: true },
      { ad: "guard", durum: true },
      { ad: "compile", durum: false },
    ]);
    expect(yeni.sinif).toBe("derleme");
    expect(kontrolSatirlari(yeni, "java").map((a) => a.etiket)).toEqual(["pom kilidi", "Java AST koruması", "derleme"]);
    // 011 öncesi core: sözlük `adimlar` → eski alanlar, liste yok.
    const eski = yerelKontrolUyarla({ adimlar: { tsc: true, eslint: true, ast_guard: false } })!;
    expect(eski.adimlar).toBeNull();
    expect(eski).toMatchObject({ tsc: true, eslint: true, ast_guard: false, sinif: "derleme" });
    expect(kontrolSatirlari(eski).map((a) => [a.etiket, a.durum])).toEqual([
      ["tsc --strict", true],
      ["eslint --no-inline-config", true],
      ["AST koruması", false],
    ]);
    // Liste de yoksa ve Java ise adım adları dilden (sonuçsuz).
    expect(kontrolSatirlari(yerelKontrolUyarla({})!, "java").map((a) => a.ad)).toEqual(["deps", "guard", "compile"]);
  });

  it("koşu dili toleranslı: dil → ortam.dil → ortam.lang; yoksa null (platformdan türetilmez)", () => {
    expect(kosuUyarla({ id: "r", dil: "java" }).dil).toBe("java");
    expect(kosuUyarla({ id: "r", ortam: { dil: "ts", platform: "web" } }).dil).toBe("ts");
    expect(kosuUyarla({ id: "r", ortam: { lang: "java" } }).dil).toBe("java");
    expect(kosuUyarla({ id: "r", ortam: { platform: "web" } }).dil).toBeNull();
  });

  it("GET /code/languages: geçersiz çift ve tanınmayan dil atılır; algılanan seçeneklerde yoksa varsayılana düşülür", () => {
    const d = kodDilleriUyarla(
      {
        platform: "android",
        algilanan: "ts",
        kaynak: "algilandi",
        sayilar: { java: 3 },
        secenekler: [{ dil: "ts" }, { dil: "java", etiket: "Java", cati: "Appium + TestNG", hat: "tam", kullanilabilir: true }, { dil: "kotlin" }],
      },
      "android",
    )!;
    expect(d.secenekler.map((s) => s.dil)).toEqual(["java"]);
    expect(d).toMatchObject({ algilanan: "java", kaynak: "varsayilan", sayilar: { java: 3 } });
    // Eksik alanlar dilden tamamlanır; csharp/python hat bilgisi yoksa doğrulanmamış.
    const w = kodDilleriUyarla({ algilanan: "ts", kaynak: "algilandi", secenekler: [{ dil: "ts" }, { dil: "csharp" }] }, "web")!;
    expect(w.secenekler).toEqual([
      { dil: "ts", etiket: "TypeScript", cati: "Playwright Test", hat: "tam", kullanilabilir: true, neden: null },
      { dil: "csharp", etiket: "C#", cati: "Playwright .NET + NUnit", hat: "dogrulanmamis", kullanilabilir: true, neden: null },
    ]);
    expect(kodDilleriUyarla({ secenekler: [] }, "web")).toBeNull();
    expect(kodDilleriUyarla("yok", "web")).toBeNull();
  });

  it("indirme adı dosya yolunun son parçası", () => {
    expect(indirmeAdi("demo-app/e2e-python/tests/uretilen/test_a.py", "python")).toBe("test_a.py");
    expect(indirmeAdi("", "csharp")).toBe("uretilen-test.cs");
  });

  it("dil rozeti: görünür ad, ekran okuyucuya 'Dil:' ve çatı; dil yoksa çizilmez", () => {
    const { container, rerender } = render(<DilRozeti dil="java" platform="web" />);
    const r = screen.getByTestId("dil-rozeti");
    expect(r).toHaveTextContent("Dil: Java (Playwright for Java + TestNG)");
    expect(r).toHaveAttribute("title", "Playwright for Java + TestNG");
    rerender(<DilRozeti dil={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("örnek arka uç: dil boyutu", () => {
  it("GET /code/languages: web'de ts algılanmış, java tam hat, csharp/python doğrulanmamış; uygulamada yalnız java", async () => {
    await oturumAc("muhendis");
    const web = (await api.kodDilleri("web"))!;
    expect(web).toMatchObject({ algilanan: "ts", kaynak: "algilandi" });
    expect(web.secenekler.map((s) => [s.dil, s.hat])).toEqual([
      ["ts", "tam"],
      ["java", "tam"],
      ["csharp", "dogrulanmamis"],
      ["python", "dogrulanmamis"],
    ]);
    const ios = (await api.kodDilleri("ios"))!;
    expect(ios.secenekler.map((s) => [s.dil, s.cati])).toEqual([["java", "Appium + TestNG"]]);
  });

  it("kodUret: dil yoksa algılanan (algilandi); web+java e2e-java yolu, Java kodu, local-ci; geçersiz çift 422", async () => {
    await oturumAc("muhendis");
    await api.kodUret(["case-1-4"], "web", "java");
    const bul = () => mockVerisi().scriptler.find((s) => s.case_ids.includes("case-1-4") && s.platform === "web")!;
    await waitFor(() => expect(bul().durum).toBe("pr_open"));
    const s = bul();
    expect(s).toMatchObject({ dil: "java", dil_kaynagi: "secildi" });
    expect(s.dosya_yolu).toMatch(/^demo-app\/e2e-java\/src\/test\/java\/com\/antreklabs\/bayi\/uretilen\/TPD1C5_[0-9a-f]{8}Test\.java$/);
    expect(s.kod).toContain("public class TPD1C5_");
    expect(s.kod).toContain('cart.expectMinOrderWarning("Minimum sipariş tutarı 750,00 TL");');
    expect(s.pr!.checks![0]).toMatchObject({ ad: "local-ci", aciklama: expect.stringContaining("pom kilidi") });
    expect(s.yerel_kontrol!.adimlar!.map((a) => a.ad)).toEqual(["deps", "guard", "compile"]);
    await expect(api.kodUret(["case-1-4"], "android", "python")).rejects.toMatchObject({ status: 422 });
    await expect(api.kodUret(["case-1-4"], "web", "kotlin" as never)).rejects.toMatchObject({ status: 422 });
  });

  it("kodUret: csharp → doğrulanmamış (PR yok, dal yok, kaynak saklı); dil yoksa ts algilandi", async () => {
    await oturumAc("muhendis");
    await api.kodUret(["case-1-4"], "web", "csharp");
    const bul = () => mockVerisi().scriptler.find((s) => s.case_ids.includes("case-1-4") && s.platform === "web" && s.durum !== "closed")!;
    await waitFor(() => expect(bul().durum).toBe("unverified"));
    expect(bul()).toMatchObject({ dil: "csharp", dogrulanmamis: true, pr: null, branch: "", yerel_kontrol: null });
    expect(bul().dosya_yolu).toMatch(/\.cs$/);
    expect(bul().kod).toContain("[TestFixture]");
    expect(bul().kod).toContain('await cart.ExpectMinOrderWarning("Minimum sipariş tutarı 750,00 TL");');
    // Başka dilde (algılanan) yeniden üretim: doğrulanmamış kayıt kapanır, yeni script ts.
    const eskiId = bul().id;
    await api.kodUret(["case-1-4"], "web");
    await waitFor(() => expect(bul().durum).toBe("pr_open"));
    expect(mockVerisi().scriptler.find((s) => s.id === eskiId)!.durum).toBe("closed");
    expect(bul()).toMatchObject({ dil: "ts", dil_kaynagi: "algilandi" });
  });
});

describe("Kod üretimi: dil seçici", () => {
  it("algılanan dil seçili ve 'repodan algılandı'; doğrulanmamış dil seçilince açık uyarı; algılanana dön", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    uygulama("/kod");
    const grup = await screen.findByRole("group", { name: "Dil" });
    expect(within(grup).getByRole("radio", { name: "TypeScript" })).toBeChecked();
    expect(within(grup).getByRole("radio", { name: "Java" })).toHaveAccessibleDescription("Playwright for Java + TestNG");
    expect(within(grup).getByRole("radio", { name: "Python" })).toHaveAccessibleDescription("pytest-playwright · doğrulanmamış");
    expect(screen.getByTestId("dil-notu")).toHaveTextContent("TypeScript repodan algılandı (9 elle yazılmış test dosyası).");
    // Dil ayrıyken platform açıklaması dil adı taşımaz.
    expect(screen.getByRole("radio", { name: "Web" })).toHaveAccessibleDescription("Tarayıcı · Playwright");
    expect(screen.queryByTestId("dogrulanmamis-dil-uyarisi")).toBeNull();

    await u.click(within(grup).getByRole("radio", { name: "Python" }));
    expect(screen.getByTestId("dil-notu")).toHaveTextContent("Python elle seçildi.");
    const uyari = screen.getByTestId("dogrulanmamis-dil-uyarisi");
    expect(uyari).toHaveTextContent(DOGRULANMAMIS_UYARISI);
    expect(uyari).toHaveTextContent("Doğrulanmamış dil: Python");
    await u.click(await screen.findByRole("checkbox", { name: /minimum tutarın altında uyarı/ }));
    const dugme = screen.getByRole("button", { name: "Seçilenler için kod üret (1) · Python" });
    // Uyarı düğmeye tanım olarak bağlı: ekran okuyucu düğmede de duyar.
    expect(dugme).toHaveAccessibleDescription(expect.stringContaining(DOGRULANMAMIS_UYARISI));

    await u.click(screen.getByRole("button", { name: "Algılanana dön (TypeScript)" }));
    expect(within(grup).getByRole("radio", { name: "TypeScript" })).toBeChecked();
    expect(screen.getByTestId("dil-notu")).toHaveTextContent("repodan algılandı");
    expect(screen.queryByTestId("dogrulanmamis-dil-uyarisi")).toBeNull();
    expect(screen.getByRole("button", { name: "Seçilenler için kod üret (1)" })).toBeEnabled();
  });

  it("elle seçilen dil POST gövdesinde; algılananla üretimde dil gönderilmez", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    const casus = vi.spyOn(api, "kodUret");
    uygulama("/kod");
    const grup = await screen.findByRole("group", { name: "Dil" });
    await u.click(within(grup).getByRole("radio", { name: "Java" }));
    await u.click(await screen.findByRole("checkbox", { name: /minimum tutarın altında uyarı/ }));
    await u.click(screen.getByRole("button", { name: "Seçilenler için kod üret (1) · Java" }));
    await waitFor(() => expect(casus).toHaveBeenCalledWith(["case-1-4"], "web", "java"));
    // Liste satırında dil rozeti (çatı adıyla).
    const satir = await screen.findByRole("row", { name: /Kampanyasız siparişte minimum tutarın altında/ });
    expect(within(satir).getByTestId("dil-rozeti")).toHaveTextContent("Dil: Java");
  });

  it("platform değişince seçenekler yeniden yüklenir, elle seçim düşer; uygulamada tek dil salt bilgi", async () => {
    await oturumAc("muhendis");
    const u = userEvent.setup();
    const casus = vi.spyOn(api, "kodDilleri");
    uygulama("/kod");
    const grup = await screen.findByRole("group", { name: "Dil" });
    await u.click(within(grup).getByRole("radio", { name: "C#" }));
    await u.click(screen.getByRole("radio", { name: /^Android/ }));
    await waitFor(() => expect(casus).toHaveBeenLastCalledWith("android"));
    const bilgi = await screen.findByTestId("dil-bilgi");
    expect(bilgi).toHaveTextContent("Java");
    expect(bilgi).toHaveTextContent("Appium + TestNG · bu platformda tek dil");
    expect(screen.queryByRole("radio", { name: "C#" })).toBeNull();
    expect(screen.queryByTestId("dogrulanmamis-dil-uyarisi")).toBeNull();
    await u.click(screen.getByRole("radio", { name: /^Web/ }));
    expect(await screen.findByRole("radio", { name: "TypeScript" })).toBeChecked();
  });

  it("kullanılamayan seçenek pasif: neden görünür ve tanım olarak okunur; seçim değişmez", async () => {
    await oturumAc("muhendis");
    vi.spyOn(api, "kodDilleri").mockResolvedValue(WEB_DILLERI);
    const u = userEvent.setup();
    uygulama("/kod");
    const java = await screen.findByRole("radio", { name: "Java" });
    expect(java).toHaveAttribute("aria-disabled", "true");
    expect(java).toHaveAccessibleDescription(/Kullanılamıyor: Depoda Java web test projesi \(e2e-java\/pom\.xml\) yok/);
    expect(screen.getByTestId("secenek-neden")).toBeVisible();
    await u.click(java);
    expect(screen.getByRole("radio", { name: "TypeScript" })).toBeChecked();
    expect(screen.getByTestId("dil-notu")).toHaveTextContent("TypeScript repodan algılandı (9 elle yazılmış test dosyası).");
  });

  it("algılama sonuçsuz: 'varsayılan' notu", async () => {
    await oturumAc("muhendis");
    vi.spyOn(api, "kodDilleri").mockResolvedValue({ ...WEB_DILLERI, kaynak: "varsayilan", sayilar: {} });
    uygulama("/kod");
    expect(await screen.findByTestId("dil-notu")).toHaveTextContent("Depoda elle yazılmış test bulunamadı; varsayılan dil TypeScript.");
  });

  it("uç yoksa (011 öncesi core) dil seçici ve dil rozeti yok; üretim bugünkü gibi", async () => {
    await oturumAc("muhendis");
    vi.spyOn(api, "kodDilleri").mockResolvedValue(null);
    const casus = vi.spyOn(api, "kodUret");
    const u = userEvent.setup();
    uygulama("/kod");
    await u.click(await screen.findByRole("checkbox", { name: /minimum tutarın altında uyarı/ }));
    expect(screen.queryByRole("group", { name: "Dil" })).toBeNull();
    expect(screen.queryAllByTestId("dil-rozeti")).toHaveLength(0);
    expect(screen.getByRole("radio", { name: "Web" })).toHaveAccessibleDescription("Tarayıcı · Playwright + TypeScript");
    await u.click(screen.getByRole("button", { name: "Seçilenler için kod üret (1)" }));
    await waitFor(() => expect(casus).toHaveBeenCalledWith(["case-1-4"], "web"));
  });
});

describe("Script detayı: dil", () => {
  it("doğrulanmamış script: kalıcı uyarı bandı, PR/kırma/merge yerine açıklama, kod indirilir", async () => {
    await oturumAc("muhendis");
    const olustur = vi.fn(() => "blob:ornek");
    const birak = vi.fn();
    Object.assign(URL, { createObjectURL: olustur, revokeObjectURL: birak });
    const tikla = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toMatch(/^test_tpd1_c8_[0-9a-f]{8}\.py$/);
      expect(this.href).toBe("blob:ornek");
    });
    const u = userEvent.setup();
    uygulama("/kod/scr-py");
    const bant = await screen.findByTestId("dogrulanmamis-bandi");
    expect(bant).toHaveTextContent("Doğrulanmamış kod: Python (pytest-playwright)");
    expect(bant).toHaveTextContent("Bu kod derlenmedi ve koşulmadı; PR açılmadı ve merge edilemez.");
    expect(screen.getByText("Doğrulanmamış", { selector: ".cip" })).toBeInTheDocument();
    expect(screen.getByText("Python için PR, kırarak doğrulama ve merge yok.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Merge et" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Kırarak doğrula" })).toBeNull();
    expect(screen.queryByTestId("merge-kapisi")).toBeNull();
    expect(screen.getByText("Python için yerel kontrol yok.")).toBeInTheDocument();
    // Doğrulama satırları "yerel kontrolde koşulur" demez: bu dilde koşu yok.
    const esleme = screen.getByRole("region", { name: "Eşlenen adımlar tablosu" });
    expect(esleme).not.toHaveTextContent("yerel kontrolde koşulur");
    expect(within(esleme).getAllByText("koşulmadı (doğrulanmamış dil)").length).toBeGreaterThan(0);
    // Ajan ve araç platforma bağlı: web → Playwright MCP (dil ne olursa olsun).
    expect(screen.getByRole("heading", { name: "Ajan adımları (Playwright MCP)" })).toBeInTheDocument();
    // Kod Python sözdizimiyle (dekoratör) renklendirilir.
    expect(screen.getByRole("heading", { name: "Üretilen test dosyası (doğrulanmamış)" })).toBeInTheDocument();
    expect(document.querySelector(".kod .tk-ek")).toHaveTextContent("@pytest.mark.uretilen");
    await u.click(within(bant).getByRole("button", { name: "Kodu indir" }));
    expect(tikla).toHaveBeenCalledTimes(1);
    expect(olustur).toHaveBeenCalledWith(expect.any(Blob));
  });

  it("başka dilde yeniden üret: tam hat dili önerilir, kodUret dille çağrılır, liste ekranına dönülür", async () => {
    await oturumAc("muhendis");
    const casus = vi.spyOn(api, "kodUret");
    const u = userEvent.setup();
    uygulama("/kod/scr-py");
    const bant = await screen.findByTestId("dogrulanmamis-bandi");
    const secim = within(bant).getByRole("combobox", { name: "Başka dil" });
    await waitFor(() => expect(within(secim).getAllByRole("option").map((o) => o.textContent)).toEqual(["TypeScript", "Java", "C# (doğrulanmamış)"]));
    await u.selectOptions(secim, "java");
    await u.click(within(bant).getByRole("button", { name: "Başka dilde yeniden üret" }));
    await waitFor(() => expect(casus).toHaveBeenCalledWith(["case-1-8"], "web", "java"));
    expect(await screen.findByRole("heading", { name: "Kod üretimi", level: 1 })).toBeInTheDocument();
    await waitFor(() => expect(mockVerisi().scriptler.find((s) => s.id === "scr-py")!.durum).toBe("closed"));
  });

  it("web + Java script: dil rozeti, Java kontrol adımları, Java sözdizimi; karar kartları var", async () => {
    await oturumAc("muhendis");
    uygulama("/kod/scr-java");
    expect(await screen.findByRole("heading", { name: "Ajan adımları (Playwright MCP)" })).toBeInTheDocument();
    expect(screen.getAllByTestId("dil-rozeti")[0]).toHaveTextContent("Dil: Java (Playwright for Java + TestNG)");
    const liste = screen.getByRole("list", { name: "Yerel kontrol adımları" });
    const satirlar = within(liste).getAllByRole("listitem").map((li) => li.textContent?.replace(/\s+/g, " ").trim());
    expect(satirlar.slice(0, 3)).toEqual(["✓ pom kilidi: geçti", "✓ Java AST koruması: geçti", "✓ derleme: geçti"]);
    expect(satirlar[3]).toContain("Playwright (Java) --repeat-each=3");
    expect(screen.getByRole("list", { name: "PR check'leri" })).toHaveTextContent("Yerel CI · Web (local-ci)");
    expect(screen.getByTestId("yerel-sinif")).toHaveTextContent("pom kilidi · Java AST koruması · derleme · Playwright (Java) (repeat-each) geçti.");
    expect(screen.getByTestId("yerel-sinif")).not.toHaveTextContent("tsc");
    expect(screen.getByRole("button", { name: "Merge et" })).toBeInTheDocument();
    expect(screen.queryByTestId("dogrulanmamis-bandi")).toBeNull();
    expect([...document.querySelectorAll(".kod .tk-ek")].map((e) => e.textContent)).toEqual(expect.arrayContaining(["@Bayi", "@Test"]));
  });
});
