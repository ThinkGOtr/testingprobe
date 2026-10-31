// Ortak test fikstürleri.
// - Her paralel işçi kendi bayi kullanıcısını kullanır (parallelIndex → bayi1/bayi2).
// - Veri yalıtımı iki moddan biriyle sağlanır (bkz. ../playwright.config.ts):
//   * sıfırlama (varsayılan): her testten önce yalnızca o bayinin sepeti, siparişleri ve demo
//     kırılması /test/reset ile silinir. Paylaşılan token ister (DEMOAPP_TEST_TOKEN →
//     X-Demoapp-Test-Token). webServer modunda token'ı playwright.config.ts üretir; çalışan bir
//     ortama (BASE_URL) karşı token ve API adresi (DEMO_API_URL, ör. http://demo-app-api:8000)
//     dışarıdan verilir — web nginx'i /api/test/ yolunu dışarı açmaz.
//   * yalnızca sepet (TP_E2E_NO_RESET=1, token yok): test uçları kullanılmaz; bayinin sepeti
//     herkese açık API ile (giriş + DELETE /cart) boşaltılır. Sipariş geçmişi silinemediği için
//     @sifir-veri etiketli testler config'te dışlanır.
// - BREAK_CAMPAIGN=1: "kırarak doğrula". Yalnızca bu koşunun bayisi için kampanya kuralı
//   POST /test/break ile bozulur, test sonunda geri alınır (token gerekir). Paylaşılan uygulama
//   örneği, diğer bayiler ve playwright-mcp etkilenmez.
// - `signedIn` istenirse bayi API üzerinden oturum açar (çerez sayfa bağlamıyla paylaşılır).
// - `dealerUsername` (test.use ile, isteğe bağlı): testi işçinin bayisi yerine belirli bir e2e
//   bayisine sabitler (ör. case metni "bayi2 / Demo123!" ile giriş yapıp bayiye özgü değer
//   doğruluyorsa). Aynı bayi iki işçide aynı anda kullanılmasın diye her test, bayisini süreçler
//   arası bir kilitle (dosya) alır ve bırakır; sabitlenmemiş testler de aynı kilidi kullanır.
import { test as base, expect, type APIRequestContext, type TestInfo } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { CartPage, CatalogPage, LoginPage, OrderPage } from "../pages";

export interface Dealer {
  username: string;
  password: string;
  name: string;
}

/** e2e bayi kullanıcıları (paralel işçi başına bir bayi). */
export const DEALERS: readonly Dealer[] = [
  { username: "bayi1", password: "Demo123!", name: "Merkez Bayi" },
  { username: "bayi2", password: "Demo123!", name: "Sahil Bayi" },
];

/** Doğrulama ajanının (playwright-mcp) bayisi; e2e testleri bu bayiyi kullanamaz ve sıfırlamaz. */
export const AGENT_DEALER = "bayi3";

/** Testin bayisi: `dealerUsername` verilmişse o, yoksa paralel işçinin bayisi. */
export function pickDealer(dealerUsername: string | undefined, parallelIndex: number): Dealer {
  if (dealerUsername !== undefined) {
    const pinned = DEALERS.find((d) => d.username === dealerUsername);
    if (!pinned) {
      const reserved = dealerUsername === AGENT_DEALER ? " (doğrulama ajanına ayrılmıştır)" : "";
      throw new Error(
        `dealerUsername '${dealerUsername}' bir e2e bayisi değil${reserved}; izinli: ${DEALERS.map((d) => d.username).join(", ")}`,
      );
    }
    return pinned;
  }
  const dealer = DEALERS[parallelIndex];
  if (!dealer) {
    throw new Error(
      `En fazla ${DEALERS.length} paralel işçi desteklenir (bayi kullanıcısı sayısı); --workers değerini düşürün.`,
    );
  }
  return dealer;
}

const LOCK_POLL_MS = 25;
const LOCK_WAIT_MS = 40_000;

function lockDir(testInfo: TestInfo): string {
  // Aynı uygulamaya (web + API adresi) karşı koşan işçiler aynı kilit dizinini paylaşır.
  const target = `${String(testInfo.project.use.baseURL)}|${process.env.DEMO_API_URL ?? ""}`;
  return join(tmpdir(), `demoapp-e2e-kilit-${createHash("sha256").update(target).digest("hex").slice(0, 12)}`);
}

function ownerOf(path: string): string | undefined {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return undefined;
  }
}

/** Kilit dosyasının sahibi süreç ölmüşse (çökmüş işçi) dosyayı kaldırır. */
function clearIfStale(path: string): void {
  const owner = ownerOf(path);
  if (!owner) return;
  try {
    process.kill(Number(owner.split(":")[0]), 0);
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ESRCH" && ownerOf(path) === owner) rmSync(path, { force: true });
  }
}

function tryCreate(path: string, owner: string): boolean {
  try {
    writeFileSync(path, owner, { flag: "wx" });
    return true;
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "EEXIST") return false;
    throw err;
  }
}

/**
 * Bayiyi bu test için özel alır (süreçler arası dosya kilidi). Bekleyen süreç `.sira` dosyasıyla
 * sırasını işaretler; kilidi bırakan işçi sıradaki varken kilidi yeniden alamaz (açlık yok).
 * Dönen fonksiyon kilidi bırakır.
 */
export async function acquireDealer(dir: string, username: string, waitMs = LOCK_WAIT_MS): Promise<() => void> {
  mkdirSync(dir, { recursive: true });
  const lock = join(dir, `${username}.kilit`);
  const queue = join(dir, `${username}.sira`);
  const me = `${process.pid}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
  const deadline = Date.now() + waitMs;
  let queued = false;
  for (;;) {
    const next = ownerOf(queue);
    if ((next === undefined || next === me) && tryCreate(lock, me)) {
      if (queued && ownerOf(queue) === me) rmSync(queue, { force: true });
      return () => {
        if (ownerOf(lock) === me) rmSync(lock, { force: true });
      };
    }
    clearIfStale(lock);
    clearIfStale(queue);
    if (!queued) queued = tryCreate(queue, me);
    if (Date.now() > deadline) {
      if (ownerOf(queue) === me) rmSync(queue, { force: true });
      throw new Error(`'${username}' bayisi ${waitMs / 1000} sn içinde serbest kalmadı (kilit: ${lock})`);
    }
    await new Promise((resolve) => setTimeout(resolve, LOCK_POLL_MS));
  }
}

/** "Kırarak doğrula": kampanya kuralı yalnızca bu koşunun bayileri için bozulur. */
export const BREAK_CAMPAIGN = process.env.BREAK_CAMPAIGN === "1";

type IsolationMode = { kind: "reset"; token: string } | { kind: "cart-only" };

/** Veri yalıtım modunu ortamdan seçer; geçersiz birleşimlerde açıklayıcı hatayla durur. */
export function isolationMode(env: NodeJS.ProcessEnv = process.env): IsolationMode {
  const token = env.DEMOAPP_TEST_TOKEN;
  if (token) return { kind: "reset", token };
  if (env.BREAK_CAMPAIGN === "1") {
    throw new Error(
      "BREAK_CAMPAIGN=1 için DEMOAPP_TEST_TOKEN gerekir (kırılma POST /test/break ile bayi kapsamında açılır).",
    );
  }
  if (env.TP_E2E_NO_RESET === "1") return { kind: "cart-only" };
  throw new Error(
    "DEMOAPP_TEST_TOKEN tanımlı değil; test verisi sıfırlanamaz. Çalışan bir ortama karşı ya token ile " +
      "DEMO_API_URL verin (ör. http://demo-app-api:8000) ya da yalnızca sepet yalıtımı için TP_E2E_NO_RESET=1 verin.",
  );
}

/**
 * /test/<path> ucunu çağırır: DEMO_API_URL verilmişse doğrudan API'ye, yoksa web vekili üzerinden.
 *
 * Bilerek Playwright'ın `request` fikstürüyle DEĞİL, Node `fetch` ile gönderilir: `request`
 * izlenir (trace: retain-on-failure) ve kırmızı testin trace.zip'i X-Demoapp-Test-Token başlığını
 * ve değerini kaydeder; bu dosyalar koşu artefaktı olarak core'dan servis edilir. Token yalnızca
 * demo-app-api ve test-runner'da bulunmalıdır (security-check 8). Bkz. tools/trace-token-selftest.js.
 */
export function testApiUrl(baseURL: string | undefined, path: string, apiUrl = process.env.DEMO_API_URL): string {
  if (apiUrl) return `${apiUrl.replace(/\/$/, "")}/test/${path}`;
  if (!baseURL) throw new Error("/test uçları için baseURL ya da DEMO_API_URL gerekir");
  return new URL(`/api/test/${path}`, baseURL).toString();
}

async function testApi(baseURL: string | undefined, token: string, path: string, data: object): Promise<void> {
  const resp = await fetch(testApiUrl(baseURL, path), {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Demoapp-Test-Token": token },
    body: JSON.stringify(data),
    signal: AbortSignal.timeout(10_000),
  });
  await resp.arrayBuffer();
  const hint =
    resp.status === 404
      ? " (uç kapalı: API'de DEMOAPP_TEST_MODE=1 + DEMOAPP_TEST_TOKEN yok ya da web vekili /api/test/ yolunu açmıyor; DEMO_API_URL verin)"
      : "";
  expect(resp.ok, `POST /test/${path} başarısız: ${resp.status}${hint}`).toBe(true);
}

/** Token olmadan: bayinin sepetini herkese açık API ile boşaltır; oturumu kapatır. */
async function clearCartViaPublicApi(request: APIRequestContext, dealer: Dealer): Promise<void> {
  const login = await request.post("/api/auth/login", {
    data: { kullanici_adi: dealer.username, parola: dealer.password },
  });
  expect(login.ok(), `sepet temizliği için giriş başarısız: ${login.status()}`).toBe(true);
  const clear = await request.delete("/api/cart");
  expect(clear.ok(), `sepet boşaltılamadı: ${clear.status()}`).toBe(true);
  expect((await clear.json() as { satirlar: unknown[] }).satirlar).toEqual([]);
  await request.post("/api/auth/logout");
}

interface Options {
  /** Testi belirli bir e2e bayisine sabitler (`test.use({ dealerUsername: "bayi2" })`). */
  dealerUsername: string | undefined;
}

interface Fixtures {
  dealer: Dealer;
  signedIn: undefined;
  loginPage: LoginPage;
  catalogPage: CatalogPage;
  cartPage: CartPage;
  orderPage: OrderPage;
}

export const test = base.extend<Fixtures & Options>({
  dealerUsername: [undefined, { option: true }],
  dealer: [
    async ({ request, dealerUsername, baseURL }, use, testInfo) => {
      const dealer = pickDealer(dealerUsername, testInfo.parallelIndex);
      const release = await acquireDealer(lockDir(testInfo), dealer.username);
      try {
        const mode = isolationMode();
        if (mode.kind === "reset") {
          await testApi(baseURL, mode.token, "reset", { kullanici_adi: dealer.username });
          if (BREAK_CAMPAIGN) {
            await testApi(baseURL, mode.token, "break", { kullanici_adi: dealer.username, kampanya: true });
          }
        } else {
          await clearCartViaPublicApi(request, dealer);
        }
        await use(dealer);
        if (mode.kind === "reset" && BREAK_CAMPAIGN) {
          await testApi(baseURL, mode.token, "break", { kullanici_adi: dealer.username, kampanya: false });
        }
      } finally {
        release();
      }
    },
    // Kilidi beklemek testin süresinden yemesin: fikstürün kendi zaman aşımı var.
    { auto: true, timeout: LOCK_WAIT_MS + 15_000 },
  ],
  signedIn: async ({ page, dealer }, use) => {
    const resp = await page.request.post("/api/auth/login", {
      data: { kullanici_adi: dealer.username, parola: dealer.password },
    });
    expect(resp.ok(), `API ile giriş başarısız: ${resp.status()}`).toBe(true);
    await use(undefined);
  },
  loginPage: async ({ page }, use) => {
    await use(new LoginPage(page));
  },
  catalogPage: async ({ page }, use) => {
    await use(new CatalogPage(page));
  },
  cartPage: async ({ page }, use) => {
    await use(new CartPage(page));
  },
  orderPage: async ({ page }, use) => {
    await use(new OrderPage(page));
  },
});

/** Her testte bayi API ile otomatik oturum açmış olarak başlar. */
export const signedInTest = test.extend<{ autoSignIn: undefined }>({
  autoSignIn: [
    async ({ signedIn }, use) => {
      await use(signedIn);
    },
    { auto: true },
  ],
});

export { expect };
