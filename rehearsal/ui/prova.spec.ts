// Demo provası — arayüz (portal + jira-sim), Playwright videosu ve adım başına ekran görüntüsü.
//
//   cd rehearsal/ui && npm ci
//   UI_KIP=tur   npx playwright test   # salt okuma: tamamlanmış akışın ekranları (yedek video)
//   UI_KIP=canli npx playwright test   # sunucunun her eylemi arayüzden (temiz `make reset` ister)
//
// Parolalar .env'den okunur (SEED_USER_PASSWORD, JIRA_SIM_PO_PASSWORD) ve hiçbir yere yazılmaz:
// Playwright izi kapalıdır (playwright.config.ts), rapor metinleri tüm .env sırlarına karşı maskelenir.
// Canlı kipte locator kırılması sunucunun sahnedeki yoluyla yapılır: Demo kontrolleri düğmesi +
// arka planda `scripts/demo-web-sync.sh --watch` (DEMO-AKISI L1). `make demo-break` terminal yedeği
// API provasında (tp_rehearsal D1) ayrıca prova edilir.
// Durum beklemeleri oturumlu `page.request` ile API'den yoklanır; eylemler (tıklamalar) arayüzden.
// Beklenen değerler docs/DEMO-VERISI.md (ana yol: REPLAY senaryosu `f2-kod-hatasi`).
import { expect, test, type Page, type BrowserContext } from "@playwright/test";
import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { maskele } from "./zaman.js";

const BURASI = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(BURASI, "..", "..");
const KIP = process.env.UI_KIP === "canli" ? "canli" : "tur";
const RAPOR = process.env.UI_RAPOR_DIZINI ?? join(BURASI, "..", "reports", "ui");
const JIRA = process.env.JIRA_SIM_URL ?? "http://127.0.0.1:8090";
// Yedek videonun izlenebilmesi için her adım ekranında bekleme (ms). Turda varsayılan 2500.
const TEMPO_MS = Number(process.env.UI_TEMPO_MS ?? (process.env.UI_KIP === "canli" ? 800 : 2500));

function envDosyasi(): Record<string, string> {
  const s: Record<string, string> = {};
  try {
    for (const satir of readFileSync(join(REPO, ".env"), "utf-8").split("\n")) {
      const m = /^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$/.exec(satir);
      if (m) s[m[1]] = m[2].trim().replace(/^(['"])(.*)\1$/, "$2");
    }
  } catch {
    /* .env yoksa süreç ortamı */
  }
  return s;
}
const ENV = envDosyasi();
const PAROLA = process.env.PORTAL_PASSWORD ?? process.env.SEED_USER_PASSWORD ?? ENV.SEED_USER_PASSWORD ?? "";
const PO_PAROLA = process.env.JIRA_SIM_PO_PASSWORD ?? ENV.JIRA_SIM_PO_PASSWORD ?? "";
// tp_rehearsal.env ile aynı kural: adı sır kalıbına uyan, ≥6 karakterli her .env değeri maskelenir.
const SIR_KALIBI = /(PASSWORD|PASSWD|TOKEN|SECRET|_KEY|PRIVATE)/i;
const SIRLAR = [
  PAROLA,
  PO_PAROLA,
  ...Object.entries({ ...ENV, ...process.env })
    .filter(([k, v]) => SIR_KALIBI.test(k) && typeof v === "string" && v.length >= 6)
    .map(([, v]) => v as string),
].filter((v) => v.length > 0);
const gizle = (m: string) => maskele(m, SIRLAR);

type Adim = { no: number; ad: string; rol: string; sure_s: number; ekran: string; durum: "PASS" | "FAIL"; hata?: string };
const adimlar: Adim[] = [];
let sayac = 0;
let rolSimdi = "-";

/** Adım: süre ölçer, sonunda tam sayfa ekran görüntüsü alır; hata olursa da ekran alır. */
async function adim(page: Page, ad: string, fn: () => Promise<void>, ekranSayfasi?: () => Page) {
  const no = ++sayac;
  const dosya = `${String(no).padStart(2, "0")}-${ad
    .toLocaleLowerCase("tr-TR")
    .replace(/[çğıöşü]/g, (c) => ({ ç: "c", ğ: "g", ı: "i", ö: "o", ş: "s", ü: "u" })[c] ?? c)
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60)}.png`;
  const t0 = Date.now();
  await test.step(`${no}. ${ad}`, async () => {
    try {
      await fn();
      await (ekranSayfasi?.() ?? page).waitForLoadState("networkidle").catch(() => undefined);
      if (TEMPO_MS > 0) await (ekranSayfasi?.() ?? page).waitForTimeout(TEMPO_MS);
      await (ekranSayfasi?.() ?? page).screenshot({ path: join(RAPOR, "ekranlar", dosya), fullPage: true });
      adimlar.push({ no, ad, rol: rolSimdi, sure_s: (Date.now() - t0) / 1000, ekran: dosya, durum: "PASS" });
    } catch (e) {
      await (ekranSayfasi?.() ?? page).screenshot({ path: join(RAPOR, "ekranlar", dosya), fullPage: true }).catch(() => undefined);
      adimlar.push({ no, ad, rol: rolSimdi, sure_s: (Date.now() - t0) / 1000, ekran: dosya, durum: "FAIL", hata: String(e).slice(0, 400) });
      throw e;
    }
  });
}

function raporYaz() {
  const basarili = adimlar.length > 0 && adimlar.every((a) => a.durum === "PASS");
  const satirlar = [
    `# Arayüz provası (${KIP}) — ${basarili ? "BAŞARILI" : "BAŞARISIZ"}`,
    "",
    KIP === "tur"
      ? "Salt okuma turu: tamamlanmış demonun ekranları rol rol gezildi (yığın değiştirilmedi)."
      : "Canlı: sunucunun eylemleri portal ve jira-sim arayüzünden yapıldı.",
    "Model çıktıları REPLAY (kayıtlı/hazırlanmış; canlı model değil). Video: `video/` (Playwright, .webm).",
    "",
    "| # | Adım | Rol | Sonuç | Süre | Ekran |",
    "|---|---|---|---|---|---|",
    ...adimlar.map(
      (a) =>
        `| ${a.no} | ${a.ad} | ${a.rol} | ${a.durum === "PASS" ? "✅ PASS" : "❌ FAIL"} | ${a.sure_s.toFixed(1)} sn | [${a.ekran}](ekranlar/${a.ekran}) |`,
    ),
  ];
  const hatali = adimlar.filter((a) => a.hata);
  if (hatali.length) satirlar.push("", "## Hatalar", "", ...hatali.map((a) => `- ${a.no} ${a.ad}: ${a.hata}`));
  if (izleyiciDurumu !== "-") satirlar.push("", `Demo uygulaması izleyicisi (demo-web-sync --watch): ${izleyiciDurumu}. Günlük: \`izleyici.log\`.`);
  writeFileSync(join(RAPOR, "rapor.md"), gizle(satirlar.join("\n") + "\n"));
  writeFileSync(join(RAPOR, "rapor.json"), gizle(JSON.stringify({ kip: KIP, basarili, adimlar }, null, 2)) + "\n");
  if (izleyiciGunlugu.length) writeFileSync(join(RAPOR, "izleyici.log"), gizle(izleyiciGunlugu.join("")));
}

// ------------------------------------------------------------------ demo-web-sync --watch (sahne yolu)

let izleyici: ChildProcess | null = null;
let izleyiciDurumu = "-";
const izleyiciGunlugu: string[] = [];

/** Sunucunun sunum boyunca açık tuttuğu izleyiciyi başlatır; zaten çalışıyorsa ikincisini açmaz. */
function izleyiciBaslat() {
  try {
    const var_ = execFileSync("pgrep", ["-f", "demo-web-sync.sh --watch"], { encoding: "utf-8" }).trim();
    if (var_) {
      izleyiciDurumu = "host'ta zaten çalışıyordu (yeniden başlatılmadı)";
      return;
    }
  } catch {
    /* pgrep 1 = süreç yok */
  }
  izleyici = spawn(join(REPO, "scripts", "demo-web-sync.sh"), ["--watch"], {
    cwd: REPO,
    detached: true, // süreç grubu: durdururken docker build alt süreçleri de biter
    stdio: ["ignore", "pipe", "pipe"],
  });
  const yaz = (d: Buffer) => izleyiciGunlugu.push(String(d));
  izleyici.stdout?.on("data", yaz);
  izleyici.stderr?.on("data", yaz);
  izleyici.on("exit", (kod) => {
    izleyiciGunlugu.push(`\n[izleyici çıktı: ${kod}]\n`);
    izleyici = null;
  });
  izleyiciDurumu = "prova tarafından başlatıldı";
}

function izleyiciDurdur() {
  if (izleyici?.pid) {
    try {
      process.kill(-izleyici.pid, "SIGTERM");
    } catch {
      /* zaten çıktı */
    }
  }
  izleyici = null;
}
process.on("exit", izleyiciDurdur);

/** Uygulanan son yenileme isteği (/forge/demo-web-refresh.done; demo-web-sync yazar). */
function yenilemeUygulandi(): string {
  try {
    return execFileSync("docker", ["compose", "exec", "-T", "core-worker", "sh", "-c", "cat /forge/demo-web-refresh.done 2>/dev/null || true"], {
      cwd: REPO,
      encoding: "utf-8",
      timeout: 30_000,
    }).trim();
  } catch {
    return "";
  }
}

// ------------------------------------------------------------------ yardımcılar

async function giris(page: Page, rol: string) {
  if (rolSimdi !== "-" && rolSimdi !== rol) {
    await page.getByRole("button", { name: "Çıkış" }).click();
    await expect(page).toHaveURL(/\/giris/);
  }
  await page.goto("/giris");
  await page.getByLabel("Kullanıcı adı").fill(rol);
  await page.getByLabel("Parola").fill(PAROLA);
  await page.getByRole("button", { name: "Giriş yap" }).click();
  await expect(page.getByRole("navigation", { name: "Ana menü" })).toBeVisible();
  await expect(page.locator(".kullanici-ad")).toHaveText(rol);
  rolSimdi = rol;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type J = any;

async function api(page: Page, yol: string): Promise<J> {
  const r = await page.request.get(`/api${yol}`);
  expect(r.ok(), `GET /api${yol} → ${r.status()}`).toBe(true);
  return r.json();
}

/** `api` gibi; 404 (kayıt henüz oluşmadı, ör. arayüzün POST'u bitmeden) → null. */
async function apiYaDaNull(page: Page, yol: string): Promise<J | null> {
  const r = await page.request.get(`/api${yol}`);
  if (r.status() === 404) return null;
  expect(r.ok(), `GET /api${yol} → ${r.status()}`).toBe(true);
  return r.json();
}

/** `fn()` doğru değer dönene kadar API'yi yoklar. */
async function bekle<T>(aciklama: string, fn: () => Promise<T | null | undefined | false>, ms: number, aralik = 3000): Promise<T> {
  const t0 = Date.now();
  for (;;) {
    const v = await fn();
    if (v) return v as T;
    if (Date.now() - t0 > ms) throw new Error(`zaman aşımı (${Math.round(ms / 1000)} sn): ${aciklama}`);
    await new Promise((r) => setTimeout(r, aralik));
  }
}

async function tpd1(page: Page): Promise<J> {
  const liste: J[] = await api(page, "/requirements");
  const r = liste.find((x) => x.jira_key === "TPD-1");
  expect(r, "TPD-1 portalda yok").toBeTruthy();
  return api(page, `/requirements/${r.id}`);
}

async function scriptBul(page: Page, sira: number): Promise<J | null> {
  const liste: J[] = await api(page, "/scripts");
  const ad = liste.filter((s) => s.case_ref === `TPD-1-C${sira}` && s.durum !== "closed");
  if (!ad.length) return null;
  ad.sort((a, b) => String(b.olusturma).localeCompare(String(a.olusturma)));
  return api(page, `/scripts/${ad[0].id}`);
}

/** REPLAY dürüstlüğü: sahte "canlı" yok, örnek veri yok. */
async function durustluk(page: Page) {
  await expect(page.getByText("ÖRNEK VERİ")).toHaveCount(0);
  await expect(page.getByText(/^live$|^CANLI$/)).toHaveCount(0);
}

async function locatorHatasi(page: Page): Promise<J | null> {
  const kosular: J[] = await api(page, "/runs?tetik=push&limit=50");
  const kirmizi = kosular.find((k) => k.durum === "failed" && [19, 22].includes(k.basarisiz));
  if (!kirmizi) return null;
  const hatalar: J[] = await api(page, `/failures?run_id=${kirmizi.id}&limit=200`);
  return hatalar.find((h) => h.sinif === "test_maintenance") ?? null;
}

// ------------------------------------------------------------------ testler

test.beforeAll(() => {
  if (!PAROLA) throw new Error("SEED_USER_PASSWORD yok (.env ya da ortam)");
});
test.afterAll(() => {
  izleyiciDurdur();
  raporYaz();
});

// Yalnızca seçili kip tanımlanır (atlanan test boş video bırakmasın).
const turTesti = KIP === "tur" ? test : test.skip;
const canliTesti = KIP === "canli" ? test : test.skip;

turTesti("tur: tamamlanmış demo akışının ekranları (salt okuma)", async ({ page, context }) => {
  const hatalar: string[] = [];
  page.on("pageerror", (e) => hatalar.push(String(e)));

  await adim(page, "Analist: gereksinimler (Jira'dan çekilen story'ler)", async () => {
    await giris(page, "analist");
    await page.goto("/gereksinimler");
    await expect(page.getByRole("row").filter({ hasText: "TPD-1" }).first()).toBeVisible();
    await durustluk(page);
  });
  const req = await tpd1(page);
  await adim(page, "TPD-1: ön inceleme, kanıtlı bulgular ve kararlar", async () => {
    await page.goto(`/gereksinimler/${req.id}`);
    await expect(page.locator(".baslik-anahtar")).toHaveText("TPD-1");
    await expect(page.getByText(/^REPLAY$/).first()).toBeVisible();
    await durustluk(page);
  });
  await adim(page, "Case review: 10 onaylı case", async () => {
    await page.goto(`/gereksinimler/${req.id}/caseler`);
    await expect(page.getByText(/6 adet kampanyalı üründe bedava ürün verilmez/).first()).toBeVisible();
    // Baz değer kaynağı etiketli; ölçüm yoksa (ya da REPLAY'de review betik hızında) kazanç uydurulmaz.
    const baz = page.getByTestId("case-baz");
    await expect(baz).toContainText(/Ölçüm|Varsayılan|Ölçülmedi/);
    const olcum = /Ölçüm/.test((await baz.textContent()) ?? "");
    if (!olcum) {
      await expect(page.getByTestId("case-kazanc")).toContainText("—");
      // Eski sabit "F0 ölçümü" etiketi ölçüm yokken görünmemeli.
      await expect(page.getByText("F0 ölçümü", { exact: false })).toHaveCount(0);
    }
  });
  await adim(page, "Yayın: Jira Test issue'ları", async () => {
    await page.goto(`/gereksinimler/${req.id}/yayin`);
    await expect(page.getByText(/TPD-\d+/).first()).toBeVisible();
  });
  const jira = await context.newPage();
  await adim(
    page,
    "jira-sim: TPD-1 (PO onayı, Test bağlantıları)",
    async () => {
      await jira.goto(`${JIRA}/browse/TPD-1`);
      await expect(jira.getByText("tp-po-approved").first()).toBeVisible();
    },
    () => jira,
  );

  await adim(page, "Mühendis: üretilen testler", async () => {
    await giris(page, "muhendis");
    await page.goto("/kod");
    await expect(page.getByRole("region", { name: "Üretilen testler tablosu" })).toBeVisible();
    await durustluk(page);
  });
  const c2 = await scriptBul(page, 2);
  await adim(page, "C2: kırarak doğrulama (yeşil → kırmızı → yeşil) ve merge", async () => {
    expect(c2, "C2 script'i yok").toBeTruthy();
    await page.goto(`/kod/${c2.id}`);
    await expect(page.getByTestId("replay-bandi").or(page.getByText("REPLAY", { exact: true })).first()).toBeVisible();
    await expect(page.getByRole("region", { name: "Eşlenen adımlar tablosu" })).toBeVisible();
  });
  const c3 = await scriptBul(page, 3);
  await adim(page, "C3: defect adayı (6 adet → beklenen 0, gerçekleşen 1)", async () => {
    expect(c3, "C3 script'i yok").toBeTruthy();
    await page.goto(`/kod/${c3.id}`);
    await expect(page.getByTestId("yerel-sinif")).toContainText("Defect adayı");
  });

  await adim(page, "Sunucu: koşular (push / deploy / nightly)", async () => {
    await giris(page, "sunucu");
    await page.goto("/kosular");
    await expect(page.getByRole("region", { name: "Koşular tablosu" })).toBeVisible();
  });
  await adim(page, "Kontrol Kulesi", async () => {
    await page.goto("/kontrol-kulesi");
    await expect(page.getByTestId("gecme-orani")).toBeVisible();
    await durustluk(page);
  });

  await adim(page, "Testçi: bug taslakları", async () => {
    await giris(page, "testci");
    await page.goto("/bug-taslaklari");
    await expect(page.getByRole("heading", { name: "Bug taslakları", level: 1 })).toBeVisible();
  });
  const c3Hata: J | null = c3?.failure_id ? await api(page, `/failures/${c3.failure_id}`) : null;
  const c3Taslak = c3Hata?.oneri?.bug_draft_id ?? c3Hata?.bug_draft_id;
  await adim(page, "C3 bug taslağı: TPD-5 kaydına bağlandı", async () => {
    expect(c3Taslak, "C3 bug taslağı yok").toBeTruthy();
    await page.goto(`/bug-taslaklari/${c3Taslak}`);
    await expect(page.getByTestId("yayin-sonucu")).toContainText("TPD-5");
  });
  const taslaklar: J[] = await api(page, "/bug-drafts");
  const f4 = taslaklar.find((t) => t.kaynak === "consistency" && /Kredi limiti/i.test(t.icerik?.summary ?? t.icerik?.ozet ?? JSON.stringify(t.icerik)));
  await adim(page, "F4 bug taslağı: yeni Bug (mükerrer adayı yok)", async () => {
    expect(f4, "F4 taslağı yok").toBeTruthy();
    await page.goto(`/bug-taslaklari/${f4.id}`);
    await expect(page.getByTestId("yayin-sonucu")).toBeVisible();
  });
  await adim(
    page,
    "jira-sim: TPD-5 (kanıt yorumları, bağlantılar)",
    async () => {
      await jira.goto(`${JIRA}/browse/TPD-5`);
      await expect(jira.getByText("TPD-1").first()).toBeVisible();
    },
    () => jira,
  );

  const lh = await locatorHatasi(page);
  await adim(page, "Mühendis: locator triage ve onarım PR'ı", async () => {
    await giris(page, "muhendis");
    expect(lh, "locator kırılması koşusu yok (make demo-break yapılmamış)").toBeTruthy();
    await page.goto(`/hatalar/${lh.id}`);
    await expect(page.getByTestId("triage-sinif")).toBeVisible();
    await expect(page.getByLabel("Onarım yaması").or(page.getByText("cart-add")).first()).toBeVisible();
  });
  await adim(page, "Sunucu: demo kontrolleri (locator onarıldı)", async () => {
    await giris(page, "sunucu");
    await page.goto("/demo");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });
  await adim(page, "Denetim kaydı (hash zinciri)", async () => {
    await page.goto("/denetim");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });
  expect(hatalar).toEqual([]);
});

canliTesti("canlı: 14 adım + locator kırma/onarım arayüzden", async ({ page, context }) => {
  const hatalar: string[] = [];
  page.on("pageerror", (e) => hatalar.push(String(e)));

  // Sunucu sunum boyunca host'ta `make demo-web-sync A=--watch` açık tutar (DEMO-AKISI kurulum).
  izleyiciBaslat();

  // ---------------- Açılış (DEMO-AKISI: make reset + make demo-reset sonrası sayaç 0/14 tamam)
  await adim(page, "Sunucu: Açılış — Demo yol haritası 0/14 tamam, model kipi REPLAY", async () => {
    await giris(page, "sunucu");
    await page.goto("/yol-haritasi");
    const sayac = page.getByTestId("yh-ilerleme");
    await expect(sayac).toBeVisible();
    // Sunucu metni "0/14 tamam" der; başka bir sayı ortamın (ya da yol haritasının) açılışa hazır
    // olmadığını gösterir — sahnede söz tutmaz.
    await expect(sayac, "açılış sayacı DEMO-AKISI'nın sözüyle uyuşmuyor").toContainText(/^\s*0\/14\s+tamam/);
    await expect(page.getByText(/REPLAY/).first()).toBeVisible();
  });

  // ---------------- Demo-A
  await adim(page, "Analist: Jira'dan çek (TPD-1)", async () => {
    await giris(page, "analist");
    await page.goto("/gereksinimler");
    const satir = page.getByRole("row").filter({ hasText: "TPD-1" }).first();
    if (!(await satir.isVisible().catch(() => false))) {
      await page.getByRole("button", { name: "Jira'dan çek" }).click();
      await expect(async () => {
        await page.reload();
        await expect(page.getByRole("row").filter({ hasText: "TPD-1" }).first()).toBeVisible({ timeout: 2_000 });
      }).toPass({ timeout: 60_000 });
    }
  });
  let req = await tpd1(page);
  expect(req.durum, "temiz başlangıç değil (make reset)").toBe("new");
  await adim(page, "Ön inceleme: 4 doğrulanmış bulgu (REPLAY)", async () => {
    await page.goto(`/gereksinimler/${req.id}`);
    await page.getByRole("button", { name: "Ön incelemeyi başlat" }).click();
    const kartlar = page.locator("article.bulgu");
    await expect(kartlar).toHaveCount(4, { timeout: 120_000 });
    await expect(page.locator("article.bulgu .rozet-dogrulandi")).toHaveCount(4);
    await expect(page.getByText(/^REPLAY$/).first()).toBeVisible();
    await durustluk(page);
  });
  await adim(page, "Kararlar: F1/F3 dokümanı düzelt, F2/F4 kod hatalı", async () => {
    const kartlar = page.locator("article.bulgu");
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
  });
  await adim(page, "Düzeltmeleri Jira'ya yaz → 2. tur → PO teyidi bekleniyor", async () => {
    await page.getByRole("button", { name: /Düzeltmeleri Jira'ya yaz/ }).click();
    await expect(page.getByText("PO teyidi bekliyor").first()).toBeVisible({ timeout: 120_000 });
  });
  const jira = await context.newPage();
  await adim(
    page,
    "PO (jira-sim): soruları gördü, tp-po-approved",
    async () => {
      rolSimdi = "po";
      expect(PO_PAROLA, "JIRA_SIM_PO_PASSWORD yok").toBeTruthy();
      await jira.goto(`${JIRA}/giris?sonra=/browse/TPD-1`);
      await jira.locator("#po-parola").fill(PO_PAROLA);
      await jira.getByRole("button", { name: "Giriş yap" }).click();
      await expect(jira.getByText("tp-po-pending").first()).toBeVisible();
      await jira.getByTestId("po-onayla").click();
      await expect(jira.getByText("tp-po-approved").first()).toBeVisible();
    },
    () => jira,
  );
  rolSimdi = "analist";
  await adim(page, "Case üretimi (10 case)", async () => {
    await expect(async () => {
      await page.reload();
      await expect(page.getByRole("button", { name: "Case üret" })).toBeEnabled({ timeout: 2_000 });
    }).toPass({ timeout: 90_000 });
    await page.getByRole("button", { name: "Case üret" }).click();
    await expect(page.getByRole("link", { name: "Case review" })).toBeVisible({ timeout: 120_000 });
  });
  await adim(page, "QA: 10 case onayı", async () => {
    await page.getByRole("link", { name: "Case review" }).click();
    const onayla = page.getByRole("button", { name: "Onayla", exact: true });
    await expect(onayla.first()).toBeVisible({ timeout: 30_000 });
    for (let i = 0; i < 20 && (await onayla.count()) > 0; i++) {
      const n = await onayla.count();
      await onayla.first().click();
      await expect(onayla).toHaveCount(n - 1, { timeout: 15_000 });
    }
  });
  await adim(page, "Yayın: önizleme → Jira Test issue'ları", async () => {
    await page.getByRole("link", { name: "Yayın önizleme" }).first().click();
    await page.getByRole("button", { name: /Seçilenleri yayınla/ }).click();
    await expect(page.getByTestId("yayin-ozeti")).toContainText(/10 oluşturuldu/, { timeout: 90_000 });
    await expect(page.getByTestId("yayin-ozeti")).toContainText("0 başarısız");
  });

  // ---------------- Demo-B
  await adim(page, "Mühendis: C1/C2/C3/C5 için kod üret", async () => {
    await giris(page, "muhendis");
    await page.goto("/kod");
    await expect(page.getByRole("checkbox").first()).toBeVisible({ timeout: 30_000 });
    for (const ad of [
      /Sepete ekle ile ürün sepete eklenir ve sepet sayacı artar/,
      /7 adet kampanyalı üründe 1 adet bedava verilir/,
      /6 adet kampanyalı üründe bedava ürün verilmez/,
      /Kampanyasız siparişte minimum tutarın altında uyarı gösterilir/,
    ]) {
      await page.getByRole("checkbox", { name: ad }).first().check();
    }
    await page.getByRole("button", { name: /Seçilenler için kod üret \(4\)/ }).click();
    await bekle(
      "4 script bitti",
      async () => {
        const s = await Promise.all([1, 2, 3, 5].map((n) => scriptBul(page, n)));
        return s.every((x) => x && !["pending", "queued", "generating", "verifying", "mapping", "checking"].includes(x.durum)) && s;
      },
      9 * 60_000,
    );
    await page.reload();
  });
  const sc: Record<number, J> = {};
  for (const n of [1, 2, 3, 5]) sc[n] = await scriptBul(page, n);
  await adim(page, "C3: defect adayı (PR açılmaz)", async () => {
    await page.goto(`/kod/${sc[3].id}`);
    await expect(page.getByTestId("yerel-sinif")).toContainText("Defect adayı");
  });
  for (const n of [2, 1, 5]) {
    await adim(page, `C${n}: kırarak doğrula`, async () => {
      await page.goto(`/kod/${sc[n].id}`);
      await page.getByRole("button", { name: /^(Kırarak doğrula|Yeniden doğrula)$/ }).last().click();
      await bekle(
        `C${n} kırma bitti`,
        async () => {
          const d = await api(page, `/scripts/${sc[n].id}`);
          return !["not_started", "running", "queued"].includes(d.break_verify.durum) && d;
        },
        5 * 60_000,
        5000,
      );
      await page.reload();
      if (n === 2) await expect(page.getByText("Test hata yakalıyor ✓").first()).toBeVisible();
    });
  }
  for (const n of [2, 1, 5]) {
    await adim(page, `C${n}: merge (insan onayı)`, async () => {
      await page.goto(`/kod/${sc[n].id}`);
      await bekle(
        `C${n} merge kapısı açık`,
        async () => {
          const d = await api(page, `/scripts/${sc[n].id}`);
          const checks = (d.pr?.checks ?? []).map((c: J) => c.durum);
          return d.pr?.durum === "open" && !d.pr?.dal?.geride && checks.length === 1 && checks[0] === "passed" && d.merge_engelleri.length === 0 && d;
        },
        5 * 60_000,
        4000,
      );
      await page.reload();
      // isVisible() beklemez: yeniden yüklemeden sonra veri gelmeden uyarı bloğu yoktur. Kapının
      // "açık ✓" görünmesi (uyarılarla aynı veri) beklenir, sonra uyarı varsa açık kabul verilir.
      await expect(page.locator(".ok-metin", { hasText: "açık ✓" }).first()).toBeVisible({ timeout: 30_000 });
      const kabul = page.getByTestId("merge-uyarilari").getByRole("checkbox");
      if ((await kabul.count()) > 0) await kabul.check(); // zayıf test: açık kabul
      await expect(page.getByRole("button", { name: "Merge et" })).toBeEnabled({ timeout: 15_000 });
      await page.getByRole("button", { name: "Merge et" }).click();
      await expect(page.locator(".sayfa-basligi").getByText("Birleştirildi")).toBeVisible({ timeout: 90_000 });
    });
  }

  await adim(page, "Sunucu: deploy + gece koşusu", async () => {
    await giris(page, "sunucu");
    await page.goto("/kosular");
    await page.getByRole("button", { name: "Deploy sonrası testleri koş" }).click();
    await expect(page.getByText(/kuyruğa alındı|zaten kuyrukta/).first()).toBeVisible();
    await page.getByRole("button", { name: "Gece koşusunu şimdi başlat" }).click();
    await bekle(
      "deploy + nightly bitti",
      async () => {
        const k: J[] = await api(page, "/runs?limit=20");
        const d = k.find((x) => x.tetik === "deploy");
        const g = k.find((x) => x.tetik === "nightly");
        return d && g && !["queued", "running"].includes(d.durum) && !["queued", "running"].includes(g.durum) && [d, g];
      },
      8 * 60_000,
      5000,
    );
    await page.reload();
  });
  await adim(page, "Koşu detayı: yerel Chromium (Sauce kimliği yok), HTML + JUnit + Allure açılıyor", async () => {
    const k: J[] = await api(page, "/runs?limit=20");
    const d = k.find((x) => x.tetik === "deploy");
    expect(d, "deploy koşusu yok").toBeTruthy();
    await page.goto(`/kosular/${d.id}`);
    // Adım 9 dürüst notu: Sauce kimliği yokken koşu yerel Chromium'dur, sahte Sauce bağlantısı yok.
    if (d.kaynak !== "sauce") {
      await expect(page.getByText("Yerel Chromium").first()).toBeVisible();
      await expect(page.getByRole("link", { name: /Sauce Labs videosu/ })).toHaveCount(0);
    }
    // Adım 10: rapor bağlantıları sahnede açılmalı (kırık link sahnede bulunmasın).
    for (const ad of [/^Playwright HTML raporu/, /^JUnit XML/, /^Allure raporu/]) {
      const link = page.getByRole("link", { name: ad }).first();
      await expect(link, `${ad} bağlantısı yok`).toBeVisible();
      const href = await link.getAttribute("href");
      expect(href, `${ad} href yok`).toBeTruthy();
      const r = await page.request.get(href!);
      expect(r.status(), `${ad} → HTTP ${r.status()}`).toBe(200);
    }
  });
  await adim(page, "Kontrol Kulesi", async () => {
    await page.goto("/kontrol-kulesi");
    await expect(page.getByTestId("gecme-orani")).toBeVisible();
    await durustluk(page);
  });

  // ---------------- Faz 4: bug
  await giris(page, "testci");
  // Adım 12: sunucu C3 script'inden triage sayfasını gösterir.
  await adim(page, "Testçi: C3 → triage sayfası (ürün hatası, kural, TPD-5 adayı)", async () => {
    await page.goto(`/kod/${sc[3].id}`);
    await page.getByRole("link", { name: "Triage sonucu ve bug taslağı" }).click();
    await expect(page).toHaveURL(/\/hatalar\//);
    await expect(page.getByTestId("triage-sinif")).toContainText("Ürün hatası");
    await expect(page.getByTestId("triage-sinif")).toContainText(/Karar kaynağı: (deterministik )?kural/);
    await expect(page.getByText("TPD-5").first()).toBeVisible({ timeout: 60_000 });
    await durustluk(page);
  });
  const c3 = await api(page, `/scripts/${sc[3].id}`);
  const c3Hata = await api(page, `/failures/${c3.failure_id}`);
  const taslaklar: J[] = await api(page, "/bug-drafts");
  const f2 = taslaklar.find((t) => t.kaynak === "consistency" && t.oneri?.link_key === "TPD-5");
  const f4 = taslaklar.find((t) => t.kaynak === "consistency" && t.oneri?.recommendation === "new");
  for (const [ad, id, bagla] of [
    ["C3 → TPD-5 kaydına bağla", c3Hata.oneri?.bug_draft_id ?? c3Hata.bug_draft_id, true],
    ["F2 → TPD-5 kaydına bağla", f2?.id, true],
    ["F4 → Onayla ve Jira'da aç (yeni Bug)", f4?.id, false],
  ] as const) {
    await adim(page, `Testçi: ${ad}`, async () => {
      expect(id, `${ad}: taslak yok`).toBeTruthy();
      await page.goto(`/bug-taslaklari/${id}`);
      await expect(page.getByText("Jira'da benzer açık bug'lar aranıyor…")).toHaveCount(0, { timeout: 60_000 });
      if (bagla) await page.getByRole("button", { name: "TPD-5 kaydına bağla" }).click();
      else await page.getByRole("button", { name: "Onayla ve Jira'da aç" }).click();
      await expect(page.getByTestId("yayin-sonucu")).toBeVisible({ timeout: 60_000 });
      await expect(page.getByTestId("yayin-sonucu").getByRole("link").first()).toHaveAttribute("href", /\/browse\/TPD-\d+$/);
    });
  }

  // ---------------- Faz 4: locator
  await adim(page, "Sunucu: Demo kontrolleri → Buton kimliğini değiştir (izleyici uygulamayı yeniden kurar)", async () => {
    await giris(page, "sunucu");
    await bekle("CI boşta", async () => !(await api(page, "/runs?limit=30")).some((k: J) => ["queued", "running"].includes(k.durum)), 8 * 60_000, 5000);
    const eskiIstek = (await api(page, "/demo/status")).web_yenileme_istegi?.istek_id ?? null;
    await page.goto("/demo");
    await expect(page.getByRole("heading", { name: "Demo kontrolleri", level: 1 })).toBeVisible();
    await page.getByRole("button", { name: "Buton kimliğini değiştir", exact: true }).click();
    await expect(page.getByRole("group", { name: "Buton kimliği değiştirme onayı" })).toBeVisible();
    await page.getByRole("button", { name: "Evet, buton kimliğini değiştir" }).click();
    const istek: J = await bekle(
      "kırma için yenileme isteği yazıldı",
      async () => {
        const i = (await api(page, "/demo/status")).web_yenileme_istegi;
        return i && i.eylem === "break" && i.istek_id !== eskiIstek && i;
      },
      2 * 60_000,
      2000,
    );
    // Sahnenin en kırılgan devri: düğme → yenileme isteği → host'taki --watch izleyici → demo.await_web.
    await bekle("izleyici isteği uyguladı (/forge/demo-web-refresh.done)", async () => yenilemeUygulandi() === istek.istek_id, 8 * 60_000, 3000);
    const d: J = await bekle(
      "uygulama kırık main'i yansıtıyor",
      async () => {
        const x = await api(page, "/demo/status");
        return x.locator_durumu === "kirik" && x.uygulama?.main_ile_eslesiyor === true && x;
      },
      3 * 60_000,
      3000,
    );
    expect(d.forge?.testid).toBe("cart-add");
    await expect(page.getByRole("list", { name: "Locator kırılması ilerlemesi" })).toBeVisible();
    await expect(page.getByText("Demo uygulaması hâlâ yeniden kurulmadı")).toHaveCount(0);
  });
  const lh = await adim(page, "Push CI kırmızı → triage test_maintenance/locator", async () => {
    await page.goto("/kosular");
    await bekle("locator triage", () => locatorHatasi(page), 8 * 60_000, 5000);
    await page.reload();
  }).then(() => locatorHatasi(page));
  await adim(page, "Mühendis: Onarım PR'ı aç", async () => {
    await giris(page, "muhendis");
    await page.goto(`/hatalar/${lh.id}`);
    await page.getByRole("button", { name: "Onarım PR'ı aç" }).click();
    // Düğme POST'u arayüzde eşzamansız: onarım kaydı oluşana kadar GET /fix 404 döner.
    await bekle("onarım PR'ı açık", async () => (await apiYaDaNull(page, `/failures/${lh.id}/fix`))?.durum === "pr_open", 4 * 60_000);
    await page.reload();
    await expect(page.getByLabel("Onarım yaması")).toContainText("cart-add");
  });
  await adim(page, "Mühendis: onarımı onayla ve merge et", async () => {
    await expect(page.getByRole("button", { name: "Onarımı onayla ve merge et" })).toBeEnabled({ timeout: 3 * 60_000 });
    await page.getByRole("button", { name: "Onarımı onayla ve merge et" }).click();
    await bekle("onarım merged", async () => (await api(page, `/failures/${lh.id}/fix`)).durum === "merged", 2 * 60_000);
    await page.reload();
    await expect(page.getByText(/Onarım birleşti/)).toBeVisible();
  });
  await adim(page, "Sunucu: push CI yeşil, Kontrol Kulesi", async () => {
    await giris(page, "sunucu");
    const fix = await api(page, `/failures/${lh.id}/fix`);
    await bekle(
      "onarım push CI'ı yeşil",
      async () => {
        const k: J[] = await api(page, "/runs?tetik=push&limit=10");
        const r = k.find((x) => x.commit === fix.pr?.merge_sha);
        return r && r.durum === "passed" && r;
      },
      5 * 60_000,
      5000,
    );
    await page.goto("/kontrol-kulesi");
    await expect(page.getByTestId("gecme-orani")).toBeVisible();
  });
  await adim(page, "Sunucu: Denetim kaydı → zinciri yeniden doğrula", async () => {
    await page.goto("/denetim");
    await page.getByRole("button", { name: "Zinciri yeniden doğrula" }).click();
    await expect(page.getByText("✓ Zincir doğrulandı")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("✗ Zincir kırık")).toHaveCount(0);
  });
  req = await tpd1(page);
  expect(hatalar).toEqual([]);
});
