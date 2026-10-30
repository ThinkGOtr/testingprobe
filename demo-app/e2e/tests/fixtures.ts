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
import { test as base, expect, type APIRequestContext } from "@playwright/test";
import { CartPage, CatalogPage, LoginPage, OrderPage } from "../pages";

export interface Dealer {
  username: string;
  password: string;
  name: string;
}

/** Demo bayi kullanıcıları. */
export const DEALERS: readonly Dealer[] = [
  { username: "bayi1", password: "Demo123!", name: "Merkez Bayi" },
  { username: "bayi2", password: "Demo123!", name: "Sahil Bayi" },
];

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

/** /test/<path> ucunu çağırır: DEMO_API_URL verilmişse doğrudan API'ye, yoksa web vekili üzerinden. */
async function testApi(request: APIRequestContext, token: string, path: string, data: object): Promise<void> {
  const url = process.env.DEMO_API_URL
    ? `${process.env.DEMO_API_URL.replace(/\/$/, "")}/test/${path}`
    : `/api/test/${path}`;
  const resp = await request.post(url, { data, headers: { "X-Demoapp-Test-Token": token } });
  const hint =
    resp.status() === 404
      ? " (uç kapalı: API'de DEMOAPP_TEST_MODE=1 + DEMOAPP_TEST_TOKEN yok ya da web vekili /api/test/ yolunu açmıyor; DEMO_API_URL verin)"
      : "";
  expect(resp.ok(), `POST /test/${path} başarısız: ${resp.status()}${hint}`).toBe(true);
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

interface Fixtures {
  dealer: Dealer;
  signedIn: undefined;
  loginPage: LoginPage;
  catalogPage: CatalogPage;
  cartPage: CartPage;
  orderPage: OrderPage;
}

export const test = base.extend<Fixtures>({
  dealer: [
    async ({ request }, use, testInfo) => {
      const dealer = DEALERS[testInfo.parallelIndex];
      if (!dealer) {
        throw new Error(
          `En fazla ${DEALERS.length} paralel işçi desteklenir (bayi kullanıcısı sayısı); --workers değerini düşürün.`,
        );
      }
      const mode = isolationMode();
      if (mode.kind === "reset") {
        await testApi(request, mode.token, "reset", { kullanici_adi: dealer.username });
        if (BREAK_CAMPAIGN) {
          await testApi(request, mode.token, "break", { kullanici_adi: dealer.username, kampanya: true });
        }
      } else {
        await clearCartViaPublicApi(request, dealer);
      }
      await use(dealer);
      if (mode.kind === "reset" && BREAK_CAMPAIGN) {
        await testApi(request, mode.token, "break", { kullanici_adi: dealer.username, kampanya: false });
      }
    },
    { auto: true },
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
