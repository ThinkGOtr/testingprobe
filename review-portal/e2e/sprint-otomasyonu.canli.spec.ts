// 013 sprint otomasyonu — canlı yığın ekran testi (Chrome for Testing).
//
// Çalıştırma (izole yığın ayakta, `make demo-prova` sonrası veriyle):
//   set -a; . ../.env; set +a
//   PORTAL_LIVE=1 PORTAL_URL=http://127.0.0.1:38180 TP_CFT_PATH="<Chrome for Testing yolu>" \
//     npx playwright test e2e/sprint-otomasyonu.canli.spec.ts
//
// Ekran görüntüleri: e2e/ekranlar/013/. Parola izi tutulmaz (canlı modda trace kapalı).
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

const EKRAN = "e2e/ekranlar/013";
mkdirSync(EKRAN, { recursive: true });

const PAROLA =
  process.env.PORTAL_PASSWORD ?? process.env.SEED_USER_PASSWORD ?? "";
if (process.env.TP_CFT_PATH)
  test.use({ launchOptions: { executablePath: process.env.TP_CFT_PATH } });

test.describe.configure({ mode: "serial" });

async function giris(page: Page, kullanici: string): Promise<void> {
  await page.context().clearCookies(); // rol değişimi: önceki oturum kapanır
  await page.goto("/giris");
  await page.getByLabel("Kullanıcı adı").fill(kullanici);
  await page.getByLabel("Parola").fill(PAROLA);
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(
    page.getByRole("navigation", { name: "Ana menü" }),
  ).toBeVisible();
}

/** Ekran görüntüsünden önce: sayfadaki tüm yükleme göstergeleri kaybolsun. */
async function yuklendi(page: Page): Promise<void> {
  await expect(page.getByText("Yükleniyor...")).toHaveCount(0, {
    timeout: 30_000,
  });
}

const hatalar: string[] = [];
test.beforeEach(({ page }) => {
  if (!PAROLA)
    throw new Error(
      "SEED_USER_PASSWORD ortamda yok: `set -a; . ../.env; set +a`",
    );
  page.on("pageerror", (e) => hatalar.push(String(e)));
});
test.afterEach(() => {
  expect(hatalar, "sayfada yakalanmamış JS hatası").toEqual([]);
});

test("1. Otomasyon sayfası: ayarlar, REPLAY uyarısı, Jira tetiği", async ({
  page,
}) => {
  await giris(page, "analist");
  await page.goto("/otomasyon");
  await expect(
    page.getByRole("heading", { name: "Otomasyon", level: 1 }),
  ).toBeVisible();
  await expect(
    page.getByText(/Onay sonrası otomatik kod/i).first(),
  ).toBeVisible();
  await expect(page.getByText(/Jira/).first()).toBeVisible();
  // K23: demo yığını REPLAY kipinde → uyarı görünür.
  await expect(
    page.getByText(/Demo kayıtları bu ayara göre değil/),
  ).toBeVisible();
  await yuklendi(page);
  await page.screenshot({ path: `${EKRAN}/01-otomasyon.png`, fullPage: true });
});

test("2. Test verisi kataloğu: gruplar, gizli kayıt rozeti, ekle ve geçmiş", async ({
  page,
}) => {
  await giris(page, "analist");
  await page.goto("/test-verisi");
  await expect(
    page.getByRole("heading", { name: "Test verisi", level: 1 }),
  ).toBeVisible();
  await expect(page.getByText("ortak.demo_parola").first()).toBeVisible();
  await expect(page.getByText(/sır tanımlı/i).first()).toBeVisible();
  // Gizli değer sayfanın hiçbir yerinde düz görünmez.
  await expect(page.locator("body")).not.toContainText(
    process.env.TP_TESTVERI_DEMO_PAROLA ?? "Demo123!",
  );
  await yuklendi(page);
  await page.screenshot({
    path: `${EKRAN}/02-test-verisi.png`,
    fullPage: true,
  });
});

type Gereksinim = {
  id: string;
  jira_key?: string;
  durum?: string;
  otomatik_akis?: { durum: string; neden: string | null } | null;
};

async function gereksinim(
  page: Page,
  anahtar: string,
): Promise<Gereksinim | undefined> {
  const r = await page.request.get("/api/requirements");
  expect(r.ok()).toBe(true);
  return ((await r.json()) as Gereksinim[]).find((g) => g.jira_key === anahtar);
}

async function caseReview(page: Page, anahtar = "TPD-1"): Promise<void> {
  const g = await gereksinim(page, anahtar);
  expect(
    g,
    `${anahtar} gereksinimi yok (demo provası koşuldu mu?)`,
  ).toBeTruthy();
  await page.goto(`/gereksinimler/${g!.id}/caseler`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

test("3. Case review: test verisi atıfları çip olarak, gizli değer düz değil", async ({
  page,
}) => {
  await giris(page, "analist");
  await caseReview(page);
  await expect(page.locator(".veri-atif").first()).toBeVisible();
  await expect(page.locator("body")).not.toContainText(
    process.env.TP_TESTVERI_DEMO_PAROLA ?? "Demo123!",
  );
  await yuklendi(page);
  await page.screenshot({
    path: `${EKRAN}/03a-case-review-atif.png`,
    fullPage: true,
  });
});

test("3b. K10: katalog değeri onaydan sonra değişince onaylı case uyarır", async ({
  page,
}) => {
  await giris(page, "analist");
  await page.goto("/test-verisi");
  await page.getByRole("button", { name: "bayi.bayi1.ad düzenle" }).click();
  const deger = page.getByLabel("Değer", { exact: true });
  const eski = await deger.inputValue();
  await deger.fill(`${eski} (013 ekran testi)`);
  await page
    .getByRole("button", { name: /^Kaydet/ })
    .first()
    .click();
  await expect(page.getByText(`${eski} (013 ekran testi)`).first()).toBeVisible(
    { timeout: 10_000 },
  );
  await caseReview(page);
  const uyari = page.getByTestId("case-veri-degisti").first();
  await expect(uyari).toBeVisible({ timeout: 15_000 });
  await uyari.scrollIntoViewIfNeeded();
  await yuklendi(page);
  await page.screenshot({
    path: `${EKRAN}/03b-veri-onaydan-sonra-degisti.png`,
  });
  // Geri al: katalog eski değerine döner.
  await page.goto("/test-verisi");
  await page.getByRole("button", { name: "bayi.bayi1.ad düzenle" }).click();
  await page.getByLabel("Değer", { exact: true }).fill(eski);
  await page
    .getByRole("button", { name: /^Kaydet/ })
    .first()
    .click();
  await expect(page.getByText(`${eski} (013 ekran testi)`)).toHaveCount(0, {
    timeout: 10_000,
  });
});

test("4. İsmail akışı: QA To Do → tetik → ön inceleme → PO → otomatik case → toplu onay", async ({
  page,
}) => {
  test.setTimeout(480_000);
  await giris(page, "sunucu");
  await page.goto("/demo");
  await page.getByLabel(/Story/i).first().fill("TPD-4");
  await page.getByRole("button", { name: /QA To Do'ya taşı/ }).click();
  await expect(page.getByText(/taşındı|zaten/i).first()).toBeVisible({
    timeout: 15_000,
  });
  await yuklendi(page);
  await page.screenshot({
    path: `${EKRAN}/04a-demo-qa-to-do.png`,
    fullPage: true,
  });

  // Tetik turu (≤ aralık) story'yi akışa alır: ön inceleme kendiliğinden başlar.
  let g: Gereksinim | undefined;
  await expect(async () => {
    g = await gereksinim(page, "TPD-4");
    expect(g?.otomatik_akis, "TPD-4 henüz tetiklenmedi").toBeTruthy();
    expect([
      "pending_po",
      "findings_open",
      "po_approved",
      "generating",
      "cases_ready",
      "failed",
    ]).toContain(g?.durum);
  }).toPass({ timeout: 240_000, intervals: [5_000] });
  await page.goto("/otomasyon");
  await yuklendi(page);
  await expect(page.getByText("TPD-4").first()).toBeVisible({
    timeout: 90_000,
  });
  await page.screenshot({
    path: `${EKRAN}/04b-otomasyon-tetik-sonucu.png`,
    fullPage: true,
  });
  await page.goto("/gereksinimler");
  await expect(
    page.getByRole("row").filter({ hasText: "TPD-4" }).first(),
  ).toBeVisible();
  await yuklendi(page);
  await page.screenshot({
    path: `${EKRAN}/04c-gereksinim-otomatik-akis-rozeti.png`,
    fullPage: true,
  });
  test.skip(
    !["pending_po", "po_approved", "generating", "cases_ready"].includes(
      g?.durum ?? "",
    ),
    `TPD-4 ön inceleme sonrası durumu ${g?.durum} (PO adımına gelmedi)`,
  );
  if (g?.durum === "pending_po") {
    // PO insan kapısı jira-sim'de (provanın A5 adımıyla aynı yol): etiket PO kimliğiyle.
    const poParola = process.env.JIRA_SIM_PO_PASSWORD ?? "";
    const jira =
      process.env.JIRA_SIM_URL ??
      `http://127.0.0.1:${process.env.JIRA_SIM_PORT ?? "8090"}`;
    const po = await page.request.put(`${jira}/rest/api/3/issue/TPD-4`, {
      headers: {
        Authorization: `Basic ${Buffer.from(`po@sim.local:${poParola}`).toString("base64")}`,
      },
      data: { update: { labels: [{ add: "tp-po-approved" }] } },
    });
    expect(po.ok(), `jira-sim PO etiketi: ${po.status()}`).toBe(true);
  }

  // PO onayı işlenince otomatik case üretimi kendiliğinden başlar ve biter.
  await expect(async () => {
    g = await gereksinim(page, "TPD-4");
    expect(g?.durum).toBe("cases_ready");
  }).toPass({ timeout: 180_000, intervals: [5_000] });

  await giris(page, "analist");
  await caseReview(page, "TPD-4");
  await expect(page.locator("article.case").first()).toBeVisible({
    timeout: 30_000,
  });
  await yuklendi(page);
  await page.screenshot({
    path: `${EKRAN}/04d-otomatik-uretilen-taslaklar.png`,
    fullPage: true,
  });
  // K13': kartlar en az 3 sn kesintisiz görünür kalmalı; sayım ancak sonra açılır.
  for (const kart of await page.locator("article.case").all()) {
    await kart.scrollIntoViewIfNeeded().catch(() => undefined);
    await page.waitForTimeout(3_500);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  const toplu = page.getByRole("button", { name: /Tümünü onayla/ });
  await expect(toplu).toBeEnabled({ timeout: 15_000 });
  await yuklendi(page);
  await page.screenshot({
    path: `${EKRAN}/04e-toplu-onay-hazir.png`,
    fullPage: true,
  });
  await toplu.click();
  const teyit = page.getByRole("group", { name: "Toplu onay teyidi" });
  await teyit.getByRole("checkbox").check();
  await yuklendi(page);
  await page.screenshot({
    path: `${EKRAN}/04f-toplu-onay-teyit.png`,
    fullPage: true,
  });
  await teyit.getByRole("button", { name: /^Onayla \(/ }).click();
  await expect(page.getByText(/onaylandı/i).first()).toBeVisible({
    timeout: 20_000,
  });
  await yuklendi(page);
  await page.screenshot({
    path: `${EKRAN}/04g-toplu-onay-sonuc.png`,
    fullPage: true,
  });
});

test("5. Kod üretimi ekranı", async ({ page }) => {
  await giris(page, "muhendis");
  await page.goto("/kod");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await yuklendi(page);
  await page.screenshot({
    path: `${EKRAN}/05-kod-uretimi.png`,
    fullPage: true,
  });
});
