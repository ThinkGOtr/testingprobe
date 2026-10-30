import { test } from "@playwright/test";
import { HomePage } from "../pages/home/HomePage";

test("ana sayfa açılır ve başlık görünür @smoke", async ({ page }) => {
  const home = new HomePage(page);
  await home.goto();
  await home.expectLoaded();
});
