// Page object sözleşmesi: kod üretimi (TEKNIK-TASARIM §8.4) yalnızca bu sınıfların metotlarını
// çağıran testler üretir. Bu dosya
//  - her public page object metodunun elle yazılmış bir testte en az bir kez koştuğunu,
//  - üretilen testlerin kullandığı eylem ve doğrulamaların beklenen davranışı verdiğini,
//  - expect* metotlarının yanlış değerde ASSERTION hatasıyla (kurulum hatası değil) kırmızı olduğunu
// doğrular. Son madde yerel kontrolün "defect adayı" sınıflamasının dayandığı ayrımdır.
import { test as base } from "@playwright/test";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, signedInTest as test } from "./fixtures";

const pagesDir = fileURLToPath(new URL("../pages", import.meta.url));
const testsDir = fileURLToPath(new URL(".", import.meta.url));

/** Assertion hatası mı? (break-verify ve yerel kontrol aynı ayrımı yapar.) */
async function assertionFailure(action: Promise<void>): Promise<string> {
  const outcome = await action.then(
    () => "",
    (err: unknown) => (err instanceof Error ? err.message : String(err)),
  );
  // ANSI renk kodları temizlenir.
  return outcome.replace(new RegExp(`${String.fromCharCode(27)}\\[[0-9;]*m`, "g"), "");
}

base.describe("Page object sözleşmesi (statik)", () => {
  base("her public page object metodu elle yazılmış bir testte çağrılır", () => {
    const methods = readdirSync(pagesDir, { recursive: true, encoding: "utf8" })
      .filter((f) => f.endsWith(".page.ts"))
      .flatMap((f) =>
        [...readFileSync(join(pagesDir, f), "utf8").matchAll(/^ {2}async (\w+)\(/gm)].map((m) => `${f}#${m[1] ?? ""}`),
      );
    expect(methods.length).toBeGreaterThan(30);
    const specs = readdirSync(testsDir, { recursive: true, encoding: "utf8" })
      .filter((f) => f.endsWith(".spec.ts") && !f.startsWith("generated"))
      .map((f) => readFileSync(join(testsDir, f), "utf8"))
      .join("\n");
    const uncalled = methods.filter((m) => !specs.includes(`.${m.split("#")[1] ?? ""}(`));
    expect(uncalled, "testlerde hiç çağrılmayan page object metotları").toEqual([]);
  });
});

test.describe("Page object eylem ve doğrulamaları", () => {
  test("adet alanı, menü gezintisi ve sepet sayfasındaki sayaç", async ({ catalogPage, cartPage }) => {
    await catalogPage.goto();
    await catalogPage.setQuantity("P-002", 3);
    await catalogPage.addToCart("P-002", 2);
    await catalogPage.openCart();
    await cartPage.expectLineQuantity("P-002", 2);
    await cartPage.expectLineTotal("P-002", "30,00 TL");
    await cartPage.expectCartCount(2);
    await catalogPage.openFromMenu();
    await catalogPage.expectCartCount(2);
  });

  test("7 adet Portakal Gazozu sepette 1 bedava adet ve sayaç 7 gösterir", async ({ catalogPage, cartPage }) => {
    await catalogPage.goto();
    await catalogPage.addToCart("P-001", 7);
    await catalogPage.expectCartCount(7);
    await cartPage.goto();
    await cartPage.expectCartCount(7);
    await cartPage.expectLineQuantity("P-001", 7);
    await cartPage.expectFreeQuantity("P-001", 1);
  });

  test("indirimsiz sepette minimum tutar uyarısı metni ve pasif onay", async ({ catalogPage, cartPage }) => {
    await catalogPage.goto();
    await catalogPage.addToCart("P-003", 1);
    await cartPage.goto();
    await cartPage.expectMinOrderWarning("Minimum sipariş tutarı 750,00 TL");
    await cartPage.expectCheckoutDisabled();
  });

  test("onaylanan sipariş geçmişte numarasıyla bulunur", async ({ catalogPage, cartPage, orderPage }) => {
    await catalogPage.goto();
    await catalogPage.addToCart("P-004", 25);
    await cartPage.goto();
    await cartPage.checkout();
    await orderPage.expectConfirmation();
    const orderNumber = await orderPage.readOrderNumber();
    await orderPage.gotoHistory();
    await orderPage.expectOrderInHistory(orderNumber);
    await orderPage.expectOrderTotalInHistory(orderNumber, "750,00 TL");
  });

  test("expect* metotları yanlış değerde assertion hatasıyla kırmızı olur", async ({ catalogPage, cartPage }) => {
    // Her yanlış doğrulama expect.timeout (5 sn) kadar bekler.
    test.setTimeout(40_000);
    await catalogPage.goto();
    await catalogPage.addToCart("P-001", 7);
    await cartPage.goto();
    await cartPage.expectLineQuantity("P-001", 7);
    const free = await assertionFailure(cartPage.expectFreeQuantity("P-001", 99));
    expect(free).toMatch(/expect\(.*\)\..*failed/);
    expect(free).toContain("cart-line-free-P-001");
    const count = await assertionFailure(cartPage.expectCartCount(5));
    expect(count).toMatch(/expect\(.*\)\..*failed/);
    await cartPage.removeProduct("P-001");
    await catalogPage.goto();
    await catalogPage.addToCart("P-002", 1);
    await cartPage.goto();
    const warning = await assertionFailure(cartPage.expectMinOrderWarning("Minimum sipariş tutarı 1,00 TL"));
    expect(warning).toMatch(/expect\(.*\)\..*failed/);
  });
});
