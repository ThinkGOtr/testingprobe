// 013 §7 (K12) ekran testi: örnek veri derlemesinde (vite build --mode mock) asistan panelinin
// kalıcı yapay zekâ bildirimi, cevap kartı kip rozeti (CANLI · model / ŞABLON), 422 `kisisel_veri` ve
// 429 `donduruldu` metinleri. Arka uç gerekmez; mock arka uç kart numarasını ve art arda 3 sır
// reddini (sonraki istek 429, kalan_s 600) taklit eder.
//
// Özel Chrome (ör. Chrome for Testing): PW_CHROME_PATH=/yol/chrome npx playwright test e2e/asistan-guvenlik.spec.ts
// Değişken yoksa Playwright'ın kendi Chromium'u kullanılır (playwright.config.ts değişmez).
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

const CHROME = process.env.PW_CHROME_PATH;
if (CHROME) test.use({ launchOptions: { executablePath: CHROME } });

const EKRAN_DIZINI = "e2e/ekranlar/asistan-guvenlik";
mkdirSync(EKRAN_DIZINI, { recursive: true });

const YZ_BILDIRIMI = "Yapay zekâ asistanı; cevaplar hatalı olabilir, kararı ilgili ekranda siz verirsiniz.";
const KISISEL = "Soru kart numarası gibi kişisel veri içeriyor; çıkarıp yeniden deneyin.";
const DONDURULDU = "Asistan, art arda engellenen istekler nedeniyle ~10 dk kullanılamıyor.";
// Mock sır deseni; repo taramasına takılmasın diye parçalı yazılır.
const SAHTE_TOKEN = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4";

async function girisYap(page: Page, kullanici: string) {
  await page.goto("/giris");
  await page.getByLabel("Kullanıcı adı").fill(kullanici);
  await page.getByLabel("Parola").fill("Demo123!");
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("navigation", { name: "Ana menü" })).toBeVisible();
}

function konsolHatalariniTopla(page: Page): string[] {
  const hatalar: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") hatalar.push(m.text());
  });
  page.on("pageerror", (e) => hatalar.push(String(e)));
  return hatalar;
}

async function paneliAc(page: Page): Promise<Locator> {
  await page.getByRole("button", { name: "Asistanı aç", exact: true }).click();
  const p = page.getByTestId("asistan-paneli");
  await expect(p).toBeVisible();
  return p;
}

async function sor(p: Locator, metin: string) {
  await p.getByLabel("Sorunuz").fill(metin);
  await p.getByRole("button", { name: "Asistana sor" }).click();
}

async function sonCevap(p: Locator): Promise<Locator> {
  await expect(p.getByTestId("asistan-bekleme")).toHaveCount(0, { timeout: 15_000 });
  const kart = p.getByRole("article").last();
  await expect(kart).toBeVisible();
  return kart;
}

async function bildirimGorunur(p: Locator) {
  const not = p.getByTestId("asistan-yz-bildirimi");
  await expect(not).toBeVisible();
  await expect(not).toHaveAttribute("role", "note");
  await expect(not).toHaveText(YZ_BILDIRIMI);
}

test("bildirim her sekmede; canlı cevapta CANLI · Haiku 5.5, kart numarası 422 kisisel_veri", async ({ page }) => {
  const hatalar = konsolHatalariniTopla(page);
  await girisYap(page, "analist");
  await page.goto("/kosular");
  const p = await paneliAc(page);

  await bildirimGorunur(p);
  await p.getByRole("tab", { name: "Öneriler" }).click();
  await bildirimGorunur(p);
  await p.getByRole("tab", { name: "Sohbet" }).click();
  await bildirimGorunur(p);

  await sor(p, "Kırarak doğrula neden gri?");
  const kart = await sonCevap(p);
  const rozet = kart.getByTestId("kip-rozeti");
  await expect(rozet).toHaveText("CANLI · Haiku 5.5");
  await expect(rozet).toHaveAttribute("title", "Canlı model cevabı");
  await page.screenshot({ path: `${EKRAN_DIZINI}/01-canli-rozet.png` });

  const kartSorusu = "Müşterinin kartı 5105 1051 0510 5100 neden reddedildi?";
  await sor(p, kartSorusu);
  await expect(p.getByRole("alert").filter({ hasText: KISISEL })).toBeVisible();
  await expect(p.getByLabel("Sorunuz")).toHaveValue(kartSorusu);
  await expect(p.getByRole("button", { name: "Asistana sor" })).toBeEnabled();
  await page.screenshot({ path: `${EKRAN_DIZINI}/02-kisisel-veri.png` });

  const axe = await new AxeBuilder({ page })
    .include('[data-testid="asistan-paneli"]')
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(axe.violations.map((v) => `${v.id}: ${v.help} — ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
  expect(hatalar.filter((h) => !/422|429/.test(h))).toEqual([]);
});

test("şablon cevabında ŞABLON rozeti (açıklama title'da)", async ({ page }) => {
  await girisYap(page, "analist");
  await page.goto("/kosular");
  const p = await paneliAc(page);
  await p.getByRole("list", { name: "Soru önerileri" }).getByRole("button", { name: "Bugün ne yapmalıyım?" }).click();
  const kart = await sonCevap(p);
  await expect(kart.getByTestId("kip-rozeti")).toHaveText("ŞABLON");
  await expect(kart.getByTestId("kip-rozeti")).toHaveAttribute("title", "Hazır cevap · kayıt durumu");
});

test("art arda 3 sır reddi → 429 donduruldu: ~10 dk metni, gönderim kapalı, taslak korunur", async ({ page }) => {
  await girisYap(page, "analist");
  await page.goto("/kosular");
  const p = await paneliAc(page);
  for (let i = 0; i < 3; i++) {
    await sor(p, `Bu token ne işe yarar ${SAHTE_TOKEN} ${i}`);
    await expect(p.getByRole("alert").filter({ hasText: /parola\/token/ })).toBeVisible();
  }
  await sor(p, "Bu ekran ne işe yarar?");
  await expect(p.getByRole("alert").filter({ hasText: DONDURULDU })).toBeVisible();
  await expect(p.getByLabel("Sorunuz")).toHaveValue("Bu ekran ne işe yarar?");
  await expect(p.getByRole("button", { name: "Asistana sor" })).toBeDisabled();
  await page.screenshot({ path: `${EKRAN_DIZINI}/03-donduruldu.png` });
});

test("dar ekran ve koyu tema: bildirim tam görünür, yatay taşma yok", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.setViewportSize({ width: 360, height: 780 });
  await girisYap(page, "analist");
  await page.goto("/kosular");
  await page.getByRole("button", { name: /Asistanı aç/ }).click();
  const d = page.getByRole("dialog", { name: "Asistan" });
  await expect(d).toBeVisible();
  await bildirimGorunur(d);
  const not = d.getByTestId("asistan-yz-bildirimi");
  const tasma = await not.evaluate((el) => el.scrollWidth - el.clientWidth);
  expect(tasma).toBeLessThanOrEqual(0);
  await page.screenshot({ path: `${EKRAN_DIZINI}/04-dar-koyu.png` });
});
