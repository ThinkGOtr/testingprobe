import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, readFileSync } from "node:fs";

const EKRAN_DIZINI = "e2e/ekranlar";
const ACIK_EKRAN_DIZINI = `${EKRAN_DIZINI}/acik`;
mkdirSync(ACIK_EKRAN_DIZINI, { recursive: true });

/** Web fontları yüklenene dek bekler: boyut/taşma ölçümleri ve ekran görüntüleri yedek fontla alınmasın. */
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

/** Akış göstergesinde kutuları üst üste binen adım adı çiftleri (1 px tolerans). */
async function akisAdCakismalari(page: Page): Promise<string[]> {
  return page.evaluate(() => {
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

test("Case review: Case filtresi sekmeleri ≥641 px'te üst çubuğun altında yapışık, ≤640 px'te akışta", async ({ page }) => {
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-tpd-1/caseler");
  const sekmeler = page.getByRole("group", { name: "Case filtresi" });
  await expect(sekmeler).toHaveCSS("position", "sticky");
  await expect(sekmeler).toHaveCSS("top", "56px");
  // Aşağı kaydırınca şerit üst çubuğun (56 px) hemen altında kalır.
  await expect(page.getByRole("article").first()).toBeVisible();
  await expect
    .poll(async () => {
      await page.evaluate(() => window.scrollTo(0, 1500));
      return Math.round((await sekmeler.boundingBox())!.y);
    })
    .toBe(56);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(sekmeler).toHaveCSS("position", "static");
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
  // İşletim sistemi açık temada olsa da varsayılan koyudur (tema seçilmemiş, depolama boş).
  await page.emulateMedia({ colorScheme: "light" });
  await girisYap(page, "sunucu");
  await page.goto("/kontrol-kulesi");
  await expect(page.getByRole("heading", { name: "Kontrol Kulesi", level: 1 })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await fontlariBekle(page);
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

test("mobil menü kapalıyken Tab sırasına girmez (dikey ve yatay telefon); menüden gezinince odak içeriğe geçer", async ({ page }) => {
  // jsdom CSS görmediği için kapalı menünün Tab dışlaması (visibility + overflow) yalnız burada sınanır.
  await girisYap(page, "sunucu");
  for (const [genislik, yukseklik] of [
    [390, 844],
    [844, 390],
  ] as const) {
    await page.setViewportSize({ width: genislik, height: yukseklik });
    await page.goto("/kosular");
    await expect(page.getByRole("heading", { name: "Koşular", level: 1 })).toBeVisible();
    const menu = page.locator("#yan-menu");
    const menuDugmesi = page.getByRole("button", { name: "Menü" });
    await expect(menu.getByRole("link", { name: "Denetim" })).toBeHidden();
    const menudeOdak = () => page.evaluate(() => !!document.activeElement?.closest("#yan-menu"));
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press("Tab");
      expect(await menudeOdak(), `${genislik}×${yukseklik} Tab ${i + 1}`).toBe(false);
    }
    // Kipsel menüde yüzen asistan başlatıcısı perdenin üstünde görünmez ve inert'tir; menü kapanınca geri gelir.
    // (Başlatıcı asistan durumu okununca çizilir: menü ondan önce açılırsa inert listesine giremez.)
    const baslatici = page.getByRole("button", { name: "Asistanı aç", exact: true });
    await expect(baslatici).toBeVisible();
    await menuDugmesi.click();
    await expect(menu.getByRole("link", { name: "Denetim" })).toBeVisible();
    await expect(baslatici).toBeHidden();
    expect(await page.locator(".asistan-baslatici").evaluate((e) => (e as HTMLElement).inert)).toBe(true);
    await page.keyboard.press("Escape");
    await expect(menuDugmesi).toBeFocused();
    await expect(menu.getByRole("link", { name: "Denetim" })).toBeHidden();
    await expect(baslatici).toBeVisible();
    // Açık menü kipsel (WCAG 2.4.11): açılışta odak ilk bağlantıda; Tab / Shift+Tab yalnız menü ile menü
    // düğmesi arasında dolaşır, menünün altında kalan içeriğe geçmez.
    await page.keyboard.press("Enter");
    await expect(menuDugmesi).toHaveAttribute("aria-expanded", "true");
    await expect(menu.getByRole("link").first()).toBeFocused();
    const odakYeri = () =>
      page.evaluate(() => {
        const e = document.activeElement;
        return e?.closest("#yan-menu") ? "menu" : e?.classList.contains("menu-dugmesi") ? "dugme" : `${e?.tagName}.${e?.className}`;
      });
    for (const tus of ["Tab", "Shift+Tab"]) {
      const yerler = new Set<string>();
      for (let i = 0; i < 14; i++) {
        await page.keyboard.press(tus);
        const yer = await odakYeri();
        expect(["menu", "dugme"], `${genislik}×${yukseklik} açık menü ${tus} ${i + 1}: ${yer}`).toContain(yer);
        yerler.add(yer);
      }
      expect([...yerler].sort(), `${genislik}×${yukseklik} ${tus} döngüsü`).toEqual(["dugme", "menu"]);
    }
    await expect(menuDugmesi).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Escape");
    await expect(menuDugmesi).toBeFocused();
    // Perdeye (menünün sağındaki karartılmış içerik) dokunmak menüyü kapatır; odak menü düğmesine döner.
    await menuDugmesi.click();
    await expect(menu.getByRole("link", { name: "Denetim" })).toBeVisible();
    await page.mouse.click(genislik - 10, yukseklik - 20);
    await expect(menuDugmesi).toHaveAttribute("aria-expanded", "false");
    await expect(menuDugmesi).toBeFocused();
    await expect(menu.getByRole("link", { name: "Denetim" })).toBeHidden();
    await expect(page.locator("#ana-icerik")).not.toHaveAttribute("inert", "");
    await menuDugmesi.click();
    await menu.getByRole("link", { name: "Denetim" }).click();
    await expect(page.getByRole("heading", { name: "Denetim", level: 1 })).toBeVisible();
    await expect(menuDugmesi).toHaveAttribute("aria-expanded", "false");
    await expect(page.locator("#ana-icerik")).toBeFocused();
  }
});

test("320–480 px üst çubuk: \"Probe\" markası rozet sayılı Öneri düğmesi ve ÖRNEK VERİ ile de kesilmez", async ({ page }) => {
  // En dolu üst çubuk: Öneri düğmesi rozetli (bekleyen iş 1) + ÖRNEK VERİ + bağlantı + tema + Çıkış.
  await page.setViewportSize({ width: 320, height: 640 });
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-ft-1");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByTestId("oneri-dugmesi").locator(".oneri-rozet")).toHaveText("1");
  await expect(page.locator(".ust-sag > .rozet-mock")).toBeVisible();
  await fontlariBekle(page);
  for (const genislik of [320, 340, 360, 390, 440, 480]) {
    await page.setViewportSize({ width: genislik, height: 640 });
    const olcu = await page.evaluate(() => {
      const kap = document.querySelector(".ust-cubuk .marka > span:last-child")!;
      return {
        tasma: kap.scrollWidth - kap.clientWidth,
        sag: document.querySelector(".ust-cubuk .marka strong")!.getBoundingClientRect().right,
        kapSag: kap.getBoundingClientRect().right,
        sayfa: document.documentElement.scrollWidth,
      };
    });
    expect(olcu.tasma, `${genislik}px marka taşması`).toBeLessThanOrEqual(0);
    expect(olcu.sag, `${genislik}px "Probe"`).toBeLessThanOrEqual(olcu.kapSag + 0.5);
    expect(olcu.sayfa, `${genislik}px yatay kaydırma`).toBeLessThanOrEqual(genislik);
  }
  // Öneri düğmesinin görünüp kaybolması sağ grubu kaydırmaz: düğme grubun en solunda.
  await page.setViewportSize({ width: 1440, height: 900 });
  const solKenar = () => page.locator(".ust-sag > .rozet-mock").evaluate((e) => e.getBoundingClientRect().left);
  const oneriliSol = await solKenar();
  await page.goto("/kod/scr-2");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByTestId("oneri-dugmesi")).toHaveCount(0);
  expect(await solKenar()).toBe(oneriliSol);
});

test("ilk boyama kayıtlı temada: açık/sistem seçen kullanıcı paket gelmeden koyu görmez", async ({ page }) => {
  // Uygulama paketi geciktirilir: tema yalnız tema-on.js'ten (head'deki klasik betik) gelebilir.
  await page.route(/\/assets\/index-[\w-]+\.js$/, async (r) => {
    await new Promise((z) => setTimeout(z, 1500));
    await r.continue();
  });
  await page.emulateMedia({ colorScheme: "light" });
  for (const [tema, beklenen] of [
    ["acik", "light"],
    ["sistem", null],
    ["koyu", "dark"],
  ] as const) {
    await page.addInitScript((t) => {
      localStorage.setItem("tp-tema-v", "2");
      localStorage.setItem("tp-tema", t);
    }, tema);
    await page.goto("/giris", { waitUntil: "commit" });
    await expect.poll(() => page.evaluate(() => document.body !== null)).toBe(true);
    // Paket henüz çalışmadı (kök boş) ama tema uygulanmış.
    expect(await page.evaluate(() => document.getElementById("root")?.childElementCount ?? -1)).toBe(0);
    expect(await page.evaluate(() => document.documentElement.getAttribute("data-theme"))).toBe(beklenen);
    expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe(tema === "koyu" ? "dark" : "light");
  }
});

test("CSP: önizleme nginx.conf başlığını gönderir; ekranlarda CSP ihlali yok", async ({ page }) => {
  const nginxCsp = /add_header\s+Content-Security-Policy\s+"([^"]+)"/.exec(readFileSync("nginx.conf", "utf8"))?.[1];
  expect(nginxCsp).toBeTruthy();
  const ihlaller: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" && /Content Security Policy/i.test(m.text())) ihlaller.push(m.text());
  });
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) => console.error(`Content Security Policy ihlali: ${e.violatedDirective} ${e.blockedURI}`));
  });
  const yanit = await page.goto("/giris");
  expect(yanit?.headers()["content-security-policy"]).toBe(nginxCsp);
  await expect(page.getByRole("button", { name: "Giriş yap" })).toBeVisible();
  await girisYap(page, "analist");
  for (const yol of ["/gereksinimler/req-tpd-1", "/kod/scr-2", "/kosular/run-107", "/kontrol-kulesi", "/yol-haritasi", "/denetim"]) {
    await page.goto(yol);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await fontlariBekle(page);
  }
  expect(ihlaller).toEqual([]);
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
  await fontlariBekle(page);
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
  await fontlariBekle(page);
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
  await fontlariBekle(page);
  const adimGenislik = await page.evaluate(() =>
    Math.min(...[...document.querySelectorAll('.tablo-yigin td[data-etiket="Adım"]')].map((td) => td.getBoundingClientRect().width)),
  );
  expect(adimGenislik).toBeGreaterThan(250);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: `${EKRAN_DIZINI}/34-mobil-case-adimlari.png`, fullPage: true });
});

// ---------------------------------------------------------------- erişilebilirlik (axe) — tasarım planı §8

type TemaTuru = {
  tema: "koyu" | "acik" | "sistem";
  /** Beklenen hesaplanmış `color-scheme` (html). */
  colorScheme: "dark" | "light";
  /** Beklenen `html[data-theme]`; null = nitelik yok (sistem kipi). */
  dataTheme: "dark" | "light" | null;
  /** İşletim sistemi tercihi: acik/koyu turunda bilerek ters seçilir (seçilen tema OS'u ezmeli). */
  os: "dark" | "light";
  genislikler: number[];
};

const TEMA_TURLARI: TemaTuru[] = [
  { tema: "koyu", colorScheme: "dark", dataTheme: "dark", os: "light", genislikler: [1440, 390] },
  { tema: "acik", colorScheme: "light", dataTheme: "light", os: "dark", genislikler: [1440, 390] },
  { tema: "sistem", colorScheme: "light", dataTheme: null, os: "light", genislikler: [1440] },
];

/** axe sayfaları: yol, ekran görüntüsü adı (açık tema, 1440 px) ve içeriğin yüklendiğini gösteren bekleme. */
const AXE_SAYFALARI: { yol: string; ad: string; hazir: (p: Page) => Promise<void> }[] = [
  { yol: "/gereksinimler", ad: "01-gereksinimler", hazir: (p) => expect(p.getByRole("region", { name: "Gereksinimler tablosu" })).toBeVisible() },
  { yol: "/gereksinimler/req-tpd-1", ad: "02-gereksinim-tpd1", hazir: (p) => expect(p.getByText("api/src/demoapp_api/pricing.py:94").first()).toBeVisible() },
  { yol: "/gereksinimler/req-ft-1", ad: "03-gereksinim-serbest-metin", hazir: (p) => expect(p.getByText("Kontrol turu").first()).toBeVisible() },
  {
    yol: "/gereksinimler/req-tpd-1/caseler",
    ad: "05-case-review",
    hazir: (p) => expect(p.getByText("5 adet kampanyalı üründe bedava ürün verilmez").first()).toBeVisible(),
  },
  { yol: "/gereksinimler/req-tpd-1/yayin", ad: "06-yayin-onizleme", hazir: (p) => expect(p.getByText("Oluşturulacak kayıtlar").first()).toBeVisible() },
  { yol: "/kod", ad: "07-kod-uretimi", hazir: (p) => expect(p.getByRole("region", { name: "Üretilen testler tablosu" })).toBeVisible() },
  { yol: "/kod/scr-2", ad: "08-script-detay", hazir: (p) => expect(p.getByText("c2-kampanya-7-adet-1-bedava.spec.ts").first()).toBeVisible() },
  { yol: "/kosular", ad: "09-kosular", hazir: (p) => expect(p.getByRole("region", { name: "Koşular tablosu" })).toBeVisible() },
  {
    yol: "/kosular/run-107",
    ad: "10-kosu-detay-ayrinti",
    // Örnek veride (Ek B2) ilk satır başarısız C2: açılınca denemeler, adım ağacı, ekran görüntüsü eki.
    hazir: async (p) => {
      await expect(p.getByRole("region", { name: "Raporlar ve bağlantılar" })).toBeVisible();
      await p.getByRole("region", { name: "Test sonuçları tablosu" }).getByRole("button").first().click();
      await expect(p.getByRole("region", { name: /^Test ayrıntısı: / })).toBeVisible();
      await expect(p.getByRole("img", { name: /^Ekran görüntüsü: / }).first()).toBeVisible();
    },
  },
  {
    yol: "/kosular/run-108",
    ad: "28-kosu-yerel-kontrol-sauce",
    hazir: (p) => expect(p.getByText("Sauce koşmadı: oturum sınırı dolu")).toBeVisible(),
  },
  { yol: "/hatalar/fail-2", ad: "11-triage-locator", hazir: (p) => expect(p.getByText("Locator yoklaması (locator-probe)").first()).toBeVisible() },
  { yol: "/bug-taslaklari", ad: "13-bug-taslaklari", hazir: (p) => expect(p.getByRole("heading", { name: "Bug taslakları" })).toBeVisible() },
  { yol: "/bug-taslaklari/bug-4", ad: "42-bug-c3-taslak", hazir: (p) => expect(p.getByText("Olası mükerrerler").first()).toBeVisible() },
  { yol: "/kontrol-kulesi", ad: "15-kontrol-kulesi", hazir: (p) => expect(p.getByText("Karne (story ve uygulama alanı)").first()).toBeVisible() },
  { yol: "/denetim", ad: "16-denetim", hazir: (p) => expect(p.getByText("Zincir doğrulandı").first()).toBeVisible() },
  { yol: "/claude-code", ad: "17-claude-code", hazir: (p) => expect(p.getByText("Token oluştur").first()).toBeVisible() },
  { yol: "/yol-haritasi", ad: "52-yol-haritasi", hazir: (p) => expect(p.getByText("Test bakımı yolu").first()).toBeVisible() },
];

/**
 * F0 tabanı (e2e/F0-TABAN.md "Yenileme sonrası taban", Ek B2 fikstürü dahil): sayfa başına axe
 * `color-contrast` **incomplete** düğüm sayısı. Sıra: koyu 1440, koyu 390, açık 1440, açık 390, sistem 1440.
 * Tasarım değişikliği bu sayıları aşamaz (§8 sayısal kapı); azalırsa taban düşürülür.
 */
const F0_INCOMPLETE: Record<string, [number, number, number, number, number]> = {
  "/giris": [0, 0, 0, 0, 0],
  "/gereksinimler/req-tpd-1": [6, 9, 6, 9, 6],
  "/gereksinimler/req-tpd-1/caseler": [0, 0, 0, 0, 0],
  "/kod/scr-2": [8, 8, 8, 8, 8],
  "/denetim": [0, 0, 0, 0, 0],
  "/kontrol-kulesi": [2, 2, 2, 2, 2],
  "/gereksinimler/req-ft-1": [2, 3, 2, 3, 2],
  "/gereksinimler/req-tpd-1/yayin": [0, 0, 0, 0, 0],
  "/claude-code": [0, 0, 0, 0, 0],
  "/hatalar/fail-2": [11, 11, 11, 11, 11],
  "/bug-taslaklari/bug-4": [0, 0, 0, 0, 0],
  "/yol-haritasi": [8, 8, 8, 8, 8],
  "/gereksinimler": [0, 0, 0, 0, 0],
  "/kod": [0, 0, 0, 0, 0],
  "/kosular": [0, 0, 0, 0, 0],
  "/kosular/run-107": [17, 17, 17, 17, 17],
  "/kosular/run-108": [1, 1, 1, 1, 1],
  "/bug-taslaklari": [0, 0, 0, 0, 0],
  "/demo": [0, 0, 0, 0, 0],
};

function f0Taban(yol: string, tema: TemaTuru["tema"], genislik: number): number {
  const SIRA: Record<string, number> = { "koyu 1440": 0, "koyu 390": 1, "acik 1440": 2, "acik 390": 3, "sistem 1440": 4 };
  const sira = SIRA[`${tema} ${genislik}`];
  const satir = F0_INCOMPLETE[yol];
  if (!satir || sira === undefined) throw new Error(`F0 tabanı yok: ${tema} ${genislik} ${yol}`);
  return satir[sira];
}

/** Tema gerçekten uygulandı mı: hesaplanmış color-scheme ve html[data-theme] (OS tercihinden bağımsız). */
async function temaDogrula(page: Page, tur: TemaTuru) {
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe(tur.colorScheme);
  if (tur.dataTheme) await expect(page.locator("html")).toHaveAttribute("data-theme", tur.dataTheme);
  else await expect(page.locator("html")).not.toHaveAttribute("data-theme");
}

for (const tur of TEMA_TURLARI) {
  test(`erişilebilirlik (axe, WCAG 2 AA) — ${tur.tema} tema`, async ({ page }) => {
    test.setTimeout(300_000);
    // Tema emulateMedia ile değil, kullanıcının seçimiyle: her belge yüklenmeden önce depolamaya yazılır.
    await page.addInitScript((t) => {
      localStorage.setItem("tp-tema-v", "2");
      localStorage.setItem("tp-tema", t);
    }, tur.tema);
    await page.emulateMedia({ colorScheme: tur.os });
    const ihlaller: string[] = [];
    const asimlar: string[] = [];
    const sayilar: string[] = [];

    const denetle = async (yol: string, genislik: number, ad: string | null) => {
      await expect(page.getByRole("status").filter({ hasText: "Yükleniyor" })).toHaveCount(0);
      await temaDogrula(page, tur);
      await fontlariBekle(page);
      if (ad && tur.tema === "acik" && genislik === 1440) {
        await page.screenshot({ path: `${ACIK_EKRAN_DIZINI}/${ad}.png`, fullPage: true, animations: "disabled" });
      }
      // Büyük dekoratif pseudo zeminler (ortam ışıması, giriş ızgarası) kontrastı "incomplete"e düşürmesin.
      await page.addStyleTag({ content: ".kabuk::before,.giris-sayfa::before,.giris-sayfa::after{display:none}" });
      const sonuc = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
      for (const v of sonuc.violations.filter((x) => x.impact === "serious" || x.impact === "critical")) {
        ihlaller.push(`${genislik}px ${yol}: ${v.id} → ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(", ")}`);
      }
      const eksik = sonuc.incomplete.find((x) => x.id === "color-contrast")?.nodes ?? [];
      const taban = f0Taban(yol, tur.tema, genislik);
      sayilar.push(`${genislik}px ${yol}: ${eksik.length} (F0 ${taban})`);
      if (eksik.length > taban) {
        asimlar.push(`${genislik}px ${yol}: color-contrast incomplete ${eksik.length} > F0 ${taban} → ${eksik.map((n) => n.target.join(" ")).slice(0, 5).join(", ")}`);
      }
    };

    for (const genislik of tur.genislikler) {
      await page.setViewportSize({ width: genislik, height: 900 });
      // Giriş ekranı oturum açmadan önce.
      await page.goto("/giris");
      await expect(page.getByRole("button", { name: "Giriş yap" })).toBeVisible();
      await denetle("/giris", genislik, "00-giris");

      await girisYap(page, "analist");
      for (const s of AXE_SAYFALARI) {
        await page.goto(s.yol);
        await s.hazir(page);
        await denetle(s.yol, genislik, s.ad);
      }
      await page.getByRole("button", { name: "Çıkış" }).click();
      await expect(page.getByRole("heading", { name: "Oturum aç" })).toBeVisible();

      // Demo kontrolleri yalnız sunucu rolünde (App.tsx RolGerekli presenter); onay grubu açık haliyle.
      await girisYap(page, "sunucu");
      await page.goto("/demo");
      await page.getByRole("button", { name: "Buton kimliğini değiştir" }).click();
      await expect(page.getByRole("group", { name: "Buton kimliği değiştirme onayı" })).toBeVisible();
      await denetle("/demo", genislik, "45-demo-kontrolleri-onay");
      await page.getByRole("button", { name: "Çıkış" }).click();
      await expect(page.getByRole("heading", { name: "Oturum aç" })).toBeVisible();
    }
    await test.info().attach(`color-contrast incomplete (${tur.tema})`, { body: sayilar.join("\n"), contentType: "text/plain" });
    expect(ihlaller).toEqual([]);
    expect(asimlar).toEqual([]);
  });
}

test("%125 zoom eşdeğeri (1152×720): Script detayında Kırarak doğrula kartı PR kartının sağında; Triage'da onarım kartı ilk ekranda", async ({ page }) => {
  await page.setViewportSize({ width: 1152, height: 720 });
  await girisYap(page, "muhendis");
  await page.goto("/kod/scr-2");
  // Aynı adlı bir düğme de var: kart bölgesi rolüyle seçilir.
  const pr = page.getByRole("region", { name: "Pull request" });
  const kirma = page.getByRole("region", { name: "Kırarak doğrula" });
  await expect(pr).toBeVisible();
  await expect(kirma).toBeVisible();
  await fontlariBekle(page);
  const a = await pr.boundingBox();
  const b = await kirma.boundingBox();
  expect(a && b).toBeTruthy();
  // Sağında: soldan PR kartının sağ kenarından sonra başlar ve aynı satırdadır (dikey örtüşme).
  expect(b!.x).toBeGreaterThanOrEqual(a!.x + a!.width - 1);
  expect(b!.y).toBeLessThan(a!.y + a!.height);
  expect(a!.y).toBeLessThan(b!.y + b!.height);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1152);
  // PR açıkken karar kartları ilk ekranda (demo Adım 6–7 kaydırmasız).
  expect(a!.y).toBeLessThan(720);
  expect(b!.y).toBeLessThan(720);
  await page.screenshot({ path: `${EKRAN_DIZINI}/57-script-detay-1152.png`, fullPage: true });

  // Triage (§5 görsel kapı): sınıf + sinyaller + onarım kartı ve "Onarım PR'ı aç" düğmesi ilk ekranda.
  await page.goto("/hatalar/fail-2");
  const onarim = page.getByRole("region", { name: "Locator onarım önerisi" });
  await expect(onarim).toBeVisible();
  await fontlariBekle(page);
  for (const bolge of [page.getByRole("region", { name: "Sınıf", exact: true }), page.getByRole("region", { name: "Eşleşen sinyaller", exact: true }), onarim]) {
    const k = await bolge.boundingBox();
    expect(k!.y).toBeLessThan(720);
  }
  const dugme = await onarim.getByRole("button", { name: "Onarım PR'ı aç" }).boundingBox();
  expect(dugme!.y + dugme!.height).toBeLessThanOrEqual(720);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1152);
  await page.screenshot({ path: `${EKRAN_DIZINI}/58-triage-1152.png` });
});

test("%125 zoom eşdeğeri (1152×720): TPD-1 'Case üret' görünür pasiflik nedenleriyle de sağ üstte; düğme aralıkları 8 px", async ({ page }) => {
  await page.setViewportSize({ width: 1152, height: 720 });
  // Analistte iki başlık düğmesi pasif ve nedenleri görünür (.dugme-neden): nedenler grubu genişletmemeli.
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-tpd-1");
  const baslik = page.locator(".sayfa-basligi");
  const caseUret = baslik.getByRole("button", { name: "Case üret" });
  await expect(caseUret).toBeVisible();
  await expect(baslik.locator(".dugme-neden").first()).toBeVisible();
  await fontlariBekle(page);
  const h1 = (await baslik.locator("h1").boundingBox())!;
  const d = (await caseUret.boundingBox())!;
  const kap = (await baslik.boundingBox())!;
  // Sağ üst: içerik ortasının sağında ve h1 ile aynı bantta (başlığın altına inmemiş).
  expect(d.x).toBeGreaterThan(kap.x + kap.width / 2);
  expect(d.y).toBeLessThan(h1.y + h1.height);
  const kutular = await baslik.locator(".eylemler > button, .eylemler > .dugme-neden-sarici > button, .eylemler > a").evaluateAll((es) =>
    es.map((e) => e.getBoundingClientRect()).map((r) => ({ x: r.left, r: r.right, y: r.top })),
  );
  kutular.sort((a, b) => a.x - b.x);
  for (let i = 1; i < kutular.length; i++) {
    if (Math.abs(kutular[i].y - kutular[i - 1].y) < 2) expect(Math.round(kutular[i].x - kutular[i - 1].r)).toBe(8);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1152);
});

test("pasiflik nedeni yerleşimi (review 3): neden kendi düğmesinin altında, grup kenarından taşmaz; kart başlıkları hizalı; sarmış başlıkta grup sağda", async ({ page }) => {
  const kutu = async (l: import("@playwright/test").Locator) => (await l.boundingBox())!;
  /** Nedenin metin satırlarının en sol / en sağ kenarı (kutunun değil, metnin). */
  const metinKenari = (l: import("@playwright/test").Locator) =>
    l.evaluate((e) => {
      const r = document.createRange();
      r.selectNodeContents(e);
      const s = [...r.getClientRects()];
      return { sol: Math.min(...s.map((x) => x.left)), sag: Math.max(...s.map((x) => x.right)), satir: new Set(s.map((x) => Math.round(x.top))).size };
    });

  // Case review, testci, 1440: karar verilmiş case satırında neden paragrafın değil 'Yeniden aç' düğmesinin altında.
  await page.setViewportSize({ width: 1440, height: 900 });
  await girisYap(page, "testci");
  await page.goto("/gereksinimler/req-tpd-1/caseler");
  const satir = page.locator(".satir-ogeler:has(> .neden-var)").first();
  await expect(satir).toBeVisible();
  await fontlariBekle(page);
  const yenidenAc = await kutu(satir.getByRole("button", { name: "Yeniden aç" }));
  const nedenK = await kutu(satir.locator(".dugme-neden"));
  expect(nedenK.x).toBeGreaterThanOrEqual(yenidenAc.x - 1);
  expect(nedenK.y).toBeGreaterThanOrEqual(yenidenAc.y + yenidenAc.height - 1);
  // Tek düğmeli sayfa başlığında kısa neden tek satır, sağ kenarı düğmeyle aynı.
  const yayin = page.locator(".sayfa-basligi .eylemler");
  const yayinNeden = await metinKenari(yayin.locator(".dugme-neden"));
  expect(yayinNeden.satir).toBe(1);
  const yayinD = await kutu(yayin.getByRole("button", { name: "Yayın önizleme" }));
  expect(Math.abs(yayinNeden.sag - (yayinD.x + yayinD.width))).toBeLessThanOrEqual(1);

  // Script detay, testci: sola yaslı merge grubunda neden metni düğmenin sol kenarından başlar; komşu kart başlıkları aynı hizada.
  for (const g of [1440, 1152]) {
    await page.setViewportSize({ width: g, height: 900 });
    await page.goto("/kod/scr-2");
    const pr = page.getByRole("region", { name: "Pull request" });
    await expect(pr).toBeVisible();
    await fontlariBekle(page);
    const merge = pr.locator(".eylemler:has(> .neden-var)").first();
    const ilkDugme = await kutu(merge.locator("button").first());
    expect((await metinKenari(merge.locator(".dugme-neden"))).sol).toBeGreaterThanOrEqual(ilkDugme.x - 1);
    const h2a = await kutu(pr.getByRole("heading", { name: "Pull request" }));
    const h2b = await kutu(page.getByRole("region", { name: "Kırarak doğrula" }).getByRole("heading", { name: "Kırarak doğrula" }));
    expect(Math.abs(h2a.y + h2a.height / 2 - (h2b.y + h2b.height / 2))).toBeLessThanOrEqual(1);
  }

  // TPD-1, analist: başlık sarınca (1024 / 390) eylem grubu sağa yaslı, neden metni son düğmenin sağ kenarında biter.
  await page.context().clearCookies();
  await girisYap(page, "analist");
  for (const g of [1024, 390]) {
    await page.setViewportSize({ width: g, height: 900 });
    await page.goto("/gereksinimler/req-tpd-1");
    const baslik = page.locator(".sayfa-basligi");
    await expect(baslik.locator(".dugme-neden").first()).toBeVisible();
    await fontlariBekle(page);
    const kap = await kutu(baslik);
    const son = await kutu(baslik.locator(".eylemler .dugme").last());
    expect(Math.abs(son.x + son.width - (kap.x + kap.width))).toBeLessThanOrEqual(1);
    for (const n of await baslik.locator(".dugme-neden").all()) {
      const k = await metinKenari(n);
      expect(Math.abs(k.sag - (kap.x + kap.width))).toBeLessThanOrEqual(1);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(g);
  }
});

test("mobil (375 px) yayın önizleme ve akış göstergesi: sayfa yatay kaymaz, adım adları çakışmaz", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-tpd-1/yayin");
  await expect(page.getByTestId("yayin-hedefi")).toBeVisible();
  await expect(page.locator(".tablo-sarici table")).toBeVisible();
  await fontlariBekle(page);
  // Tablo kendi kabında kayar; görsel gizli metinler dahil hiçbir şey sayfayı genişletmez.
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  await page.screenshot({ path: `${EKRAN_DIZINI}/35-mobil-yayin.png`, fullPage: true });

  await page.goto("/gereksinimler/req-tpd-1");
  await expect(page.locator(".akis-ad").first()).toBeVisible();
  await fontlariBekle(page);
  expect(await akisAdCakismalari(page)).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
});

test("akış göstergesi 1024 px (1280 ekran %125): adım adları çakışmaz, düzen içerik genişliğine göre 7x2; tamamlanmış AI adımı kesik kalır", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-tpd-1");
  await expect(page.locator(".akis-ad").first()).toBeVisible();
  await fontlariBekle(page);
  expect(await akisAdCakismalari(page)).toEqual([]);
  expect(await page.locator(".akis ol").evaluate((e) => getComputedStyle(e).gridTemplateColumns.split(" ").length)).toBe(7);
  // Kesik kenar regresyonu: tür dolgusu kenarın altına boyanmaz (background-clip: padding-box), kenar kesik kalır.
  const aiNo = page.locator(".akis-tamam.akis-tur-ai .akis-no").first();
  await expect(aiNo).toBeAttached();
  expect(await aiNo.evaluate((e) => [getComputedStyle(e).backgroundClip, getComputedStyle(e).borderTopStyle])).toEqual(["padding-box", "dashed"]);
  await page.screenshot({ path: `${EKRAN_DIZINI}/59-akis-1024.png` });

  await page.setViewportSize({ width: 1440, height: 900 });
  await expect.poll(() => page.locator(".akis ol").evaluate((e) => getComputedStyle(e).gridTemplateColumns.split(" ").length)).toBe(14);
  expect(await akisAdCakismalari(page)).toEqual([]);

  await page.goto("/yol-haritasi");
  const yhAi = page.locator('.yh-adim.yh-tamam[data-tur="ai"] .yh-no').first();
  await expect(yhAi).toBeVisible();
  expect(await yhAi.evaluate((e) => [getComputedStyle(e).backgroundClip, getComputedStyle(e).borderTopStyle])).toEqual(["padding-box", "dashed"]);
});

test("bilinmeyen sayfa: h1 başlığı var (axe page-has-heading-one)", async ({ page }) => {
  await girisYap(page, "analist");
  await page.goto("/yok-boyle");
  await expect(page.getByRole("heading", { name: "Sayfa bulunamadı", level: 1 })).toBeVisible();
  const sonuc = await new AxeBuilder({ page }).withRules(["page-has-heading-one"]).analyze();
  expect(sonuc.violations.map((v) => v.id)).toEqual([]);
});

// Bölüm gezgini (`nav "Sayfa bölümleri"`) bağlantıları kart başlıklarıyla aynı metni taşır ve DOM'da
// içerikten önce gelir: kart başlığı `getByText(...).first()` ile değil, `getByRole("region", { name })`
// ile aranır (860 px ve altında gezgin gizlidir, `.first()` gizli bağlantıyı bulur; ≥861 px'te görünür
// bağlantıyı bulur ve kart kaybını yakalamaz). 861–1279 px'te gezgin üst çubuğun altında yapışkan tek satır
// yatay şerittir, ≥1280 px'te sağda yapışkan sütun.
test("bölüm gezgini: ≥1280 px yapışkan sütun, 1152 ve 861 px yapışkan tek satır şerit, 860 px'te gizli; bağlantı bölümü üst çubuğun altına getirir", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-tpd-1");
  const gezgin = page.getByRole("navigation", { name: "Sayfa bölümleri" });
  await expect(gezgin).toBeVisible();
  const bolum = page.getByRole("region", { name: "Tutarlılık bulguları" });
  await gezgin.getByRole("link", { name: "Tutarlılık bulguları" }).click();
  await expect(page).toHaveURL(/#bulgular$/);
  await expect(bolum).toBeInViewport();
  await expect
    .poll(async () => {
      const ust = await page.locator(".ust-cubuk").boundingBox();
      const kutu = await bolum.boundingBox();
      return !!ust && !!kutu && kutu.y >= ust.y + ust.height;
    })
    .toBe(true);
  await page.setViewportSize({ width: 1152, height: 720 });
  await expect(gezgin).toBeVisible();
  await expect(gezgin).toHaveCSS("position", "sticky");
  // Kaydırınca şerit üst çubuğun altında kalır; bağlantı bölümü şeridin altına getirir (WCAG 2.4.11).
  await gezgin.getByRole("link", { name: "Doküman" }).click();
  await gezgin.getByRole("link", { name: "Tutarlılık bulguları" }).click();
  await expect(gezgin).toBeInViewport();
  await expect
    .poll(async () => {
      const serit = await gezgin.boundingBox();
      const kutu = await bolum.boundingBox();
      return !!serit && !!kutu && kutu.y >= serit.y + serit.height;
    })
    .toBe(true);
  // Şeridin en dar ucu (861 px): bağlantılar sarmaz, şerit tek satır kalır → sabit çapa payı yeter.
  await page.setViewportSize({ width: 861, height: 720 });
  await gezgin.getByRole("link", { name: "Doküman" }).click();
  await gezgin.getByRole("link", { name: "Tutarlılık bulguları" }).click();
  await expect
    .poll(async () => {
      const serit = await gezgin.boundingBox();
      const kutu = await bolum.boundingBox();
      return !!serit && !!kutu && serit.height < 60 && kutu.y >= serit.y + serit.height;
    })
    .toBe(true);
  await page.setViewportSize({ width: 860, height: 800 });
  await expect(gezgin).toBeHidden();
  await expect(page.getByRole("region", { name: "Tutarlılık bulguları" })).toBeVisible();
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
