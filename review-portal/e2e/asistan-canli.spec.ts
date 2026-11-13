// Portal asistanı — canlı yığın testi (AI-ASISTAN-PLANI §13 "E2E" (b)). PORTAL_LIVE=1 ile koşar
// (playwright.config.ts: `canli.spec.ts` ile biten dosyalar); portal gerçek core-api + core-worker'a
// bağlıdır, örnek veri yoktur. Model KAPALI kipte koşar (TP_ASISTAN_MODEL_MODE=off): hiçbir cevap
// model çağırmaz, maliyet yoktur; yalnız hata sözlüğü, kayıt şablonları, kapalı kip mesajı ve kural
// önerileri sınanır. Çalıştırma (yığın `make up` ile ayakta, worker'da TP_ASISTAN_MODEL_MODE=off):
//
//   set -a; . ../.env; set +a; PORTAL_LIVE=1 npx playwright test e2e/asistan-canli.spec.ts
//
// Kapsam (§2 örnek soruları): S2 (sözlük), S3 ve S6 (şablon), kapalı kip mesajı, gereksinim detayında
// kural önerisi (S12) — model kapalıyken kartın "Neden? Sor" düğmesi "Açıklamayı göster" olur (§17.6),
// model çağrısı yapılmaz. Roller: Analist ve Testçi. Prova dürüstlük kilidiyle aynı kural: canlı
// yığında "CANLI"/"live" metni ve "ÖRNEK VERİ" hiçbir yerde görünmez.
import { expect, test, type Locator, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";

const EKRAN_DIZINI = "e2e/ekranlar/canli/asistan";
mkdirSync(EKRAN_DIZINI, { recursive: true });

const PAROLA = process.env.PORTAL_PASSWORD ?? process.env.SEED_USER_PASSWORD ?? "";
const SAHTE_CANLI = /^live$|^CANLI$/;
/** Worker bir soruyu kuyruktan alıp cevaplayana kadar (modelsiz dallar saniyeler sürer). */
const CEVAP_SURESI = 60_000;
/** Kapalı kip sabit metni (core `flow.KAPALI_METNI`). */
const KAPALI_METNI = "Canlı model kapalı; hata mesajlarını ve gereksinim/iş durumunu sorabilirsiniz.";

interface AsistanDurumu {
  etkin: boolean;
  neden?: string | null;
  mod: string;
  model_hazir?: boolean;
}

test.beforeAll(() => {
  if (!PAROLA) throw new Error("SEED_USER_PASSWORD (veya PORTAL_PASSWORD) ortamda yok: `set -a; . ../.env; set +a`");
});

async function girisYap(page: Page, kullanici: string) {
  await page.goto("/giris");
  await page.getByLabel("Kullanıcı adı").fill(kullanici);
  await page.getByLabel("Parola").fill(PAROLA);
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("navigation", { name: "Ana menü" })).toBeVisible();
  await expect(page.locator(".kullanici-ad")).toHaveText(kullanici);
}

/** Asistan uçları çekirdekte, worker ayakta ve model kapalı kipte mi? Değilse test anlamsızdır. */
async function kapaliKipDogrula(page: Page): Promise<AsistanDurumu> {
  const api = await page.request.get("/api/openapi.json");
  expect(api.ok(), "core-api openapi.json okunamadı (yığın ayakta mı?)").toBe(true);
  const yollar = Object.keys(((await api.json()) as { paths: Record<string, unknown> }).paths);
  expect(yollar, "çekirdek asistan uçlarını sunmuyor").toContain("/assistant/status");
  expect(yollar).toContain("/assistant/suggestions");

  const r = await page.request.get("/api/assistant/status");
  expect(r.ok(), `GET /assistant/status → ${r.status()}`).toBe(true);
  const d = (await r.json()) as AsistanDurumu;
  expect(d.etkin, `asistan kapalı (neden: ${d.neden ?? "?"}); core-worker asistan şeridi ayakta mı?`).toBe(true);
  expect(d.mod, "bu test TP_ASISTAN_MODEL_MODE=off ister (model çağrısı yapılmaz)").toBe("off");
  expect(d.model_hazir ?? false).toBe(false);
  return d;
}

/** Gereksinim listesi boşsa Jira'dan (jira-sim) çeker; TPD-3 satırı görünene kadar bekler. */
async function gereksinimleriHazirla(page: Page) {
  await page.goto("/gereksinimler");
  await expect(page.getByRole("heading", { name: "Gereksinimler", level: 1 })).toBeVisible();
  const satir = page.getByRole("row").filter({ hasText: "TPD-3" }).first();
  if (!(await satir.waitFor({ timeout: 10_000 }).then(() => true).catch(() => false))) {
    const cek = page.getByRole("button", { name: "Jira'dan çek" });
    test.skip(!(await cek.isEnabled().catch(() => false)), "gereksinim yok ve bu rol Jira'dan çekemez (önce analist testi koşmalı)");
    await cek.click();
    await expect(async () => {
      await page.reload();
      await expect(page.getByRole("row").filter({ hasText: "TPD-3" }).first()).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 60_000 });
  }
}

function panel(page: Page): Locator {
  return page.getByTestId("asistan-paneli");
}

/**
 * Paneli Sohbet sekmesinde, boş (yeni) bir sohbetle açar. "Son hata" çipi varsayılan olarak
 * kaldırılır: worker'da sözlük dalı şablondan önce gelir, "neden" içeren bir kayıt sorusu son hata
 * bağlamıyla gönderilirse sözlükten cevaplanır (S3 sınanamaz).
 */
async function sohbetAc(page: Page, { sonHataKalsin = false }: { sonHataKalsin?: boolean } = {}): Promise<Locator> {
  if (!(await panel(page).isVisible().catch(() => false))) {
    await page.getByRole("button", { name: "Asistanı aç", exact: true }).click();
  }
  const p = panel(page);
  await expect(p).toBeVisible();
  await p.getByRole("tab", { name: "Sohbet" }).click();
  await p.getByRole("button", { name: "Yeni sohbet" }).click();
  const kaldir = p.getByRole("button", { name: "Son hata bağlamını kaldır" });
  if (!sonHataKalsin && (await kaldir.isVisible().catch(() => false))) await kaldir.click();
  return p;
}

/** Soruyu yazıp gönderir; son cevap kartını (worker bitirince) döndürür. */
async function sor(p: Locator, soru: string): Promise<Locator> {
  await p.getByLabel("Sorunuz").fill(soru);
  await p.getByRole("button", { name: "Asistana sor" }).click();
  await expect(p.locator(".asistan-soru").filter({ hasText: soru }).last()).toBeVisible();
  return sonCevap(p);
}

async function sonCevap(p: Locator): Promise<Locator> {
  await expect(p.getByTestId("asistan-bekleme")).toHaveCount(0, { timeout: CEVAP_SURESI });
  await expect(p.getByRole("alert")).toHaveCount(0);
  const kart = p.getByRole("article").last();
  await expect(kart).toBeVisible();
  return kart;
}

/** Hazır (modelsiz) cevap kartının ortak beklentileri: ücret yok, derin inceleme yok, sahte canlı yok. */
async function hazirCevap(kart: Locator, rozet: "ŞABLON" | "MODEL KAPALI") {
  // 013 §7: hazır cevap tek kip rozetiyle işaretlenir (açıklaması görünür küçük metin).
  await expect(kart.getByTestId("kip-rozeti")).toHaveText(rozet);
  await expect(kart.getByText(/Maliyet: ölçülmedi/)).toBeVisible();
  await expect(kart.getByRole("button", { name: /Daha ayrıntılı incele/ })).toHaveCount(0);
  await expect(kart.getByText("Bilgi amaçlıdır; kararı ilgili ekranda verin.")).toBeVisible();
}

/** Prova dürüstlük kilidi (rehearsal/ui/prova.spec.ts `durustluk`) + kapalı kip rozeti. */
async function durustluk(page: Page) {
  await expect(page.getByText("ÖRNEK VERİ")).toHaveCount(0);
  await expect(page.getByText(SAHTE_CANLI)).toHaveCount(0);
}

/** Bu kullanıcıya bu ekranda öneri düşen ilk gereksinim (yoksa null). Hız sınırı (60/dk) için sınırlı tarama. */
async function oneriliGereksinim(page: Page, oncelikli: string[]): Promise<{ id: string; anahtar: string; baslik: string } | null> {
  const r = await page.request.get("/api/requirements");
  expect(r.ok()).toBe(true);
  const govde = (await r.json()) as unknown;
  const liste = (Array.isArray(govde) ? govde : ((govde as { items?: unknown[] }).items ?? [])) as { id: string; jira_key?: string | null }[];
  const sirali = [...liste].sort((a, b) => {
    const ia = oncelikli.indexOf(a.jira_key ?? "");
    const ib = oncelikli.indexOf(b.jira_key ?? "");
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  for (const g of sirali.slice(0, 12)) {
    const q = new URLSearchParams({ rota: `/gereksinimler/${g.id}`, varlik_tur: "requirement", varlik_id: g.id });
    const o = await page.request.get(`/api/assistant/suggestions?${q}`);
    if (!o.ok()) continue;
    const sonuc = (await o.json()) as { oneriler: { baslik: string }[] };
    if (sonuc.oneriler.length > 0) return { id: g.id, anahtar: g.jira_key ?? "", baslik: sonuc.oneriler[0].baslik };
  }
  return null;
}

test("analist (model kapalı): S2 sözlük, S3 şablon, kapalı kip mesajı, S12 kural önerisi", async ({ page }) => {
  test.setTimeout(240_000);
  const hatalar: string[] = [];
  page.on("pageerror", (e) => hatalar.push(String(e)));

  await girisYap(page, "analist");
  await kapaliKipDogrula(page);
  await gereksinimleriHazirla(page);

  // --- Panel başlığı: kapalı kipte "HAZIR CEVAPLAR"; ÖRNEK VERİ ve CANLI/live yok.
  let p = await sohbetAc(page);
  await expect(p.getByText("HAZIR CEVAPLAR", { exact: true })).toBeVisible();
  await expect(p.getByText("Sorular denetim kaydına girer; sohbet 90 gün saklanır.")).toBeVisible();
  await durustluk(page);
  // Kapalı kipte yalnız modelsiz soru önerileri.
  const oneriListesi = p.getByRole("list", { name: "Soru önerileri" });
  await expect(oneriListesi.getByRole("button", { name: "Bugün ne yapmalıyım?" })).toBeVisible();
  await expect(oneriListesi.getByRole("button", { name: "Onay bekleyen story'ler hangileri?" })).toHaveCount(0);
  await expect(oneriListesi.getByRole("button", { name: "Bu ekranda ne yapabilirim?" })).toHaveCount(0);

  // --- S2: gerçek bir API hatası (olmayan gereksinim → 404 `bulunamadi`) "son hata" olur; sözlük cevabı.
  await page.goto(`/gereksinimler/${randomUUID()}`);
  await expect(page.getByRole("main").getByRole("alert").first()).toBeVisible();
  p = await sohbetAc(page, { sonHataKalsin: true });
  await expect(p.getByLabel("Soruya eklenecek bağlam").getByText(/^Son hata:/)).toBeVisible();
  await p.getByRole("list", { name: "Soru önerileri" }).getByRole("button", { name: "Az önceki hata ne demek?" }).click();
  let kart = await sonCevap(p);
  await hazirCevap(kart, "ŞABLON");
  await expect(kart.getByText("Kayıt bulunamadı", { exact: true })).toBeVisible();
  await expect(kart.getByText(/^Ne yapmalı: /)).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/01-s2-sozluk.png` });

  // --- S3: kayıt durumu şablonu (modelsiz): bekleyen kapı + sorumlu + ekran bağlantısı.
  kart = await sor(await sohbetAc(page), "TPD-3 neden case üretimine geçmiyor?");
  await hazirCevap(kart, "ŞABLON");
  await expect(kart.getByText(/^TPD-3 · Gereksinim/)).toBeVisible();
  await expect(kart.getByRole("link", { name: /^Git: Gereksinim ekranı$/ })).toBeVisible();
  await expect(kart.getByText("Kaynakla doğrulandı").first()).toBeVisible();
  await page.screenshot({ path: `${EKRAN_DIZINI}/02-s3-sablon.png` });
  // Git iç rotaya (TPD-3 detayı) gider.
  await kart.getByRole("link", { name: "Git: Gereksinim ekranı" }).click();
  await expect(page).toHaveURL(/\/gereksinimler\/[0-9a-f-]{36}$/);
  await expect(page.locator(".baslik-anahtar")).toHaveText("TPD-3");

  // --- Kapalı kip: şablon/sözlük dışı soru modele gitmez, sabit mesaj döner.
  kart = await sor(await sohbetAc(page), "Flaky test nasıl ayıklanır?");
  await hazirCevap(kart, "MODEL KAPALI");
  await expect(kart.getByText(KAPALI_METNI)).toBeVisible();
  await durustluk(page);
  await page.screenshot({ path: `${EKRAN_DIZINI}/03-kapali-kip.png` });

  // --- S12: gereksinim detayında kural önerisi (TPD-2 kabul kriteri eksik öncelikli). Model kapalı:
  // "Neden? Sor" yerine "Açıklamayı göster" (kuralın açıklama metni; model çağrısı yok).
  const hedef = await oneriliGereksinim(page, ["TPD-2", "TPD-1", "TPD-3"]);
  expect(hedef, "analist için öneri düşen gereksinim yok (kural seti / tohum verisi?)").not.toBeNull();
  await page.goto(`/gereksinimler/${hedef!.id}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const dugme = page.getByTestId("oneri-dugmesi");
  await expect(dugme).toHaveAttribute("aria-label", /^Öneriler: [1-9]\d*$/);
  await dugme.click();
  await expect(panel(page).getByRole("tab", { name: "Öneriler" })).toHaveAttribute("aria-selected", "true");
  const sekme = page.getByTestId("oneriler-sekmesi");
  const oneri = sekme.getByRole("article").filter({ has: page.getByRole("heading", { name: hedef!.baslik }) });
  await expect(oneri).toHaveCount(1);
  await expect(oneri.getByRole("button", { name: "Yaptım" })).toBeVisible();
  await expect(oneri.getByRole("button", { name: "Gizle" })).toBeVisible();
  await expect(oneri.getByRole("button", { name: "Neden? Sor" })).toHaveCount(0);
  await expect(oneri.getByRole("list", { name: "Hazır sorular" })).toHaveCount(0);
  await expect(sekme.getByRole("button", { name: "Başka ne yapabilirim?" })).toHaveCount(0);
  await oneri.getByRole("button", { name: "Açıklamayı göster" }).click();
  await expect(oneri.locator(".oneri-aciklama")).not.toBeEmpty();
  // Jira eylemli kartta bağlantıyı yalnız sunucu kurar; varsa yeni sekmede ve güvenli rel ile.
  const jira = oneri.getByRole("link", { name: /Jira'yı aç/ });
  if ((await jira.count()) > 0) {
    await expect(jira).toHaveAttribute("target", "_blank");
    await expect(jira).toHaveAttribute("rel", "noopener noreferrer");
  }
  await durustluk(page);
  await page.screenshot({ path: `${EKRAN_DIZINI}/04-s12-oneri.png` });
  expect(hatalar).toEqual([]);
});

test("testçi (model kapalı): S6 bugün ne yapmalıyım, S3 şablon, kapalı kip mesajı, öneri paneli", async ({ page }) => {
  test.setTimeout(180_000);
  const hatalar: string[] = [];
  page.on("pageerror", (e) => hatalar.push(String(e)));

  await girisYap(page, "testci");
  await kapaliKipDogrula(page);
  await gereksinimleriHazirla(page);

  // --- S6: rolün bekleyen işleri (probe_my_queue şablonu).
  let p = await sohbetAc(page);
  await expect(p.getByText("HAZIR CEVAPLAR", { exact: true })).toBeVisible();
  await p.getByRole("list", { name: "Soru önerileri" }).getByRole("button", { name: "Bugün ne yapmalıyım?" }).click();
  let kart = await sonCevap(p);
  await hazirCevap(kart, "ŞABLON");
  await expect(kart.getByText("Kaynakla doğrulandı").first()).toBeVisible();
  await durustluk(page);
  await page.screenshot({ path: `${EKRAN_DIZINI}/05-s6-testci.png` });
  // Kuyrukta iş varsa yönlendirmeler iç rotadır.
  const git = kart.getByRole("link", { name: /^Git: / });
  if ((await git.count()) > 0) await expect(git.first()).toHaveAttribute("href", /^\/[a-z]/);

  // --- S3 testçi gözüyle: aynı şablon (rol bağımsız kayıt durumu).
  kart = await sor(await sohbetAc(page), "TPD-3 neden bekliyor?");
  await hazirCevap(kart, "ŞABLON");
  await expect(kart.getByText(/^TPD-3 · Gereksinim/)).toBeVisible();

  // --- Kapalı kip mesajı.
  p = await sohbetAc(page);
  kart = await sor(p, "Demo uygulamasında kampanya indirimi nasıl hesaplanıyor?");
  await hazirCevap(kart, "MODEL KAPALI");
  await expect(kart.getByText(KAPALI_METNI)).toBeVisible();

  // --- Öneri paneli: testçinin kuralı olan bir ekranda (bug taslağı kararı) düğme ve kart.
  const r = await page.request.get("/api/bug-drafts");
  expect(r.ok()).toBe(true);
  const govde = (await r.json()) as unknown;
  const taslaklar = (Array.isArray(govde) ? govde : ((govde as { items?: unknown[] }).items ?? [])) as { id: string; durum?: string }[];
  const taslak = taslaklar.find((t) => t.durum === "draft");
  if (!taslak) {
    test.info().annotations.push({ type: "atlandı", description: "taslak durumda bug taslağı yok; testçi öneri kartı sınanmadı" });
  } else {
    await page.goto(`/bug-taslaklari/${taslak.id}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const dugme = page.getByTestId("oneri-dugmesi");
    await expect(dugme).toHaveAttribute("aria-label", /^Öneriler: [1-9]\d*$/);
    await dugme.click();
    const oneri = page.getByTestId("oneriler-sekmesi").getByRole("article").filter({ hasText: /Taslak kararınızı bekliyor/ });
    await expect(oneri).toHaveCount(1);
    await expect(oneri.getByRole("button", { name: "Açıklamayı göster" })).toBeVisible();
    await expect(oneri.getByRole("button", { name: "Neden? Sor" })).toHaveCount(0);
    // Sistem hattı (§17.3): bug taslağı ekranında Jira taslağı/yorumu önerilmez.
    await expect(oneri.getByRole("button", { name: "Taslağı göster" })).toHaveCount(0);
    await durustluk(page);
    await page.screenshot({ path: `${EKRAN_DIZINI}/06-testci-oneri.png` });
  }
  expect(hatalar).toEqual([]);
});
