// Bayi seçimi ve yalıtımı: işçi bayisi, test.use({ dealerUsername }) ile sabitleme ve süreçler
// arası bayi kilidi. Üretilen testler case metnindeki bayiye bu yolla sabitlenir.
import { test as base } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AGENT_DEALER, DEALERS, acquireDealer, expect, pickDealer, test } from "./fixtures";

base.describe("Bayi seçimi (birim)", () => {
  base("işçi bayisi ve sabitleme; doğrulama ajanının bayisi e2e'ye kapalı", () => {
    expect(pickDealer(undefined, 0).username).toBe("bayi1");
    expect(pickDealer(undefined, 1).username).toBe("bayi2");
    expect(pickDealer("bayi2", 0)).toEqual(DEALERS[1]);
    expect(() => pickDealer(undefined, DEALERS.length)).toThrow(/paralel işçi/);
    expect(() => pickDealer(AGENT_DEALER, 0)).toThrow(/doğrulama ajanına ayrılmıştır/);
    expect(() => pickDealer("yok", 0)).toThrow(/e2e bayisi değil/);
  });

  base("bayi kilidi özeldir ve bekleyen sıradaki alır", async () => {
    const dir = mkdtempSync(join(tmpdir(), "demoapp-kilit-test-"));
    const order: string[] = [];
    const releaseA = await acquireDealer(dir, "bayi1");
    const waiterB = acquireDealer(dir, "bayi1").then((release) => {
      order.push("B");
      return release;
    });
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(order, "kilit tutulurken ikinci alıcı beklemeli").toEqual([]);
    // A bırakıp hemen yeniden ister: sıradaki B önce almalı (açlık yok).
    releaseA();
    const againA = acquireDealer(dir, "bayi1").then((release) => {
      order.push("A");
      return release;
    });
    const releaseB = await waiterB;
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(order).toEqual(["B"]);
    releaseB();
    (await againA)();
    expect(order).toEqual(["B", "A"]);
    // Başka bayinin kilidi bağımsızdır; süre dolunca açıklayıcı hata verir.
    const releaseC = await acquireDealer(dir, "bayi2");
    await expect(acquireDealer(dir, "bayi2", 100)).rejects.toThrow(/serbest kalmadı/);
    releaseC();
  });
});

test.describe("Bayiye sabitlenmiş test (bayi2)", () => {
  test.use({ dealerUsername: "bayi2" });

  test("case metnindeki bayi ile arayüzden giriş yapılır", async ({ dealer, loginPage, catalogPage }) => {
    expect(dealer.username).toBe("bayi2");
    await loginPage.goto();
    await loginPage.login("bayi2", "Demo123!");
    await loginPage.expectLoggedIn("Sahil Bayi");
    await catalogPage.expectCartCount(0);
  });
});

test.describe("Bayiye sabitlenmiş test (bayi1)", () => {
  test.use({ dealerUsername: "bayi1" });

  test("case metnindeki bayi ile arayüzden giriş yapılır", async ({ dealer, loginPage, catalogPage }) => {
    expect(dealer.username).toBe("bayi1");
    await loginPage.goto();
    await loginPage.login("bayi1", "Demo123!");
    await loginPage.expectLoggedIn("Merkez Bayi");
    await catalogPage.addToCart("P-002", 1);
    await catalogPage.expectCartCount(1);
  });
});
