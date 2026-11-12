// Portal asistanı duman testleri (AI-ASISTAN-PLANI §13 "E2E" (a)): örnek veri derlemesinde
// (vite build --mode mock) panel, bağlam çipi, "? Bu ne?" (pasif/disabled düğme vakası dahil),
// "Git" yönlendirmeleri ve Öneri paneli. Arka uç gerekmez; asistan cevapları mock'un hazırlanmış
// örnekleridir ("ÖRNEK VERİ"), model çağrısı yoktur. Kapalı kip (TP_ASISTAN_MODEL_MODE=off) mock
// derlemede tarayıcıdan seçilemez; o dal birim testlerinde (panel.test.tsx, oneri.test.tsx) ve canlı
// yığında (asistan-canli.spec.ts) sınanır.
//
// Not: mock arka ucun durumu (sohbetler, "son hata" kaydı) sayfa belleğindedir; tam sayfa yüklemesi
// (page.goto) sıfırlar. Durum taşıması gereken adımlar uygulama içi gezinmeyle (bağlantı/düğme) yapılır.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

const EKRAN_DIZINI = "e2e/ekranlar/asistan";
mkdirSync(EKRAN_DIZINI, { recursive: true });

/** Rozet/metin olarak "canlı" gösterimi (prova dürüstlük kilidiyle aynı desen). */
const SAHTE_CANLI = /^live$|^CANLI$/;

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

/** Masaüstünde panel modal olmayan tamamlayıcı bölge; dar ekranda modal dialog. */
function panel(page: Page): Locator {
  return page.getByTestId("asistan-paneli");
}

async function paneliAc(page: Page): Promise<Locator> {
  await page.getByRole("button", { name: "Asistanı aç", exact: true }).click();
  const p = panel(page);
  await expect(p).toBeVisible();
  return p;
}

/** Son cevap kartı tamamlanana kadar bekler (mock adımları ~2 sn). */
async function sonCevap(p: Locator): Promise<Locator> {
  await expect(p.getByTestId("asistan-bekleme")).toHaveCount(0, { timeout: 15_000 });
  const kart = p.getByRole("article").last();
  await expect(kart).toBeVisible();
  return kart;
}

/** Panelin WCAG 2.2 AA denetimi (renk karşıtlığı, hedef boyutu dahil): ihlal 0. */
async function panelAxe(page: Page, bolge = '[data-testid="asistan-paneli"]') {
  const axe = await new AxeBuilder({ page }).include(bolge).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(axe.violations.map((v) => `${v.id}: ${v.help} — ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
}

test("asistan paneli: açılır, sekmeler, dürüst rozetler, bağlam çipi rotayla güncellenir, Esc kapatır", async ({ page }) => {
  const hatalar = konsolHatalariniTopla(page);
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-tpd-1");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Kampanyalı sepet/);

  // Kapalıyken yalnız başlatıcı düğme; giriş ekranında hiç yok (aşağıda).
  await expect(panel(page)).toHaveCount(0);
  const p = await paneliAc(page);
  await expect(page.getByRole("complementary", { name: "Asistan" })).toBeVisible();
  await expect(p.getByRole("heading", { name: "Asistan", level: 2 })).toBeVisible();

  // Sekmeler: tablist, varsayılan Sohbet.
  const sekmeler = p.getByRole("tablist", { name: "Asistan sekmeleri" });
  await expect(sekmeler.getByRole("tab", { name: "Sohbet" })).toHaveAttribute("aria-selected", "true");
  await expect(sekmeler.getByRole("tab", { name: "Öneriler" })).toHaveAttribute("aria-selected", "false");

  // Dürüstlük: örnek veri derlemesinde "ÖRNEK VERİ" rozeti; canlı kipte rozet yok, CANLI/live metni hiçbir yerde yok.
  await expect(p.getByText("ÖRNEK VERİ", { exact: true })).toBeVisible();
  await expect(p.getByText("HAZIR CEVAPLAR")).toHaveCount(0);
  await expect(page.getByText(SAHTE_CANLI)).toHaveCount(0);
  await expect(p.getByText("Sorular denetim kaydına girer; sohbet 90 gün saklanır.")).toBeVisible();

  // Bağlam çipi: ekran adı + Jira anahtarı (matchPath ile varlıktan).
  const cipler = p.getByLabel("Soruya eklenecek bağlam");
  await expect(cipler.getByText(/Bu ekran: Gereksinim detayı · TPD-1/)).toBeVisible();
  // Boş sohbette soru önerileri (rol + rota).
  await expect(p.getByRole("list", { name: "Soru önerileri" }).getByRole("button", { name: "Bugün ne yapmalıyım?" })).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/01-panel-gereksinim.png` });

  // Erişilebilirlik: panelin kendisinde ciddi ihlal yok.
  const axe = await new AxeBuilder({ page }).include('[data-testid="asistan-paneli"]').analyze();
  const ciddi = axe.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
  expect(ciddi.map((v) => `${v.id}: ${v.help}`)).toEqual([]);

  // Çip kaldırılabilir; rota değişince (uygulama içi gezinme) yeniden eklenir ve güncellenir.
  await cipler.getByRole("button", { name: "Ekran bağlamını kaldır" }).click();
  await expect(cipler.getByText(/Bu ekran:/)).toHaveCount(0);
  await page.getByRole("navigation", { name: "Ana menü" }).getByRole("link", { name: /Bug taslakları/ }).click();
  await expect(page).toHaveURL(/\/bug-taslaklari$/);
  await expect(panel(page)).toBeVisible();
  await expect(cipler.getByText("Bu ekran: Bug taslakları")).toBeVisible();

  // Esc paneli kapatır (odak panel içindeyken).
  await p.getByLabel("Sorunuz").focus();
  await page.keyboard.press("Escape");
  await expect(panel(page)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Asistanı aç", exact: true })).toBeVisible();

  // Giriş ekranında asistan yok.
  await page.getByRole("button", { name: /Çıkış/ }).click();
  await expect(page).toHaveURL(/\/giris$/);
  await expect(page.getByRole("button", { name: "Asistanı aç", exact: true })).toHaveCount(0);
  expect(hatalar).toEqual([]);
});

test('"? Bu ne?": pasif (disabled) düğme seçilir, nedeni sorulur; Esc önce kipten çıkar; "Git" iç rotaya götürür', async ({ page }) => {
  const hatalar = konsolHatalariniTopla(page);
  // Sunucu: script detayında "Merge et" pasif (yalnız mühendis) ve "Git: Kod üretimi" açabildiği ekran
  // (Kod üretimi listesi yalnız mühendis + sunucuya açık).
  await girisYap(page, "sunucu");
  await page.goto("/kod/scr-2");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/7 adet kampanyalı/);

  // Analist için mühendis düğmesi pasif ve nedenini title'da söyler (S1 vakası).
  const merge = page.getByRole("button", { name: "Merge et" });
  await expect(merge).toBeDisabled();
  await expect(merge).toHaveAttribute("title", "Bu işlem için gereken rol: Mühendis");
  await merge.scrollIntoViewIfNeeded();

  const p = await paneliAc(page);
  await expect(p.getByLabel("Soruya eklenecek bağlam").getByText("Bu ekran: Script detayı")).toBeVisible();

  // Kip aç → Esc yalnız kipten çıkar, panel açık kalır.
  const buNe = p.getByRole("button", { name: "? Bu ne?" });
  await buNe.click();
  await expect(buNe).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("asistan-bune-bindirme")).toBeVisible();
  await expect(page.getByText("Sormak istediğiniz öğeye tıklayın.")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("asistan-bune-bindirme")).toHaveCount(0);
  await expect(panel(page)).toBeVisible();

  // Kipte disabled düğmeye tıklanır: tarayıcı disabled öğeye olay göndermese de bindirme
  // elementsFromPoint ile altındaki düğmeyi bulur.
  await buNe.click();
  const kutu = await merge.boundingBox();
  expect(kutu, "Merge et görünür alanda olmalı").not.toBeNull();
  await page.mouse.move(kutu!.x + kutu!.width / 2, kutu!.y + kutu!.height / 2);
  await page.mouse.click(kutu!.x + kutu!.width / 2, kutu!.y + kutu!.height / 2);
  await expect(page.getByTestId("asistan-bune-bindirme")).toHaveCount(0);
  await expect(p.getByLabel("Soruya eklenecek bağlam").getByText("Seçili: Merge et")).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/02-bu-ne-secili.png` });

  // Soru gönderilir; cevap kartı (mock örneği) gelir, seçili çip tüketilir.
  await p.getByLabel("Sorunuz").fill("Bu düğme neden gri?");
  await p.getByRole("button", { name: "Asistana sor" }).click();
  await expect(p.getByText("Bu düğme neden gri?")).toBeVisible();
  const kart = await sonCevap(p);
  await expect(kart.getByText(/ÖRNEK VERİ — hazırlanmış örnek cevap/)).toBeVisible();
  await expect(kart.getByText("Bilgi amaçlıdır; kararı ilgili ekranda verin.")).toBeVisible();
  await expect(p.getByText("Seçili: Merge et")).toHaveCount(0);
  await expect(page.getByText(SAHTE_CANLI)).toHaveCount(0);
  // Doğrulanmamış kaynak satırı (docs/DEMO-AKISI.md) biçimle işaretli; satır soldurulmaz → kart AA'da ihlalsiz.
  const dogrulanmamis = kart.locator(".soluk-kaynak");
  await expect(dogrulanmamis.getByText("doğrulanmadı", { exact: true })).toBeVisible();
  await dogrulanmamis.scrollIntoViewIfNeeded();
  await panelAxe(page);
  await page.screenshot({ path: `${EKRAN_DIZINI}/03-bu-ne-cevap.png` });

  // "Git": iç rotaya gider; masaüstünde panel açık kalır, sohbet korunur.
  await kart.getByRole("link", { name: "Git: Kod üretimi" }).click();
  await expect(page).toHaveURL(/\/kod$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^Kod üretimi$/);
  await expect(panel(page)).toBeVisible();
  await expect(p.getByText("Bu düğme neden gri?")).toBeVisible();
  expect(hatalar).toEqual([]);
});

// İki temada (koyu varsayılan, açık) panelin üç durumu: boş sohbet, cevap kartı (doğrulanmamış kaynak satırı
// dahil), Öneriler sekmesi; dar ekranda (390 px) modal dialog. Token'a çevrilen renklerin kontrast kilidi.
for (const tema of ["koyu", "acik"] as const) {
  test(`asistan paneli axe (${tema} tema): boş sohbet, cevap kartı, Öneriler, 390 px modal`, async ({ page }) => {
    await page.addInitScript((t) => {
      try {
        localStorage.setItem("tp-tema-v", "2");
        localStorage.setItem("tp-tema", t);
      } catch {
        /* depolama kapalıysa varsayılan tema */
      }
    }, tema);
    await girisYap(page, "analist");
    await expect(page.locator("html")).toHaveAttribute("data-theme", tema === "koyu" ? "dark" : "light");
    await page.goto("/gereksinimler/req-ft-1");
    const p = await paneliAc(page);
    await panelAxe(page);

    await p.getByLabel("Sorunuz").fill("Bu düğme neden gri?");
    await p.getByRole("button", { name: "Asistana sor" }).click();
    const kart = await sonCevap(p);
    const dogrulanmamis = kart.locator(".soluk-kaynak");
    await expect(dogrulanmamis.getByText("doğrulanmadı", { exact: true })).toBeVisible();
    await dogrulanmamis.scrollIntoViewIfNeeded();
    await panelAxe(page);
    await page.screenshot({ path: `${EKRAN_DIZINI}/08-axe-${tema}-cevap.png` });

    await p.getByRole("tab", { name: "Öneriler" }).click();
    await expect(page.getByTestId("oneriler-sekmesi").getByRole("article").first()).toBeVisible();
    await panelAxe(page);

    await page.setViewportSize({ width: 390, height: 844 });
    const d = page.getByRole("dialog", { name: "Asistan" });
    await expect(d).toBeVisible();
    await d.getByRole("tab", { name: "Sohbet" }).click();
    await expect(d.getByRole("article").last()).toBeVisible();
    await panelAxe(page);
    await page.screenshot({ path: `${EKRAN_DIZINI}/08-axe-${tema}-390.png` });
  });
}

test("masaüstü panel odağı örtmez (WCAG 2.4.11): ≥1440 px içerik boşaltılır; daha dar ekranda Esc örtülen öğeden paneli kapatır", async ({ page }) => {
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-ft-1");
  const p = await paneliAc(page);
  // 1440 px: içerik sütunu panelin solunda biter.
  const panelSol = (await p.boundingBox())!.x;
  const icerik = await page.locator(".icerik").evaluate((el) => el.getBoundingClientRect().right - parseFloat(getComputedStyle(el).paddingRight));
  expect(icerik).toBeLessThanOrEqual(panelSol);

  // 1280 px: panel bindirme; panelin altındaki odaklı öğede Esc paneli kapatır, odak yerinde kalır.
  await page.setViewportSize({ width: 1280, height: 900 });
  const ortulen = page.getByRole("link", { name: "PO teyidi" }).first();
  await ortulen.focus();
  expect((await ortulen.boundingBox())!.x).toBeGreaterThan((await p.boundingBox())!.x);
  await page.keyboard.press("Escape");
  await expect(panel(page)).toHaveCount(0);
  await expect(ortulen).toBeFocused();
  // Panelin altında olmayan öğede Esc paneli kapatmaz.
  await paneliAc(page);
  await page.getByRole("navigation", { name: "Ana menü" }).getByRole("link").first().focus();
  await page.keyboard.press("Escape");
  await expect(panel(page)).toBeVisible();
});

// Panel açıkken (1440–1699 px) içerik 861–1279 px genişliğine iner: bölüm gezgini sağ sütunda kalmaz,
// yapışkan tek satır şerit olur; gövde içerik genişliğini alır. ≥1700 px'te sütun geri gelir.
test("panel açıkken (1440–1699 px) bölüm gezgini yatay şerit, gövde daralmaz; ≥1700 px sütun", async ({ page }) => {
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-tpd-1");
  const gezgin = page.getByRole("navigation", { name: "Sayfa bölümleri" });
  const govde = page.locator(".bolum-govde");
  await expect(gezgin).toHaveCSS("flex-direction", "column");
  await paneliAc(page);
  for (const w of [1440, 1680]) {
    await page.setViewportSize({ width: w, height: 900 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect(gezgin).toHaveCSS("flex-direction", "row");
    await expect(gezgin).toHaveCSS("position", "sticky");
    const g = (await gezgin.boundingBox())!;
    const b = (await govde.boundingBox())!;
    expect(g.y + g.height, `${w}: şerit gövdenin üstünde`).toBeLessThanOrEqual(b.y);
    expect(g.height, `${w}: tek satır`).toBeLessThan(60);
    expect(b.width, `${w}: gövde içerik genişliğinde`).toBeGreaterThanOrEqual(700);
    expect(g.x + g.width, `${w}: şerit panelin altına girmez`).toBeLessThanOrEqual((await panel(page).boundingBox())!.x + 1);
    await gezgin.getByRole("link", { name: "Doküman" }).click();
    await gezgin.getByRole("link", { name: "Tutarlılık bulguları" }).click();
    await expect
      .poll(async () => {
        const serit = await gezgin.boundingBox();
        const kutu = await page.getByRole("region", { name: "Tutarlılık bulguları" }).boundingBox();
        return !!serit && !!kutu && kutu.y >= serit.y + serit.height;
      })
      .toBe(true);
  }
  await page.setViewportSize({ width: 1700, height: 900 });
  await expect(gezgin).toHaveCSS("flex-direction", "column");
  await page.getByRole("button", { name: "Asistanı kapat" }).click();
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(gezgin).toHaveCSS("flex-direction", "column");
});

test("son hata çipi ve sözlük cevabı (S2, mock örneği)", async ({ page }) => {
  const hatalar = konsolHatalariniTopla(page);
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-yok-e2e");
  await expect(page.getByRole("alert").filter({ hasText: "Gereksinim bulunamadı" })).toBeVisible();

  const p = await paneliAc(page);
  const cipler = p.getByLabel("Soruya eklenecek bağlam");
  await expect(cipler.getByText(/Son hata: Gereksinim bulunamadı/)).toBeVisible();
  await p.getByRole("list", { name: "Soru önerileri" }).getByRole("button", { name: "Az önceki hata ne demek?" }).click();
  const kart = await sonCevap(p);
  // 013 K12: "Hazır cevap" etiketi kip rozetine birleşti (ŞABLON; açıklama rozetin yanında görünür).
  await expect(kart.getByTestId("kip-rozeti")).toHaveText("ŞABLON");
  await expect(kart.getByTestId("kip-aciklamasi")).toHaveText("Yapay zekâ kullanılmadı; hazır açıklama.");
  await expect(kart.getByTestId("kip-aciklamasi")).toBeVisible();
  await expect(kart.getByText(/Maliyet: ölçülmedi/)).toBeVisible();
  // 404 konsol hatası beklenen (bulunamayan kayıt); başka hata yok.
  expect(hatalar.filter((h) => !/404|Not Found|bulunamadı/i.test(h))).toEqual([]);
});

test("dar ekran: panel modal dialog; şablon cevabındaki Git paneli kapatır, sohbet korunur", async ({ page }) => {
  const hatalar = konsolHatalariniTopla(page);
  await page.setViewportSize({ width: 700, height: 900 });
  await girisYap(page, "analist");
  await page.goto("/kosular");
  await page.getByRole("button", { name: "Asistanı aç", exact: true }).click();
  const d = page.getByRole("dialog", { name: "Asistan" });
  await expect(d).toBeVisible();
  await expect(d).toHaveAttribute("aria-modal", "true");
  await d.getByRole("button", { name: "Bugün ne yapmalıyım?" }).click();
  const kart = await sonCevap(d);
  // 013 K12: "Hazır cevap" etiketi kip rozetine birleşti (ŞABLON; açıklama rozetin yanında görünür).
  await expect(kart.getByTestId("kip-rozeti")).toHaveText("ŞABLON");
  await expect(kart.getByTestId("kip-aciklamasi")).toHaveText("Yapay zekâ kullanılmadı; hazır açıklama.");
  await expect(kart.getByTestId("kip-aciklamasi")).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/04-dar-ekran.png` });

  // Git: dar ekranda panel kapanır; yeniden açınca aynı sohbet.
  await kart.getByRole("link", { name: "Git: Gereksinimler" }).click();
  await expect(page).toHaveURL(/\/gereksinimler$/);
  await expect(d).toHaveCount(0);
  await page.getByRole("button", { name: "Asistanı aç", exact: true }).click();
  await expect(d.locator(".asistan-soru").filter({ hasText: "Bugün ne yapmalıyım?" })).toBeVisible();
  await expect(d.getByRole("article")).toHaveCount(1);
  expect(hatalar).toEqual([]);
});

test("760–860 px: panel ile mobil menü birbirini dışlar (menü açılınca panel kapanır, panel açılınca menü)", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 800 });
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-ft-1");
  await paneliAc(page);
  const menuDugmesi = page.getByRole("button", { name: "Menü" });
  await menuDugmesi.click();
  await expect(menuDugmesi).toHaveAttribute("aria-expanded", "true");
  await expect(panel(page)).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Ana menü" }).getByRole("link").first()).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menuDugmesi).toHaveAttribute("aria-expanded", "false");
  await paneliAc(page);
  await expect(menuDugmesi).toHaveAttribute("aria-expanded", "false");
});

test("Öneri paneli: rozet, kart, Neden? Sor sohbete geçer, Git çapaya gider; boş ve kuralsız ekran", async ({ page }) => {
  const hatalar = konsolHatalariniTopla(page);
  await girisYap(page, "analist");

  // Kuralsız (rota × rol): analist için script detayında Öneri düğmesi yok.
  await page.goto("/kod/scr-2");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/7 adet kampanyalı/);
  await expect(page.getByRole("button", { name: "Asistanı aç", exact: true })).toBeVisible();
  await expect(page.getByTestId("oneri-dugmesi")).toHaveCount(0);

  // Kural var, iş yok: rozetsiz düğme ve boş durum.
  await page.goto("/gereksinimler/req-tpd-1");
  const bos = page.getByRole("button", { name: "Öneriler: 0" });
  await expect(bos).toBeVisible();
  await bos.click();
  await expect(panel(page).getByRole("tab", { name: "Öneriler" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("oneriler-sekmesi").getByText("Bu ekranda sizin için bekleyen bir iş yok.")).toBeVisible();

  // Bekleyen iş: rozet 1; düğme paneli Öneriler sekmesinde açar.
  await page.goto("/gereksinimler/req-ft-1");
  const dugme = page.getByRole("button", { name: "Öneriler: 1" });
  await expect(dugme).toBeVisible();
  await expect(dugme.locator(".oneri-rozet")).toHaveText("1");
  // WCAG 2.5.3: görünür etiket erişilebilir adın içinde ("Öneriler 1" ⊂ "Öneriler: 1"; başlatıcıda "Asistanı aç");
  // dar üst çubukta (yalnız ikon + köşe rozeti) da. axe parantez içini addan düşürdüğü için ad "Öneriler (1)" değil.
  for (const genislik of [1440, 390]) {
    await page.setViewportSize({ width: genislik, height: 900 });
    const ad = await new AxeBuilder({ page }).include(".ust-cubuk").include(".asistan-baslatici-kap").withRules(["label-content-name-mismatch"]).analyze();
    expect(ad.violations.map((v) => `${genislik}px ${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await dugme.click();
  const p = panel(page);
  await expect(p.getByRole("tab", { name: "Öneriler" })).toHaveAttribute("aria-selected", "true");
  const sekme = page.getByTestId("oneriler-sekmesi");
  const kart = sekme.getByRole("article").filter({ hasText: /tutarlılık bulgusu kararınızı bekliyor/ });
  await expect(kart).toHaveCount(1);
  await expect(kart.getByRole("button", { name: "Yaptım" })).toBeVisible();
  await expect(kart.getByRole("button", { name: "Gizle" })).toBeVisible();
  // Model açık (mock canlı kip): "Neden? Sor" + hazır soru çipleri; "Başka ne yapabilirim?".
  await expect(kart.getByRole("list", { name: "Hazır sorular" }).getByRole("button", { name: "Kim onaylıyor?" })).toBeVisible();
  await expect(sekme.getByRole("button", { name: "Başka ne yapabilirim?" })).toBeVisible();
  await expect(page.getByText(SAHTE_CANLI)).toHaveCount(0);
  await page.screenshot({ path: `${EKRAN_DIZINI}/05-oneri-paneli.png` });
  // Erişilebilirlik: Öneriler sekmesi (kart, ikonlu araç çubuğu, tıklanabilir çipler; WCAG 2.2 hedef boyutu dahil) ihlalsiz.
  const axeOneri = await new AxeBuilder({ page }).include('[data-testid="asistan-paneli"]').withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(axeOneri.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);

  // "Neden? Sor": Sohbet sekmesine geçer ve öneri bağlamıyla soruyu gönderir.
  await kart.getByRole("button", { name: "Neden? Sor" }).click();
  await expect(p.getByRole("tab", { name: "Sohbet" })).toHaveAttribute("aria-selected", "true");
  await expect(p.getByText("Bu öneriyi neden yapmalıyım, yapmazsam ne olur?")).toBeVisible();
  const cevap = await sonCevap(p);
  await expect(cevap.getByText(/ÖRNEK VERİ — hazırlanmış örnek cevap/)).toBeVisible();

  // Öneriler sekmesine dönüp "Git": bulgular çapasına gider.
  await p.getByRole("tab", { name: "Öneriler" }).click();
  await sekme.getByRole("article").filter({ hasText: /tutarlılık bulgusu/ }).getByRole("button", { name: "Git" }).click();
  await expect(page).toHaveURL(/\/gereksinimler\/req-ft-1#bulgular$/);
  expect(hatalar).toEqual([]);
});

test("Kontrol Kulesi öneri ölçümü: Faydalı sayısı karta yansır (uygulama içi gezinme), kart ihlalsiz", async ({ page }) => {
  await girisYap(page, "analist");
  await page.goto("/gereksinimler/req-ft-1");
  await page.getByRole("button", { name: "Öneriler: 1" }).click();
  const sekme = page.getByTestId("oneriler-sekmesi");
  await sekme.getByRole("button", { name: "Faydalı" }).click();
  await expect(sekme.getByRole("button", { name: "Faydalı" })).toHaveAttribute("aria-pressed", "true");
  // Mock durumu sayfa belleğinde: Kule'ye menüden (tam yükleme olmadan) gidilir.
  await page.getByRole("button", { name: "Asistanı kapat" }).click();
  await page.getByRole("navigation", { name: "Ana menü" }).getByRole("link", { name: /Kontrol Kulesi/ }).click();
  const kart = page.getByRole("region", { name: "Öneriler ve asistan" });
  await expect(kart).toBeVisible();
  await expect(kart.getByTestId("oneri-toplam-geri-bildirim")).toHaveText("1 / 0 / 0");
  await expect(kart.getByTestId("oneri-olcum-tablosu")).toBeVisible();
  const axe = await new AxeBuilder({ page }).include(".kule-oneriler").withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(axe.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  await kart.screenshot({ path: `${EKRAN_DIZINI}/07-kule-oneri-olcumu.png` });
});

test("Öneri paneli: Jira taslağı kartı (mühendis, CI ortam hatası) — taslak gösterilir, simülatörde Jira bağlantısı yok", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await girisYap(page, "muhendis");
  await page.goto("/kosular/run-109");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/run-109/);
  await page.getByRole("button", { name: /^Öneriler: \d+$/ }).click();
  const sekme = page.getByTestId("oneriler-sekmesi");
  const kart = sekme.getByRole("article").filter({ has: page.getByRole("heading", { name: "Testler koşmadı: CI ortam hatası" }) });
  await expect(kart).toHaveCount(1);
  await expect(kart.getByText(/Demo Jira'sında kayıt oluşturma sayfası yok/)).toBeVisible();
  await expect(kart.getByText("Bu bir öneridir; kaydı siz açarsınız.")).toBeVisible();
  await expect(kart.getByRole("link", { name: /Jira'yı aç/ })).toHaveCount(0);
  await kart.getByRole("button", { name: "Taslağı göster" }).click();
  await expect(kart.getByText("Proje: TPD, Tür: Task seçin; metni yapıştırın.")).toBeVisible();
  await kart.getByRole("button", { name: "Kopyala" }).click();
  await expect(page.getByText("Taslak panoya kopyalandı.")).toBeVisible();
  const pano = await page.evaluate(() => navigator.clipboard.readText());
  expect(pano).toContain("Tür: Task");
  expect(pano).toContain("CI ortam hatası testlerin koşmasını engelliyor");
  await page.screenshot({ path: `${EKRAN_DIZINI}/06-oneri-jira-taslak.png` });
});

// Asistan düzeltmelerinin regresyon kilitleri (zorunlu renk, kısa yükseklik, "Bu ne?" bandı).
test("zorunlu renk kipi: seçili sekme ve basılı 'Faydalı' ayırt edilir; metin eylemleri kenara yapışmaz", async ({ page }) => {
  await page.emulateMedia({ forcedColors: "active" });
  await girisYap(page, "analist");
  await page.goto("/kod/scr-2");
  const p = await paneliAc(page);
  const stil = (l: Locator) =>
    l.evaluate((e) => {
      const c = getComputedStyle(e);
      return `${c.backgroundColor}|${c.color}|${c.borderTopColor}`;
    });
  expect(await stil(p.getByRole("tab", { name: "Sohbet" }))).not.toBe(await stil(p.getByRole("tab", { name: "Öneriler" })));

  await p.getByLabel("Sorunuz").fill("Bu düğme neden gri?");
  await p.getByRole("button", { name: "Asistana sor" }).click();
  const kart = await sonCevap(p);
  const eylem = kart.getByRole("button", { name: /^(Satırları|Alıntıyı) göster$/ }).first();
  await expect(eylem).toBeVisible();
  expect(parseFloat(await eylem.evaluate((e) => getComputedStyle(e).paddingLeft))).toBeGreaterThanOrEqual(6);

  await page.goto("/gereksinimler/req-ft-1");
  await page.getByRole("button", { name: "Öneriler: 1" }).click();
  const sekme = page.getByTestId("oneriler-sekmesi");
  const faydali = sekme.getByRole("button", { name: "Faydalı" });
  const gizle = sekme.getByRole("button", { name: "Gizle" }).first();
  await faydali.click();
  await expect(faydali).toHaveAttribute("aria-pressed", "true");
  expect(await stil(faydali)).not.toBe(await stil(gizle));
});

test("kısa görünüm (1280×500): panel bütün olarak kayar, soru alanı odakla görünür alana gelir", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 500 });
  await girisYap(page, "analist");
  await page.goto("/kosular");
  const p = await paneliAc(page);
  await expect(p).toHaveCSS("overflow-y", "auto");
  expect(await p.evaluate((e) => e.scrollHeight > e.clientHeight)).toBe(true);
  const soru = p.getByLabel("Sorunuz");
  await soru.focus();
  await expect.poll(async () => (await soru.boundingBox())!.y + (await soru.boundingBox())!.height).toBeLessThanOrEqual(500);
});

test('"Bu ne?" bandı: üst çubuğun altında, kenar çubuğunu örtmez, ÖRNEK VERİ şeridiyle aynı kenarlar; kipte kaydırma payı bandın altına', async ({ page }) => {
  await girisYap(page, "analist");
  await page.goto("/kod/scr-2");
  const p = await paneliAc(page);
  await p.getByRole("button", { name: "? Bu ne?" }).click();
  const bant = page.locator(".asistan-bune-ipucu");
  await expect(bant).toBeVisible();
  const b = (await bant.boundingBox())!;
  const s = (await page.getByTestId("ornek-veri-bandi").boundingBox())!;
  expect(b.y).toBeLessThanOrEqual(120);
  expect(b.x).toBeGreaterThanOrEqual(240);
  expect(Math.abs(b.x - s.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(b.x + b.width - (s.x + s.width))).toBeLessThanOrEqual(1);
  expect(b.y + b.height).toBeGreaterThanOrEqual(s.y + s.height);
  const pay = () => page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop));
  expect(await pay()).toBeGreaterThanOrEqual(b.y + b.height);
  await page.keyboard.press("Escape");
  await expect(bant).toHaveCount(0);
  expect(await pay()).toBe(72);
});
