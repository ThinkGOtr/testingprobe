// Bayi seçimi ve yalıtımı: işçi bayisi, test.use({ dealerUsername }) ile sabitleme ve süreçler
// arası bayi kilidi. Üretilen testler case metnindeki bayiye bu yolla sabitlenir.
import { test as base } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AGENT_DEALER, DEALERS, type Dealer, acquireDealer, expect, pickDealer, runPasswordEnvName, runPasswords, setRunPasswordEnv, test, withRunPassword } from "./fixtures";

/** Seed listesindeki bayi (koşu ortamı parolasından bağımsız). */
function seed(username: string): Dealer {
  const d = DEALERS.find((x) => x.username === username);
  if (!d) throw new Error(`seed bayisi yok: ${username}`);
  return d;
}

base.describe("Bayi seçimi (birim)", () => {
  base("işçi bayisi ve sabitleme; doğrulama ajanının bayisi e2e'ye kapalı", () => {
    expect(pickDealer(undefined, 0).username).toBe("bayi1");
    expect(pickDealer(undefined, 1).username).toBe("bayi2");
    // Parola koşu ortamından gelebilir (TP_RUN_DEALER_PASSWORDS): kimlik ve ad seed listesindeki gibi.
    expect(pickDealer("bayi2", 0)).toEqual({ ...DEALERS[1], password: pickDealer("bayi2", 0).password });
    expect(() => pickDealer(undefined, DEALERS.length)).toThrow(/paralel işçi/);
    expect(() => pickDealer(AGENT_DEALER, 0)).toThrow(/doğrulama ajanına ayrılmıştır/);
    expect(() => pickDealer("yok", 0)).toThrow(/e2e bayisi değil/);
  });

  base("koşu hesabı parolası: ortamda girilen hesabın parolası, yoksa seed parolası", () => {
    expect(runPasswords("")).toEqual({});
    expect(runPasswords(" ")).toEqual({});
    const pw = runPasswords('{"bayi2": "Bayi2-ozel!", "bos": ""}');
    expect(pw).toEqual({ bayi2: "Bayi2-ozel!" });
    const [bayi1, bayi2] = [seed("bayi1"), seed("bayi2")];
    expect(withRunPassword(bayi2, pw)).toEqual({ ...bayi2, password: "Bayi2-ozel!" });
    expect(withRunPassword(bayi1, pw)).toBe(bayi1);
    expect(() => runPasswords("{bozuk")).toThrow(/geçerli JSON değil/);
    expect(() => runPasswords('["x"]')).toThrow(/JSON nesnesi/);
  });

  base("üretilen testin koşu parolası ortam adı: girilmemişse seed yazılır, girilmişse korunur", () => {
    expect(runPasswordEnvName("bayi1")).toBe("TP_TESTVERI_KOSU_BAYI1");
    expect(runPasswordEnvName("test.k-2")).toBe("TP_TESTVERI_KOSU_TEST_K_2");
    expect(runPasswordEnvName("x".repeat(60))).toBeUndefined();
    const env: Record<string, string | undefined> = { TP_TESTVERI_KOSU_BAYI2: "runner-verdi" };
    setRunPasswordEnv(env);
    expect(env["TP_TESTVERI_KOSU_BAYI2"]).toBe("runner-verdi");
    expect(env["TP_TESTVERI_KOSU_BAYI1"]).toBe(pickDealer("bayi1", 0).password);
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
