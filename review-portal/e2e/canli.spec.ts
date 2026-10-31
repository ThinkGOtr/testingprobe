// Canlı yığın testi (PORTAL_LIVE=1): portal gerçek core-api'ye bağlıdır (örnek veri değil).
// Analist olarak girer, gerekirse Jira'dan (jira-sim) çeker, TPD-1'i açar ve ekranın çekirdekten
// geldiğini doğrular. Çalıştırma:
//
//   set -a; . ../.env; set +a; PORTAL_LIVE=1 npx playwright test
//
// PORTAL_URL varsayılanı compose portalıdır (http://127.0.0.1:8080). Yerel geliştirme sunucusuyla
// (npm run dev, /api → 127.0.0.1:8000): PORTAL_URL=http://127.0.0.1:5173.
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

const EKRAN_DIZINI = "e2e/ekranlar/canli";
mkdirSync(EKRAN_DIZINI, { recursive: true });

const PAROLA = process.env.PORTAL_PASSWORD ?? process.env.SEED_USER_PASSWORD ?? "";

/** Gereksinim uçları çekirdekte mi? Değilse portal örnek veriye düşer: canlı test anlamsızdır. */
async function cekirdekUclari(page: Page): Promise<string[]> {
  const r = await page.request.get("/api/openapi.json");
  expect(r.ok(), "core-api openapi.json okunamadı (yığın ayakta mı?)").toBe(true);
  // Parametre adları önemsiz (portal da `{param}`'ı tek yol parçası sayar): `{x}` → `{}`.
  return Object.keys(((await r.json()) as { paths: Record<string, unknown> }).paths).map((y) =>
    y.replace(/\{[^}]+\}/g, "{}"),
  );
}

test.beforeAll(() => {
  if (!PAROLA) throw new Error("SEED_USER_PASSWORD (veya PORTAL_PASSWORD) ortamda yok: `set -a; . ../.env; set +a`");
});

test("analist: giriş → gereksinimler (çekirdek) → TPD-1 detayı", async ({ page }) => {
  const hatalar: string[] = [];
  page.on("pageerror", (e) => hatalar.push(String(e)));

  const uclar = await cekirdekUclari(page);
  expect(uclar, "çekirdek GET /requirements sunmuyor; portal örnek veriye düşerdi").toContain("/requirements");
  expect(uclar).toContain("/requirements/{}");

  await page.goto("/giris");
  await page.getByLabel("Kullanıcı adı").fill("analist");
  await page.getByLabel("Parola").fill(PAROLA);
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("navigation", { name: "Ana menü" })).toBeVisible();
  await expect(page.locator(".kullanici-ad")).toHaveText("analist");

  await page.goto("/gereksinimler");
  await expect(page.getByRole("heading", { name: "Gereksinimler", level: 1 })).toBeVisible();
  const tpd1 = page.getByRole("row").filter({ hasText: "TPD-1" }).first();
  if (!(await tpd1.isVisible().catch(() => false))) {
    // Boş veritabanı: Jira'dan (jira-sim) çek; liste SSE ile ya da yenilemeyle dolar.
    await page.getByRole("button", { name: "Jira'dan çek" }).click();
    await expect(async () => {
      await page.reload();
      await expect(page.getByRole("row").filter({ hasText: "TPD-1" }).first()).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 60_000 });
  }
  // Gereksinim listesi çekirdekten: "ÖRNEK VERİ" rozeti varsa ipucunda bu uç olmamalı.
  const rozet = page.getByText("ÖRNEK VERİ");
  if (await rozet.isVisible().catch(() => false)) {
    await expect(rozet).not.toHaveAttribute("title", /GET \/requirements(\s|,|$)/);
  }
  await page.screenshot({ path: `${EKRAN_DIZINI}/01-gereksinimler.png`, fullPage: true });

  await page.getByRole("row").filter({ hasText: "TPD-1" }).first().getByRole("link").click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Kampanyalı sepet");
  await expect(page.locator(".baslik-anahtar")).toHaveText("TPD-1");
  // Seed'deki AC1 (DEMO-VERISI.md) çekirdekten geldi.
  await expect(page.getByText(/"Sepete ekle" butonuna bastığında ürün sepete eklenir/).first()).toBeVisible();
  // Jira bağlantısı jira-sim'e gider.
  await expect(page.getByRole("link", { name: /Jira'da aç/ })).toHaveAttribute("href", /\/browse\/TPD-1$/);
  // Akış adımları (stepper) çizilir.
  await expect(page.getByRole("navigation", { name: "14 adımlı akıştaki ilerleme" })).toBeVisible();
  // Anahtarsız yığında model çıktısı REPLAY'dir: ön inceleme yapıldıysa rozeti görünür.
  if (await page.getByText("Ön inceleme henüz yapılmadı.").isHidden()) {
    await expect(page.getByText(/^REPLAY(-MISS)?$/).first()).toBeVisible();
  }
  await page.screenshot({ path: `${EKRAN_DIZINI}/02-tpd1.png`, fullPage: true });
  expect(hatalar).toEqual([]);
});

// Demo-A uçtan uca (TPD-1), yalnızca portal ve jira-sim arayüzleriyle. Taze yığın ister
// (`make reset`): DEMOA_UI=1 set -a; . ../.env; set +a; PORTAL_LIVE=1 npx playwright test
const JIRA_URL = process.env.JIRA_SIM_URL ?? "http://127.0.0.1:8090";
test("Demo-A: ön inceleme → 4 doğrulanmış bulgu → düzeltme → Jira PO onayı → case → yayın", async ({ page, browser }) => {
  test.skip(process.env.DEMOA_UI !== "1", "DEMOA_UI=1 ile ve `make reset` sonrası koşar");
  test.setTimeout(300_000);
  const hatalar: string[] = [];
  page.on("pageerror", (e) => hatalar.push(String(e)));
  const ekran = (ad: string) => page.screenshot({ path: `${EKRAN_DIZINI}/demoa-${ad}.png`, fullPage: true });

  await page.goto("/giris");
  await page.getByLabel("Kullanıcı adı").fill("analist");
  await page.getByLabel("Parola").fill(PAROLA);
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("navigation", { name: "Ana menü" })).toBeVisible();
  await page.goto("/gereksinimler");
  const satir = page.getByRole("row").filter({ hasText: "TPD-1" }).first();
  if (!(await satir.waitFor({ timeout: 10_000 }).then(() => true).catch(() => false))) {
    await page.getByRole("button", { name: "Jira'dan çek" }).click();
    await expect(async () => {
      await page.reload();
      await expect(page.getByRole("row").filter({ hasText: "TPD-1" }).first()).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 60_000 });
  }
  await page.getByRole("row").filter({ hasText: "TPD-1" }).first().getByRole("link").click();
  await page.getByRole("button", { name: "Ön incelemeyi başlat" }).click();

  // 4 bilerek konmuş uyumsuzluk, kanıtı deterministik doğrulanmış olarak gelir.
  const kartlar = page.locator("article.bulgu");
  await expect(kartlar).toHaveCount(4, { timeout: 120_000 });
  await expect(page.locator("article.bulgu .rozet-dogrulandi")).toHaveCount(4);
  for (const no of ["F1", "F2", "F3", "F4"]) {
    await expect(page.getByTestId("bulgu-etiketi").filter({ hasText: `${no} (tur 1)` })).toHaveCount(1);
  }
  await expect(page.getByText(/^REPLAY$/).first()).toBeVisible();
  await expect(page.getByText(/^live$|CANLI/i)).toHaveCount(0);
  await ekran("01-bulgular");

  for (const [no, karar] of [
    ["F1", "Dokümanı düzelt"],
    ["F2", "Dokümanı düzelt"],
    ["F3", "Dokümanı düzelt"],
    ["F4", "Kod/veri hatalı"],
  ] as const) {
    const kart = kartlar.filter({ has: page.getByTestId("bulgu-etiketi").filter({ hasText: `${no} (tur 1)` }) });
    await kart.getByRole("radio", { name: new RegExp(karar.replace("/", "\\/")) }).check();
    await kart.getByRole("button", { name: "Kararı kaydet" }).click();
    await expect(kart.getByText(/Karar:/)).toBeVisible({ timeout: 15_000 });
  }
  await ekran("02-kararlar");
  await page.getByRole("button", { name: /Düzeltmeleri Jira'ya yaz/ }).click();
  // 2. tur (TPD-1-r2) temiz → son hal → PO soru yorumu + tp-po-pending.
  await expect(page.getByText("PO teyidi bekliyor").first()).toBeVisible({ timeout: 120_000 });
  await ekran("03-po-bekleniyor");

  // PO, jira-sim arayüzünde onaylar (insan onay kapısı; portal değil).
  const jira = await browser.newPage();
  await jira.goto(`${JIRA_URL}/giris?sonra=/browse/TPD-1`);
  await jira.locator("#po-parola").fill(process.env.JIRA_SIM_PO_PASSWORD ?? "");
  await jira.getByRole("button", { name: "Giriş yap" }).click();
  await expect(jira.getByText(/Testing Probe ön inceleme — TPD-1 için PO teyidi/).first()).toBeVisible();
  await expect(jira.getByText("tp-po-pending").first()).toBeVisible();
  await jira.getByTestId("po-onayla").click();
  await jira.screenshot({ path: `${EKRAN_DIZINI}/demoa-04-jira-po-onayi.png`, fullPage: true });

  await expect(async () => {
    await page.reload();
    await expect(page.getByRole("button", { name: "Case üret" })).toBeEnabled({ timeout: 2_000 });
  }).toPass({ timeout: 90_000 });
  await page.getByRole("button", { name: "Case üret" }).click();
  await expect(page.getByRole("link", { name: "Case review" })).toBeVisible({ timeout: 120_000 });
  await page.getByRole("link", { name: "Case review" }).click();
  const onayla = page.getByRole("button", { name: "Onayla", exact: true });
  await expect(onayla.first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/^REPLAY$/).first()).toBeVisible();
  await ekran("05-case-review");
  for (let i = 0; i < 20 && (await onayla.count()) > 0; i++) {
    const n = await onayla.count();
    await onayla.first().click();
    await expect(onayla).toHaveCount(n - 1, { timeout: 15_000 });
  }
  await page.getByRole("link", { name: "Yayın önizleme" }).first().click();
  await page.getByRole("button", { name: /Seçilenleri yayınla/ }).click();
  await expect(page.getByTestId("yayin-ozeti")).toContainText(/[1-9]\d* oluşturuldu/, { timeout: 90_000 });
  await expect(page.getByTestId("yayin-ozeti")).toContainText("0 başarısız");
  await ekran("06-yayin");

  // Zincir çapası yorumu yayın işinin son adımında yazılır.
  await expect(async () => {
    await jira.goto(`${JIRA_URL}/browse/TPD-1`);
    await expect(jira.getByText(/test case yayınlandı/).first()).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 60_000 });
  await jira.screenshot({ path: `${EKRAN_DIZINI}/demoa-07-jira-baglantilar.png`, fullPage: true });
  expect(hatalar).toEqual([]);
});
