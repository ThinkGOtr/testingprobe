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

  // Ana demo yolu (REPLAY senaryosu `f2-kod-hatasi`, docs/DEMO-VERISI.md): F2 kampanya ve F4 kredi
  // limiti kod hatasıdır; F1/F3 dokümanda düzeltilir. AC2 özgün kalır ("7 adette 1 bedava") →
  // Demo-B'de 6 adet sınır case'i bugünkü kodda defect adayı olur.
  for (const [no, karar] of [
    ["F1", "Dokümanı düzelt"],
    ["F2", "Kod/veri hatalı"],
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

// Demo-B uçtan uca (canlı yığın, REPLAY): onaylı TPD-1 case'lerinden kod üretimi → yerel kontrol →
// PR (LocalForge) → kırarak doğrula (yeşil → kırmızı → yeşil) → merge; sınır case'i defect adayı;
// sunucu: Kontrol Kulesi (KPI kaynakları) ve deploy tetiği. Demo-A tamamlanmış olmalı (onaylı case'ler):
//   DEMOB_UI=1 set -a; . ../.env; set +a; PORTAL_LIVE=1 npx playwright test -g Demo-B
async function girisCanli(page: Page, kullanici: string) {
  await page.goto("/giris");
  await page.getByLabel("Kullanıcı adı").fill(kullanici);
  await page.getByLabel("Parola").fill(PAROLA);
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("navigation", { name: "Ana menü" })).toBeVisible();
}

/** Liste satırı (script) bulunana ve koşul sağlanana kadar sayfayı yeniler. */
async function bekleSatir(page: Page, baslik: RegExp, metin: RegExp, sure_ms: number) {
  await expect(async () => {
    await page.reload();
    const satir = page.getByRole("row").filter({ has: page.getByRole("link", { name: baslik }) }).first();
    await expect(satir).toContainText(metin, { timeout: 2_000 });
  }).toPass({ timeout: sure_ms, intervals: [3_000] });
}

test("Demo-B: kod üretimi → yerel kontrol → PR → kırarak doğrula → merge; defect adayı; Kontrol Kulesi", async ({ page }) => {
  test.skip(process.env.DEMOB_UI !== "1", "DEMOB_UI=1 ile, Demo-A (onaylı TPD-1 case'leri) sonrası koşar");
  test.setTimeout(20 * 60_000);
  const hatalar: string[] = [];
  page.on("pageerror", (e) => hatalar.push(String(e)));
  const uclar = await cekirdekUclari(page);
  for (const u of ["/scripts", "/scripts/{}", "/code/generate", "/scripts/{}/break-verify", "/prs/{}/merge", "/runs", "/runs/{}", "/control-tower", "/ci/trigger"]) {
    expect(uclar, `çekirdek ${u} sunmuyor (Demo-B şeritleri birleşmemiş)`).toContain(u);
  }

  // Mühendis: rol bazlı açılış Kod üretimi.
  await girisCanli(page, "muhendis");
  await expect(page).toHaveURL(/\/kod$/);
  await expect(page.getByText("ÖRNEK VERİ")).toHaveCount(0);
  const yedi = /7 adet kampanyalı üründe 1 adet bedava verilir/;
  const alti = /6 adet kampanyalı üründe bedava ürün verilmez/;
  // Onaylı case listesi yüklenmeden sayılırsa (count() beklemez) hiçbir kutu işaretlenmez.
  await expect(page.getByRole("checkbox").or(page.getByRole("row")).first()).toBeVisible({ timeout: 30_000 });
  for (const ad of [yedi, alti]) {
    const kutu = page.getByRole("checkbox", { name: ad });
    if ((await kutu.count()) > 0) await kutu.first().check();
  }
  const uret = page.getByRole("button", { name: /Seçilenler için kod üret \([1-9]/ });
  if (await uret.isEnabled().catch(() => false)) {
    await uret.click();
    await expect(page.getByRole("status").filter({ hasText: /kod üretimi/i }).or(page.getByText(/kod üretimi/i).first())).toBeVisible();
  }
  await page.screenshot({ path: `${EKRAN_DIZINI}/demob-01-kod-uretimi.png`, fullPage: true });

  // 7 adet: PR açılır (yerel kontrol yeşil).
  await bekleSatir(page, yedi, /PR açık|Birleştirildi/, 8 * 60_000);
  await page.getByRole("link", { name: yedi }).first().click();
  await expect(page.getByText("REPLAY", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("region", { name: "Eşlenen adımlar tablosu" })).toContainText("expect");
  // PR CI işi PR açıldıktan sonra kuyruğa alınır: check satırı (bekliyor/geçti) birkaç saniye sonra gelir.
  await expect(async () => {
    await page.reload();
    await expect(page.getByRole("list", { name: "PR check'leri" })).toBeVisible({ timeout: 3_000 });
  }).toPass({ timeout: 120_000, intervals: [3_000] });
  const adimEkran = page.locator(".ajan-ekran img");
  if ((await adimEkran.count()) > 0) await expect(adimEkran.first()).toHaveJSProperty("complete", true);
  await page.screenshot({ path: `${EKRAN_DIZINI}/demob-02-script-pr.png`, fullPage: true });

  const kir = page.getByRole("button", { name: /Kırarak doğrula|Yeniden doğrula/ });
  if (await page.getByText("Test hata yakalıyor ✓").isHidden()) {
    await kir.click();
    await expect(page.getByText("Test hata yakalıyor ✓")).toBeVisible({ timeout: 8 * 60_000 });
  }
  await page.screenshot({ path: `${EKRAN_DIZINI}/demob-03-kirarak-dogrula.png`, fullPage: true });
  const merge = page.getByRole("button", { name: "Merge et" });
  // Yeniden koşuda PR zaten birleştirilmiş olabilir (düğme yok): beklemeden atlanır.
  if ((await merge.count()) > 0 && (await merge.isEnabled())) {
    await merge.click();
    await expect(page.locator(".sayfa-basligi").getByText("Birleştirildi")).toBeVisible({ timeout: 90_000 });
  }
  await page.screenshot({ path: `${EKRAN_DIZINI}/demob-04-merge.png`, fullPage: true });

  // 6 adet: assertion kırmızı → defect adayı, PR yok.
  await page.goto("/kod");
  await bekleSatir(page, alti, /Defect adayı|İnsana düştü/, 8 * 60_000);
  await page.getByRole("link", { name: alti }).first().click();
  await expect(page.getByTestId("yerel-sinif")).toContainText("Defect adayı");
  await page.screenshot({ path: `${EKRAN_DIZINI}/demob-05-defect-adayi.png`, fullPage: true });
  await page.getByRole("button", { name: "Çıkış" }).click();

  // Sunucu: açılış Kontrol Kulesi; KPI kaynakları; uydurma yok; deploy tetiği.
  await girisCanli(page, "sunucu");
  await expect(page).toHaveURL(/\/kontrol-kulesi$/);
  await expect(page.getByRole("img", { name: /^Kaynak: run\.sonuc/ })).toBeVisible();
  await expect(page.getByText("ÖRNEK VERİ")).toHaveCount(0);
  await page.screenshot({ path: `${EKRAN_DIZINI}/demob-06-kontrol-kulesi.png`, fullPage: true });
  await page.goto("/kosular");
  // Satır sayısı tablo yüklendikten sonra okunur (sayaç "N/M koşu" görünür); yeniden yüklemede de.
  const sayac = page.getByRole("status").filter({ hasText: /\d+\/\d+ koşu/ });
  const satirlar = page.getByRole("region", { name: "Koşular tablosu" }).getByRole("row");
  await expect(sayac).toBeVisible();
  const once = await satirlar.count();
  await page.getByRole("button", { name: "Deploy tetikle" }).click();
  // Önceki deploy koşusu hâlâ kuyruktaysa core yeni koşu açmaz ("zaten kuyrukta"): satır eklenmez.
  const zatenKuyrukta = page.getByText(/zaten kuyrukta/).first();
  await expect(page.getByText(/kuyruğa alındı|zaten kuyrukta/).first()).toBeVisible();
  if (!(await zatenKuyrukta.isVisible())) {
    await expect(async () => {
      await page.reload();
      await expect(sayac).toBeVisible({ timeout: 5_000 });
      expect(await satirlar.count()).toBeGreaterThan(once);
    }).toPass({ timeout: 90_000, intervals: [3_000] });
  }
  await page.screenshot({ path: `${EKRAN_DIZINI}/demob-07-kosular.png`, fullPage: true });
  expect(hatalar).toEqual([]);
});

test("koşu raporu: Playwright HTML raporu tek CSP ile açılır ve çizilir (boş sayfa değil)", async ({ page }) => {
  await page.goto("/giris");
  await page.getByLabel("Kullanıcı adı").fill("sunucu");
  await page.getByLabel("Parola").fill(PAROLA);
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("navigation", { name: "Ana menü" })).toBeVisible();
  const kosular = (await (await page.request.get("/api/runs")).json()) as { rapor_url: string | null }[];
  const rapor = kosular.find((k) => k.rapor_url)?.rapor_url;
  test.skip(!rapor, "HTML raporu olan koşu yok");
  const csp: string[] = [];
  const cspHatalari: string[] = [];
  page.on("response", async (r) => {
    if (r.url().endsWith(rapor!)) for (const h of await r.headersArray()) if (h.name.toLowerCase() === "content-security-policy") csp.push(h.value);
  });
  page.on("console", (m) => {
    if (/Content Security Policy/i.test(m.text())) cspHatalari.push(m.text());
  });
  await page.goto(rapor!);
  // Rapor satır içi betikle #root'u doldurur; portal CSP'si de gelirse betik engellenir ve #root boş kalır.
  await expect(page.locator("#root > *").first()).toBeAttached({ timeout: 10_000 });
  expect(csp, "artefakt yanıtında tek CSP (core sandbox) olmalı").toHaveLength(1);
  expect(csp[0]).toMatch(/^sandbox /);
  expect(cspHatalari).toEqual([]);
});

// Faz 4 bug yolu (canlı): testçi açık bir bug taslağını açar, mükerrer adaylarını (jira-sim araması +
// dup_rank, REPLAY) görür ve karar verir: AI "bağla" öneriyorsa önerilen kayda bağlar, değilse yeni
// kayıt açar. Sonuç Jira (jira-sim) bağlantısıyla görünmelidir. Yığını değiştirir (jira-sim'e yazar);
// karar bekleyen taslak yoksa atlanır (`make reset` ve demo akışıyla taslak oluşur).
test("testçi: bug taslağı → mükerrer adayları → karar → jira-sim bağlantısı", async ({ page }) => {
  test.setTimeout(120_000);
  const hatalar: string[] = [];
  page.on("pageerror", (e) => hatalar.push(String(e)));
  const uclar = await cekirdekUclari(page);
  test.skip(!uclar.includes("/bug-drafts/{}/decision"), "çekirdek POST /bug-drafts/{id}/decision sunmuyor (Faz 4 bugs şeridi yığında değil)");

  await page.goto("/giris");
  await page.getByLabel("Kullanıcı adı").fill("testci");
  await page.getByLabel("Parola").fill(PAROLA);
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("navigation", { name: "Ana menü" })).toBeVisible();
  await page.goto("/bug-taslaklari");
  await expect(page.getByRole("heading", { name: "Bug taslakları", level: 1 })).toBeVisible();
  // Liste yüklenene kadar bekle (ilk görüntüde tablo boş olabilir; aksi hâlde test yanlışlıkla atlanır).
  await expect(page.getByRole("row").nth(1)).toBeVisible({ timeout: 15_000 }).catch(() => undefined);
  const bekleyen = page.getByRole("row").filter({ hasText: "Onay bekliyor" }).first();
  test.skip(!(await bekleyen.isVisible().catch(() => false)), "karar bekleyen bug taslağı yok");
  await page.screenshot({ path: `${EKRAN_DIZINI}/10-bug-taslaklari.png`, fullPage: true });
  await bekleyen.getByRole("link").first().click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  // Arama sürüyorsa bitmesini bekle (SSE ya da yenileme).
  await expect(page.getByText("Jira'da benzer açık bug'lar aranıyor…")).toHaveCount(0, { timeout: 60_000 });
  await page.screenshot({ path: `${EKRAN_DIZINI}/11-bug-taslak.png`, fullPage: true });

  const oneri = page.getByTestId("mukerrer-onerisi");
  const bagla = (await oneri.isVisible().catch(() => false)) && /mevcut kayda bağla \((TPD-\d+)\)/.exec((await oneri.textContent()) ?? "");
  if (bagla) {
    await page.getByRole("button", { name: `${bagla[1]} kaydına bağla` }).click();
  } else {
    await page.getByRole("button", { name: "Onayla ve Jira'da aç" }).click();
  }
  const sonuc = page.getByTestId("yayin-sonucu");
  await expect(sonuc).toBeVisible({ timeout: 60_000 });
  await expect(sonuc.getByRole("link").first()).toHaveAttribute("href", /\/browse\/TPD-\d+$/);
  await page.screenshot({ path: `${EKRAN_DIZINI}/12-bug-yayinlandi.png`, fullPage: true });
  expect(hatalar).toEqual([]);
});
