// 009 mobil-masaüstü (Ş7): örnek veri kipinde platform seçimi, platform rozeti, Kontrol Kulesi süzgeci,
// uygulama ajanı adımları ve hata anı sayfa kaynağı görüntüleyicisi. Ekran görüntüleri
// e2e/ekranlar/platform/ altına (gitignore) iki temada, masaüstü ve telefon genişliğinde yazılır.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

const DIZIN = "e2e/ekranlar/platform";
mkdirSync(DIZIN, { recursive: true });

async function fontlariBekle(page: Page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
}

async function girisYap(page: Page, kullanici: string) {
  await page.goto("/giris");
  await fontlariBekle(page);
  await page.getByLabel("Kullanıcı adı").fill(kullanici);
  await page.getByLabel("Parola").fill("Demo123!");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("navigation", { name: "Ana menü" })).toBeVisible();
  await fontlariBekle(page);
}

function konsolHatalariniTopla(page: Page): string[] {
  const hatalar: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") hatalar.push(m.text());
  });
  page.on("pageerror", (e) => hatalar.push(String(e)));
  return hatalar;
}

test("009: Kod üretiminde Android seçilir → uygulama ajanı adımları (Türkçe) → PR check'i 'Yerel CI · Android'", async ({ page }) => {
  const hatalar = konsolHatalariniTopla(page);
  await girisYap(page, "muhendis");
  await expect(page).toHaveURL(/\/kod$/);
  const grup = page.getByRole("group", { name: "Hedef platform" });
  await expect(grup.getByRole("radio", { name: "Web" })).toBeChecked();
  // Klavye: ok tuşu radyo grubunda gezer (yerel radyo davranışı).
  await grup.getByRole("radio", { name: "Web" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(grup.getByRole("radio", { name: "Android" })).toBeChecked();
  await page.getByRole("checkbox", { name: /Kampanyasız siparişte minimum tutarın altında/ }).check();
  await page.getByRole("button", { name: "Seçilenler için kod üret (1) · Android" }).click();
  const satir = page.getByRole("region", { name: "Üretilen testler tablosu" }).getByRole("row").filter({ hasText: /Kampanyasız siparişte minimum tutarın altında/ });
  await expect(satir.getByTestId("platform-rozeti")).toHaveText("Platform: Android");
  await satir.getByRole("link").first().click();
  await expect(page.getByRole("heading", { name: "Ajan adımları (Appium · app-mcp)" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Ajan adımları" })).toContainText("Uygulamayı başlat");
  await expect(page.getByRole("list", { name: "PR check'leri" }).first()).toContainText("Yerel CI · Android (local-ci-android)", { timeout: 20_000 });
  await expect(page.getByRole("region", { name: "Eşlenen adımlar tablosu" })).toContainText("SepetEkrani.dogrulaMinimumTutarUyarisi");
  // Dikey ekran görüntüsü çerçeveye sığar: yükseklik görünür alanı aşmaz, oran korunur.
  const img = page.locator("figure.ajan-ekran-dikey img");
  await expect(img).toBeVisible();
  const boy = await img.evaluate((e) => {
    const r = e.getBoundingClientRect();
    const i = e as HTMLImageElement;
    return { h: r.height, w: r.width, vh: window.innerHeight, oran: i.naturalWidth / i.naturalHeight };
  });
  expect(boy.h).toBeLessThanOrEqual(boy.vh * 0.7 + 1);
  expect(Math.abs(boy.w / boy.h - boy.oran)).toBeLessThan(0.02);
  await page.screenshot({ path: `${DIZIN}/60-kod-android-uretim.png`, fullPage: true });
  expect(hatalar).toEqual([]);
});

test("009: Kontrol Kulesi platform süzgeci adres çubuğunda; son koşular ve platform dağılımı daralır", async ({ page }) => {
  const hatalar = konsolHatalariniTopla(page);
  await girisYap(page, "sunucu");
  await page.goto("/kontrol-kulesi");
  const grup = page.getByRole("group", { name: "Platform" });
  await expect(grup.getByRole("radio", { name: "Tümü" })).toBeChecked();
  await expect(page.getByRole("region", { name: "Platform dağılımı tablosu" }).getByRole("row")).toHaveCount(5);
  await grup.getByText("Android", { exact: true }).click();
  await expect(page).toHaveURL(/platform=android/);
  await expect(page.getByRole("region", { name: "Platform dağılımı tablosu" }).getByRole("row")).toHaveCount(2);
  const kosular = page.getByRole("region", { name: "Koşular tablosu" });
  await expect(kosular.getByRole("row")).toHaveCount(2);
  await expect(kosular.getByTestId("platform-rozeti")).toHaveText("Platform: Android");
  await page.reload();
  await expect(page.getByRole("group", { name: "Platform" }).getByRole("radio", { name: "Android" })).toBeChecked();
  await page.screenshot({ path: `${DIZIN}/61-kule-android.png`, fullPage: true });
  await page.goto("/kosular?platform=ios");
  await expect(page.getByText("Süzgece uyan koşu yok.")).toBeVisible();
  expect(hatalar).toEqual([]);
});

test("009: triage sayfa kaynağı görüntüleyicisi (kaçışlı, sınırlı) ve kimlik onarım kartı (boş rol/ad satırı yok)", async ({ page }) => {
  const hatalar = konsolHatalariniTopla(page);
  await girisYap(page, "muhendis");
  await page.goto("/kosular/run-110");
  await expect(page.getByRole("list", { name: "Platform kontrolleri" })).toContainText("Yerel CI · Android");
  await page.getByRole("list", { name: "Triage kayıtları" }).getByRole("link", { name: "Triage sonucunu aç" }).click();
  await expect(page.getByTestId("triage-sinif")).toContainText("Android");
  const sk = page.getByTestId("sayfa-kaynagi");
  await sk.getByText("Sayfa kaynağını göster (XML)").click();
  const pre = sk.locator("pre.sayfa-kaynagi-xml");
  await expect(pre).toContainText('resource-id="login-button"');
  expect(await page.locator("hierarchy").count()).toBe(0);
  await expect(page.getByTestId("kanit-ekran").locator("img")).toBeVisible();
  await expect(page.getByTestId("onarim-sayfa-kaynagi")).toContainText("Kimlikler.java");
  await expect(page.getByTestId("onarim-niyet")).toHaveCount(0);
  await page.screenshot({ path: `${DIZIN}/62-triage-sayfa-kaynagi.png`, fullPage: true });
  expect(hatalar).toEqual([]);
});

const TEMALAR = [
  { tema: "koyu", colorScheme: "dark", dataTheme: "dark" },
  { tema: "acik", colorScheme: "light", dataTheme: "light" },
] as const;

const SAYFALAR: { yol: string; ad: string; hazir: (p: Page) => Promise<void> }[] = [
  { yol: "/kod", ad: "kod", hazir: (p) => expect(p.getByRole("group", { name: "Hedef platform" })).toBeVisible() },
  { yol: "/kod/scr-and", ad: "script-android", hazir: (p) => expect(p.getByRole("list", { name: "Ajan adımları" })).toBeVisible() },
  { yol: "/kontrol-kulesi?platform=android", ad: "kule-android", hazir: (p) => expect(p.getByRole("region", { name: "Platform dağılımı tablosu" })).toBeVisible() },
  { yol: "/kosular/run-110", ad: "kosu-android", hazir: (p) => expect(p.getByRole("list", { name: "Platform kontrolleri" })).toBeVisible() },
  {
    yol: "/hatalar/fail-5",
    ad: "triage-android",
    hazir: async (p) => {
      await p.getByTestId("sayfa-kaynagi").getByText("Sayfa kaynağını göster (XML)").click();
      await expect(p.locator("pre.sayfa-kaynagi-xml")).toBeVisible();
    },
  },
];

for (const tur of TEMALAR) {
  test(`009 ekranları: ${tur.tema} tema, 1440 ve 390 px — axe (ciddi/kritik yok), yatay taşma yok, ekran görüntüsü`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.addInitScript((t) => {
      localStorage.setItem("tp-tema-v", "2");
      localStorage.setItem("tp-tema", t);
    }, tur.tema);
    const ihlaller: string[] = [];
    const tasmalar: string[] = [];
    for (const genislik of [1440, 390]) {
      await page.setViewportSize({ width: genislik, height: 900 });
      await girisYap(page, "muhendis");
      for (const s of SAYFALAR) {
        await page.goto(s.yol);
        await s.hazir(page);
        await expect(page.getByRole("status").filter({ hasText: "Yükleniyor" })).toHaveCount(0);
        await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe(tur.colorScheme);
        await expect(page.locator("html")).toHaveAttribute("data-theme", tur.dataTheme);
        await fontlariBekle(page);
        await page.screenshot({ path: `${DIZIN}/${tur.tema}-${genislik}-${s.ad}.png`, fullPage: true, animations: "disabled" });
        const sw = await page.evaluate(() => document.documentElement.scrollWidth);
        if (sw > genislik) tasmalar.push(`${genislik}px ${s.yol}: scrollWidth ${sw}`);
        await page.addStyleTag({ content: ".kabuk::before,.giris-sayfa::before,.giris-sayfa::after{display:none}" });
        const sonuc = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
        for (const v of sonuc.violations.filter((x) => x.impact === "serious" || x.impact === "critical")) {
          ihlaller.push(`${tur.tema} ${genislik}px ${s.yol}: ${v.id} → ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`);
        }
      }
      await page.getByRole("button", { name: "Çıkış" }).click();
      await expect(page.getByRole("heading", { name: "Oturum aç" })).toBeVisible();
    }
    expect(ihlaller).toEqual([]);
    expect(tasmalar).toEqual([]);
  });
}
