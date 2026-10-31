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
