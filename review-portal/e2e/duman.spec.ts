import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

const EKRAN_DIZINI = "e2e/ekranlar";
mkdirSync(EKRAN_DIZINI, { recursive: true });

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

const ROTALAR: { yol: string; ad: string; baslik: RegExp }[] = [
  { yol: "/gereksinimler", ad: "01-gereksinimler", baslik: /^Gereksinimler$/ },
  { yol: "/gereksinimler/req-tpd-1", ad: "02-gereksinim-tpd1", baslik: /Kampanyalı sepet/ },
  { yol: "/gereksinimler/req-ft-1", ad: "03-gereksinim-serbest-metin", baslik: /Sepetten ürün çıkarma/ },
  { yol: "/gereksinimler/req-tpd-3", ad: "04-gereksinim-tpd3-injection", baslik: /Ürün arama/ },
  { yol: "/gereksinimler/req-tpd-1/caseler", ad: "05-case-review", baslik: /^Case review$/ },
  { yol: "/gereksinimler/req-tpd-1/yayin", ad: "06-yayin-onizleme", baslik: /^Yayın önizleme$/ },
  { yol: "/kod", ad: "07-kod-uretimi", baslik: /^Kod üretimi$/ },
  { yol: "/kod/scr-2", ad: "08-script-detay", baslik: /7 adet kampanyalı/ },
  { yol: "/kod/scr-3", ad: "08b-script-defect-adayi", baslik: /6 adet kampanyalı/ },
  { yol: "/kosular", ad: "09-kosular", baslik: /^Koşular$/ },
  { yol: "/kosular/run-107", ad: "10-kosu-detay", baslik: /run-107/ },
  { yol: "/hatalar/fail-2", ad: "11-triage-locator", baslik: /^Triage sonucu$/ },
  { yol: "/hatalar/fail-1", ad: "12-triage-defect", baslik: /^Triage sonucu$/ },
  { yol: "/bug-taslaklari", ad: "13-bug-taslaklari", baslik: /^Bug taslakları$/ },
  { yol: "/bug-taslaklari/bug-1", ad: "14-bug-taslak-detay", baslik: /7 adet Portakal Gazozu/ },
  { yol: "/kontrol-kulesi", ad: "15-kontrol-kulesi", baslik: /^Kontrol Kulesi$/ },
  { yol: "/denetim", ad: "16-denetim", baslik: /^Denetim$/ },
  { yol: "/claude-code", ad: "17-claude-code", baslik: /^Claude Code kanalı$/ },
  { yol: "/hatalar/fail-4", ad: "40-triage-c3-defect", baslik: /^Triage sonucu$/ },
  { yol: "/hatalar/fail-3", ad: "41-triage-ortam", baslik: /^Triage sonucu$/ },
  { yol: "/bug-taslaklari/bug-4", ad: "42-bug-c3-taslak", baslik: /6 adet Portakal Gazozu/ },
  { yol: "/bug-taslaklari/bug-3", ad: "43-bug-f2-tutarlilik", baslik: /TPD-1 AC2/ },
  { yol: "/kosular/run-109", ad: "44-kosu-ortam-hatasi", baslik: /run-109/ },
  { yol: "/yol-haritasi", ad: "52-yol-haritasi", baslik: /^Demo yol haritası$/ },
];

test("giriş ekranı", async ({ page }) => {
  const hatalar = konsolHatalariniTopla(page);
  await page.goto("/gereksinimler");
  await expect(page).toHaveURL(/\/giris$/);
  await expect(page.getByRole("heading", { name: "Oturum aç" })).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/00-giris.png`, fullPage: true });
  expect(hatalar).toEqual([]);
});

test("analist tüm rotaları gezer (ekran görüntüleri)", async ({ page }) => {
  const hatalar = konsolHatalariniTopla(page);
  await girisYap(page, "analist");
  await expect(page.getByText("ÖRNEK VERİ", { exact: true })).toBeVisible();
  // Örnek veri derlemesinde her ekranın üstünde tam genişlik "gerçek değil" bandı.
  await expect(page.getByTestId("ornek-veri-bandi")).toContainText("ÖRNEK VERİ — gerçek değil");
  for (const r of ROTALAR) {
    await page.goto(r.yol);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(r.baslik);
    await expect(page.getByRole("status").filter({ hasText: "Yükleniyor" })).toHaveCount(0);
    await page.screenshot({ path: `${EKRAN_DIZINI}/${r.ad}.png`, fullPage: true });
  }
  expect(hatalar).toEqual([]);
});

test("insan kapıları uçtan uca: bulgu kararı → düzeltme → PO teyidi", async ({ page }) => {
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-ft-1");
  const bulgular = page.getByRole("article");
  // Serbest metin golden'ı (SERBEST): 3 engelleyici bulgu, REPLAY etiketli; tur sayacı görünür.
  await expect(bulgular).toHaveCount(3);
  await expect(page.getByText("REPLAY", { exact: true }).first()).toBeVisible();
  await expect(page.getByTestId("bulgu-sayaclari")).toContainText("Kontrol turu 1/3");

  const ilk = bulgular.nth(0);
  await ilk.getByLabel("Dokümanı düzelt").check();
  await expect(ilk.getByLabel("Önerilen değişiklik farkı").locator("ins")).toContainText("6");
  await ilk.getByRole("button", { name: "Kararı kaydet" }).click();
  await expect(ilk.getByText("Uygulanmayı bekliyor")).toBeVisible();

  const ikinci = bulgular.nth(1);
  await ikinci.getByLabel("Dokümanı düzelt").check();
  await ikinci.getByRole("button", { name: "Kararı kaydet" }).click();
  await expect(ikinci.getByText("Uygulanmayı bekliyor")).toBeVisible();

  const ucuncu = bulgular.nth(2);
  await ucuncu.getByLabel("Bilinçli fark").check();
  await ucuncu.getByRole("button", { name: "Kararı kaydet" }).click();
  await expect(ucuncu.getByRole("alert")).toContainText("gerekçe zorunludur");
  await ucuncu.getByLabel(/Gerekçe/).fill("Aynı AC3 düzeltmesi bir önceki bulguda kabul edildi");
  await ucuncu.getByRole("button", { name: "Kararı kaydet" }).click();
  await expect(ucuncu.getByText("Aynı AC3 düzeltmesi bir önceki bulguda kabul edildi")).toBeVisible();

  await expect(page.getByRole("button", { name: /Düzeltmeleri uygula \(2\) · tur 1\/3/ })).toBeEnabled();
  await page.screenshot({ path: `${EKRAN_DIZINI}/19-akis-kararlar-tur-sayaci.png`, fullPage: true });
  await page.getByRole("button", { name: /Düzeltmeleri uygula/ }).click();
  await expect(page.locator(".sayfa-basligi").getByText("PO teyidi bekliyor")).toBeVisible();
  // Serbest metinde Jira yok: düzeltme dokümana uygulanır; akışın 1. adımı "Serbest metin".
  await expect(page.getByText("Dokümana uygulandı").first()).toBeVisible();
  await expect(page.getByText("Jira'ya yazıldı")).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: /14 adımlı akış/ }).getByText("Serbest metin")).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/20-akis-po-bekliyor.png`, fullPage: true });

  await page.getByRole("button", { name: "Çıkış" }).click();
  await expect(page.getByRole("heading", { name: "Oturum aç" })).toBeVisible();
  await girisYap(page, "po");
  await expect(page.locator(".kullanici-ad")).toHaveText("po");
  await page.goto("/gereksinimler/req-ft-1");
  await page.getByRole("button", { name: "PO olarak onayla" }).click();
  await expect(page.locator(".sayfa-basligi").getByText("PO onaylı")).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/21-akis-po-onayli.png`, fullPage: true });
});

test("Demo-A: case taslağa alma, yayın (kısmi sonuç, jira-sim bağlantıları), Claude Code token'ı", async ({ page }) => {
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-tpd-1/caseler");
  const kart = (etiket: string) => page.getByRole("article").filter({ has: page.locator(".cip", { hasText: new RegExp(`^${etiket}$`) }) }).first();
  const red = kart("Reddedildi");
  // Golden C10 (C2 tekrarı) de reddedilmiş olarak gelir: biri yeniden açılınca 1 ret kalır.
  await red.getByRole("button", { name: "Yeniden aç" }).click();
  await expect(page.getByText("Reddedilen (1)")).toBeVisible();
  // Taslağa alınan case'e yeniden karar verilir (ölçüm görüntülemeden yeniden başlar).
  const taslak = page.getByRole("article").filter({ hasText: "taslağa alındı (önceki karar: ret)" });
  await expect(taslak.getByRole("button", { name: "Onayla" })).toBeEnabled();
  await taslak.getByRole("button", { name: "Onayla" }).click();
  await expect(page.getByText("Reddedilen (1)")).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/26-case-taslaga-al.png`, fullPage: true });

  await page.goto("/gereksinimler/req-tpd-1/yayin");
  await expect(page.getByTestId("yayin-hedefi")).toContainText("Jira (Test issue) · proje TPD");
  await expect(page.getByRole("link", { name: /TPD-9/ })).toHaveAttribute("href", "http://127.0.0.1:8090/browse/TPD-9");
  await page.getByRole("button", { name: /Seçilenleri yayınla/ }).click();
  await expect(page.getByTestId("yayin-ozeti")).toContainText("oluşturuldu");
  await expect(page.getByTestId("yayin-ozeti").locator("..").getByRole("link").first()).toHaveAttribute("href", /^http:\/\/127\.0\.0\.1:8090\/browse\/TPD-\d+$/);
  await page.screenshot({ path: `${EKRAN_DIZINI}/27-yayin-sonucu.png`, fullPage: true });

  await page.goto("/claude-code");
  await page.getByRole("button", { name: "8 saatlik token oluştur" }).click();
  await expect(page.getByLabel(".mcp.json (ortam değişkeniyle)")).toContainText("${TP_MCP_TOKEN}");
  await expect(page.getByRole("region", { name: "Token listesi" }).getByText("Etkin")).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/28-claude-code-token.png`, fullPage: true });
});

test("case kararları durum makinesine uyar: reddedilen onaylanamaz, onaylı reddedilemez", async ({ page }) => {
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-tpd-1/caseler");
  const kart = (etiket: string) => page.getByRole("article").filter({ has: page.locator(".cip", { hasText: new RegExp(`^${etiket}$`) }) }).first();
  const red = kart("Reddedildi");
  await expect(red).toBeVisible();
  // Karar verilmiş case'te karar düğmeleri hiç gösterilmez (pasif düğme yerine kilit notu + "Yeniden aç").
  await expect(red.getByTestId("case-karar-kilit")).toBeVisible();
  for (const ad of ["Onayla", "Düzelt", "Reddet"]) await expect(red.getByRole("button", { name: ad })).toHaveCount(0);
  // Karar değiştirmenin tek yolu taslağa almaktır (yeniden review).
  await expect(red.getByRole("button", { name: "Yeniden aç" })).toBeEnabled();
  const onayli = kart("Onaylı");
  await expect(onayli.getByTestId("case-karar-kilit")).toBeVisible();
  for (const ad of ["Onayla", "Düzelt", "Reddet"]) await expect(onayli.getByRole("button", { name: ad })).toHaveCount(0);
  // Taslak case'te kararlar açık ve çalışır.
  const taslak = kart("Karar bekliyor");
  await expect(taslak.getByRole("button", { name: "Onayla" })).toBeEnabled();
  await page.screenshot({ path: `${EKRAN_DIZINI}/24-case-karar-kilidi.png`, fullPage: true });
});

test("TPD-3: seed metni, golden soruları ve golden uyarı bulgusu görünür ('Bulgu yok' değil)", async ({ page }) => {
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-tpd-3");
  await expect(page.getByText("Bayi katalogda ürün adının bir bölümünü yazdığında yalnızca eşleşen ürünler listelenir.").first()).toBeVisible();
  await expect(page.getByText(/Aramanın başlaması için en az kaç karakter girilmeli/)).toBeVisible();
  await expect(page.getByText("api/src/demoapp_api/main.py:331")).toBeVisible();
  await expect(page.getByText("Bulgu yok: doküman kod ve veriyle tutarlı.")).toHaveCount(0);
  await page.screenshot({ path: `${EKRAN_DIZINI}/25-tpd3-golden.png`, fullPage: true });
});

test("mühendis: kod üretimi canlı adımlar ve kırarak doğrulama", async ({ page }) => {
  const hatalar = konsolHatalariniTopla(page);
  await girisYap(page, "muhendis");
  // Rol bazlı açılış: mühendis → Kod üretimi.
  await expect(page).toHaveURL(/\/kod$/);
  await page.getByRole("checkbox", { name: /Kampanyasız siparişte minimum tutarın altında/ }).check();
  await page.getByRole("button", { name: /Seçilenler için kod üret/ }).click();
  await page.getByRole("link", { name: /Kampanyasız siparişte minimum tutarın altında/ }).first().click();
  await expect(page.getByText("Ajan çalışıyor…")).toBeVisible();
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${EKRAN_DIZINI}/22-kod-uretimi-canli.png`, fullPage: true });
  // Golden'lı case: adımlar doğrulanır, eşleme + şablon, yerel kontrol yeşil → PR (LocalForge, local-ci).
  await expect(page.getByRole("list", { name: "PR check'leri" })).toContainText("local-ci", { timeout: 20_000 });
  await expect(page.getByRole("region", { name: "Eşlenen adımlar tablosu" })).toContainText('CartPage.expectMinOrderWarning("Minimum sipariş tutarı 750,00 TL")');
  // Kırma yapılmadı: kapı değil, açık kabul isteyen uyarı (TEKNIK-TASARIM §2 adım 6).
  await expect(page.getByTestId("merge-kapisi")).toContainText("açık ✓");
  await expect(page.getByTestId("merge-uyarilari")).toContainText("Kırarak doğrulama yapılmadı");
  await expect(page.getByRole("button", { name: "Merge et" })).toBeDisabled();
  await page.getByRole("checkbox", { name: /kırarak doğrulama kanıtı olmadan merge et/ }).check();
  await expect(page.getByRole("button", { name: "Merge et" })).toBeEnabled();
  await page.getByRole("checkbox", { name: /kırarak doğrulama kanıtı olmadan merge et/ }).uncheck();
  await page.screenshot({ path: `${EKRAN_DIZINI}/24-kod-pr-acik.png`, fullPage: true });

  // Defect adayı: assertion kırmızı, PR yok, insana düştü.
  await page.goto("/kod/scr-3");
  await expect(page.getByTestId("yerel-sinif")).toContainText("Defect adayı");
  await expect(page.getByText("PR açılmadı: defect adayı insana düştü.")).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/25-kod-defect-adayi.png`, fullPage: true });

  await page.goto("/kod/scr-2");
  await page.getByRole("button", { name: "Yeniden doğrula" }).click();
  await expect(page.getByText("Koşuyor").first()).toBeVisible();
  await expect(page.getByText("Test hata yakalıyor ✓")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("merge-kapisi")).toContainText("açık ✓");
  await page.getByRole("button", { name: "Merge et" }).click();
  await expect(page.getByText("Birleşti")).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/23-kirarak-dogrula-merge.png`, fullPage: true });
  expect(hatalar).toEqual([]);
});

test("sunucu: açılış Demo yol haritası; Kontrol Kulesi (KPI kaynağı), koşu süzgeci ve deploy tetiği", async ({ page }) => {
  const hatalar = konsolHatalariniTopla(page);
  await girisYap(page, "sunucu");
  await expect(page).toHaveURL(/\/yol-haritasi$/);
  await expect(page.getByRole("list", { name: "14 adımlı demo akışı" }).getByRole("listitem")).toHaveCount(14);
  await page.goto("/kontrol-kulesi");
  await expect(page.getByRole("img", { name: /^Kaynak: run tablosu|^Kaynak: test_result/ }).first()).toBeVisible();
  await page.getByRole("img", { name: /^Kaynak: test_result \(JUnit XML\)/ }).first().focus();
  await expect(page.getByText("ölçülmüş baz yok")).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/26-kontrol-kulesi-kaynak.png`, fullPage: true });
  await page.goto("/kosular");
  await page.getByRole("combobox", { name: "Tetik" }).selectOption("break_verify");
  await expect(page).toHaveURL(/tetik=break_verify/);
  await page.getByRole("button", { name: "Deploy sonrası testleri koş" }).click();
  await expect(page.getByText(/Deploy koşusu sıraya alındı/).first()).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/27-kosular-suzgec.png`, fullPage: true });
  await page.goto("/kosular/run-108");
  await expect(page.getByRole("region", { name: "Raporlar ve bağlantılar" })).toContainText("Playwright HTML raporu");
  await page.screenshot({ path: `${EKRAN_DIZINI}/28-kosu-yerel-kontrol.png`, fullPage: true });
  expect(hatalar).toEqual([]);
});

test("mobil görünüm ve koyu tema", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ colorScheme: "dark" });
  await girisYap(page, "sunucu");
  await page.goto("/kontrol-kulesi");
  await expect(page.getByRole("heading", { name: "Kontrol Kulesi", level: 1 })).toBeVisible();
  const tasanlar = await page.evaluate(() =>
    [...document.querySelectorAll("body *")]
      .filter((e) => e.getBoundingClientRect().right > window.innerWidth + 1 && !e.closest(".tablo-sarici, .yan-menu, pre, .gorunmez"))
      .map((e) => `${e.tagName}.${e.className}`),
  );
  expect(tasanlar).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: `${EKRAN_DIZINI}/30-mobil-koyu-kontrol-kulesi.png`, fullPage: true });
  await page.getByRole("button", { name: "Menü" }).click();
  await expect(page.getByRole("link", { name: "Koşular" })).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/31-mobil-menu.png` });
});

test("hiçbir rolde ölü iç bağlantı yok (her href bir ekrana çıkar)", async ({ page }) => {
  test.setTimeout(180_000);
  for (const rol of ["analist", "muhendis", "sunucu", "po", "testci"]) {
    await girisYap(page, rol);
    const hrefler = new Set<string>();
    for (const r of ROTALAR) {
      await page.goto(r.yol);
      // Rol yetkisi olmayan ekran (ör. Claude Code kanalı) başlık yerine yetki mesajı gösterir.
      await expect(page.getByRole("heading", { level: 1 }).or(page.getByText("Bu ekran için yetkiniz yok."))).toBeVisible();
      await expect(page.getByRole("status").filter({ hasText: "Yükleniyor" })).toHaveCount(0);
      for (const h of await page.locator("a[href]").evaluateAll((as) => as.map((a) => a.getAttribute("href") ?? ""))) {
        if (h.startsWith("/")) hrefler.add(h);
      }
    }
    // Artifact/forge sunucusu yok: bu yollara bağlantı üretilmemeli.
    expect([...hrefler].filter((h) => /^\/(forge|artifacts)\//.test(h))).toEqual([]);
    for (const h of hrefler) {
      await page.goto(h);
      await expect(page.getByRole("heading", { name: "Sayfa bulunamadı", level: 1 }), `${rol}: ${h}`).toHaveCount(0);
      await expect(page.getByRole("heading", { level: 1 }).or(page.getByText("Bu ekran için yetkiniz yok.")), `${rol}: ${h}`).toBeVisible();
    }
    await page.getByRole("button", { name: "Çıkış" }).click();
    await expect(page.getByRole("heading", { name: "Oturum aç" })).toBeVisible();
  }
});

test("mobil gereksinim detayı: kanıt blokları yatay taşmaz", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-tpd-1");
  await expect(page.getByText("api/src/demoapp_api/pricing.py:97").first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  const tasanlar = await page.evaluate(() =>
    [...document.querySelectorAll(".kanit, .kanit-baslik, .kanit-baslik *")]
      .filter((e) => e.getBoundingClientRect().right > window.innerWidth + 1)
      .map((e) => `${e.tagName}.${e.className}`),
  );
  expect(tasanlar).toEqual([]);
  await page.screenshot({ path: `${EKRAN_DIZINI}/32-mobil-gereksinim-kanit.png`, fullPage: true });
});

test("mobil tablolar kart görünümünde: sütun kırpılmaz, adım metni dar sütuna sıkışmaz", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await girisYap(page, "analist");
  await page.goto("/gereksinimler");
  const satir = page.locator(".tablo-yigin tbody tr").first();
  await expect(satir).toBeVisible();
  // Her hücre görünür ve ekran içinde (yatay kaydırma gerekmez).
  const hucreler = await page.evaluate(() =>
    [...document.querySelectorAll(".tablo-yigin tbody td")].map((td) => {
      const r = td.getBoundingClientRect();
      return { etiket: td.getAttribute("data-etiket"), sag: r.right, gen: r.width };
    }),
  );
  expect(hucreler.length).toBeGreaterThan(0);
  expect(hucreler.filter((h) => h.sag > 391 || h.gen < 1)).toEqual([]);
  expect(new Set(hucreler.map((h) => h.etiket))).toEqual(new Set(["Anahtar", "Başlık", "Durum", "Adım", "PO", "Açık bulgu", "Case (onaylı)", "Çekim"]));
  await page.screenshot({ path: `${EKRAN_DIZINI}/33-mobil-gereksinim-listesi.png`, fullPage: true });

  await page.goto("/gereksinimler/req-tpd-1/caseler");
  await expect(page.locator(".tablo-yigin").first()).toBeVisible();
  const adimGenislik = await page.evaluate(() =>
    Math.min(...[...document.querySelectorAll('.tablo-yigin td[data-etiket="Adım"]')].map((td) => td.getBoundingClientRect().width)),
  );
  expect(adimGenislik).toBeGreaterThan(250);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: `${EKRAN_DIZINI}/34-mobil-case-adimlari.png`, fullPage: true });
});

for (const tema of ["light", "dark"] as const) {
  test(`erişilebilirlik (axe, WCAG 2 AA) — ${tema} tema`, async ({ page }) => {
    test.setTimeout(120_000);
    await page.emulateMedia({ colorScheme: tema });
    await girisYap(page, "analist");
    // Her sayfa için içeriğin (ayrı istekle gelen bölümler dahil) yüklendiğini gösteren metin.
    const sayfalar: [string, string][] = [
      ["/gereksinimler/req-tpd-1", "api/src/demoapp_api/pricing.py:94"],
      ["/gereksinimler/req-tpd-1/caseler", "5 adet kampanyalı üründe bedava ürün verilmez"],
      ["/kod/scr-2", "c2-kampanya-7-adet-1-bedava.spec.ts"],
      ["/denetim", "Zincir doğrulandı"],
      ["/kontrol-kulesi", "Karne (story ve uygulama alanı)"],
      ["/gereksinimler/req-ft-1", "Kontrol turu"],
      ["/gereksinimler/req-tpd-1/yayin", "Oluşturulacak kayıtlar"],
      ["/claude-code", "Token oluştur"],
      ["/hatalar/fail-2", "Locator yoklaması (locator-probe)"],
      ["/bug-taslaklari/bug-4", "Olası mükerrerler"],
      ["/yol-haritasi", "Test bakımı yolu"],
    ];
    const ihlaller: string[] = [];
    for (const genislik of [1440, 390]) {
      await page.setViewportSize({ width: genislik, height: 900 });
      for (const [yol, hazir] of sayfalar) {
        await page.goto(yol);
        await expect(page.getByText(hazir).first()).toBeVisible();
        await expect(page.getByRole("status").filter({ hasText: "Yükleniyor" })).toHaveCount(0);
        const sonuc = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
        for (const v of sonuc.violations.filter((x) => x.impact === "serious" || x.impact === "critical")) {
          ihlaller.push(`${genislik}px ${yol}: ${v.id} → ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`);
        }
      }
    }
    expect(ihlaller).toEqual([]);
  });
}

test("mobil (375 px) yayın önizleme ve akış göstergesi: sayfa yatay kaymaz, adım adları çakışmaz", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-tpd-1/yayin");
  await expect(page.getByTestId("yayin-hedefi")).toBeVisible();
  await expect(page.locator(".tablo-sarici table")).toBeVisible();
  // Tablo kendi kabında kayar; görsel gizli metinler dahil hiçbir şey sayfayı genişletmez.
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: `${EKRAN_DIZINI}/35-mobil-yayin.png`, fullPage: true });

  await page.goto("/gereksinimler/req-tpd-1");
  await expect(page.locator(".akis-ad").first()).toBeVisible();
  const cakisanlar = await page.evaluate(() => {
    const kutular = [...document.querySelectorAll(".akis-ad")].map((e) => ({ m: e.textContent, r: e.getBoundingClientRect() }));
    const sonuc: string[] = [];
    for (let i = 0; i < kutular.length; i++)
      for (let j = i + 1; j < kutular.length; j++) {
        const a = kutular[i].r;
        const b = kutular[j].r;
        if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) sonuc.push(`${kutular[i].m} ↔ ${kutular[j].m}`);
      }
    return sonuc;
  });
  expect(cakisanlar).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
});

test("bilinmeyen sayfa: h1 başlığı var (axe page-has-heading-one)", async ({ page }) => {
  await girisYap(page, "analist");
  await page.goto("/yok-boyle");
  await expect(page.getByRole("heading", { name: "Sayfa bulunamadı", level: 1 })).toBeVisible();
  const sonuc = await new AxeBuilder({ page }).withRules(["page-has-heading-one"]).analyze();
  expect(sonuc.violations.map((v) => v.id)).toEqual([]);
});

// ---------------------------------------------------------------- Faz 4

test("Faz 4 locator yolu: sunucu kırar → CI kırmızı → triage → mühendis onarım PR'ı → merge", async ({ page }) => {
  test.setTimeout(120_000);
  const hatalar = konsolHatalariniTopla(page);
  await girisYap(page, "sunucu");
  await page.getByRole("link", { name: "Demo kontrolleri" }).click();
  await expect(page.getByRole("heading", { name: "Demo kontrolleri", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Buton kimliğini değiştir" }).click();
  await expect(page.getByRole("group", { name: "Buton kimliği değiştirme onayı" })).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/45-demo-kir-onay.png`, fullPage: true });
  await page.getByRole("button", { name: "Evet, buton kimliğini değiştir" }).click();
  const ilerleme = page.getByRole("list", { name: "Locator kırılması ilerlemesi" });
  await expect(ilerleme.getByRole("link", { name: "onarım önerisini aç" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("list", { name: "Demo olay günlüğü" })).toContainText("demo-admin bypass");
  await page.screenshot({ path: `${EKRAN_DIZINI}/46-demo-kir-ilerleme.png`, fullPage: true });
  await page.getByRole("button", { name: "Çıkış" }).click();
  await expect(page.getByRole("heading", { name: "Oturum aç" })).toBeVisible();

  await girisYap(page, "muhendis");
  await page.goto("/hatalar/fail-2");
  await expect(page.getByTestId("triage-sinif")).toContainText("Karar kaynağı: kural");
  await expect(page.getByRole("region", { name: "Locator yoklaması (locator-probe)" })).toContainText("commit eşleşiyor");
  await page.screenshot({ path: `${EKRAN_DIZINI}/47-triage-locator-oneri.png`, fullPage: true });
  await page.getByRole("button", { name: "Onarım PR'ı aç" }).click();
  const merge = page.getByRole("button", { name: "Onarımı onayla ve merge et" });
  await expect(merge).toBeEnabled({ timeout: 30_000 });
  await expect(page.getByRole("list", { name: "Onarım hattı" })).toContainText("3/3 geçti");
  await page.screenshot({ path: `${EKRAN_DIZINI}/48-onarim-pr-acik.png`, fullPage: true });
  await merge.click();
  await expect(page.getByText(/Onarım birleşti/)).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/49-onarim-birlesti.png`, fullPage: true });
  expect(hatalar).toEqual([]);
});

test("Faz 4 bug yolu: C3 defect → triage → TPD-5 mükerrer → testçi bağlar → Jira bağlantısı", async ({ page }) => {
  const hatalar = konsolHatalariniTopla(page);
  await girisYap(page, "muhendis");
  await page.goto("/kod/scr-3");
  await expect(page.getByRole("button", { name: "Kırarak doğrula" })).toBeDisabled();
  await page.getByRole("link", { name: "Triage sonucu ve bug taslağı" }).click();
  await expect(page.getByTestId("triage-sinif")).toContainText("Ürün hatası");
  await page.getByRole("button", { name: "Çıkış" }).click();
  await expect(page.getByRole("heading", { name: "Oturum aç" })).toBeVisible();

  await girisYap(page, "testci");
  await page.goto("/hatalar/fail-4");
  await page.getByRole("link", { name: "Bug taslağına git" }).click();
  const aday = page.getByRole("list", { name: "Mükerrer adayları" }).getByRole("listitem").first();
  await expect(aday).toContainText("yüksek olasılık");
  await expect(aday).toContainText("AI gerekçesi");
  await expect(page.getByText("canlı değerlendirme bekliyor").first()).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/50-bug-mukerrer-tpd5.png`, fullPage: true });
  await aday.getByRole("button", { name: "TPD-5 kaydına bağla" }).click();
  const sonuc = page.getByTestId("yayin-sonucu");
  await expect(sonuc).toContainText("kaydına bağlandı");
  await expect(sonuc.getByRole("link")).toHaveAttribute("href", /\/browse\/TPD-5$/);
  await page.screenshot({ path: `${EKRAN_DIZINI}/51-bug-baglandi.png`, fullPage: true });
  expect(hatalar).toEqual([]);
});

test("Faz 5: analist TPD-1'e ölçülmüş baz değer girer → Kontrol Kulesi kazancı yalnız o story'den; yol haritası", async ({ page }) => {
  const hatalar = konsolHatalariniTopla(page);
  await girisYap(page, "analist");
  // Ölçüm girilmeden önce case review özeti kazanç göstermez (baz değer uydurulmaz).
  await page.goto("/gereksinimler/req-tpd-1/caseler");
  await expect(page.getByTestId("case-baz")).toContainText("Ölçülmedi");
  await expect(page.getByTestId("case-kazanc")).toHaveText("—");
  await expect(page.getByText(/F0 ölçümü/)).toHaveCount(0);
  await page.goto("/gereksinimler/req-tpd-1");
  const kart = page.getByRole("region", { name: "Manuel baz değer" });
  await expect(kart.getByText("Ölçülmedi", { exact: true })).toBeVisible();
  await kart.getByRole("button", { name: "Ölçüm gir" }).click();
  await kart.getByLabel("Dakika").fill("45");
  await kart.getByRole("button", { name: "Kaydet" }).click();
  await expect(kart.getByRole("alert")).toContainText("Ölçüm notu gerekli");
  await kart.getByLabel("Ölçüm notu (kim, nasıl ölçtü)").fill("İsmail, F0 haftası, kronometre");
  await kart.getByRole("checkbox").check();
  await kart.screenshot({ path: `${EKRAN_DIZINI}/53-baz-deger-formu.png` });
  await kart.getByRole("button", { name: "Kaydet" }).click();
  await expect(kart.getByTestId("baz-deger-sure")).toHaveText("45 dk 00 sn");
  await expect(kart.getByText("Ölçüm", { exact: true })).toBeVisible();
  await kart.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${EKRAN_DIZINI}/54-baz-deger-olcum.png`, fullPage: true });
  // Case review özeti: baz değer "Ölçüm" etiketli, girenin adıyla.
  await page.goto("/gereksinimler/req-tpd-1/caseler");
  await expect(page.getByTestId("case-baz")).toContainText("45 dk 00 sn");
  await expect(page.getByTestId("case-baz")).toContainText("Ölçüm");
  await expect(page.getByTestId("case-baz-aciklama")).toContainText("ölçüm · analist");
  await page.getByRole("button", { name: "Çıkış" }).click();

  await girisYap(page, "sunucu");
  await page.goto("/kontrol-kulesi");
  // Örnek veri REPLAY: ölçüm girilse de başlık yüzdesi yok (yalnız review; verimlilik iddiası değil).
  await expect(page.getByTestId("hazirlik-kazanci")).toHaveText("REPLAY: hesaplanmaz");
  await expect(page.getByTestId("kazanc-kapsam")).toContainText("Kazanç hesaplanmaz (REPLAY)");
  await expect(page.getByTestId("hazirlik-TPD-1")).toContainText("REPLAY: yalnız review");
  await expect(page.getByTestId("hazirlik-TPD-1")).toContainText("Ölçüm");
  await page.getByRole("heading", { name: "Hazırlık süresi (story bazında)" }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${EKRAN_DIZINI}/55-kontrol-kulesi-kazanc.png`, fullPage: true });

  await page.goto("/yol-haritasi");
  await expect(page.getByTestId("yh-mod")).toContainText("REPLAY");
  await expect(page.getByTestId("yh-adim-1")).toHaveAttribute("data-hal", "tamam");
  await page.screenshot({ path: `${EKRAN_DIZINI}/52-yol-haritasi.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByRole("list", { name: "14 adımlı demo akışı" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: `${EKRAN_DIZINI}/56-mobil-yol-haritasi.png`, fullPage: true });
  expect(hatalar).toEqual([]);
});
