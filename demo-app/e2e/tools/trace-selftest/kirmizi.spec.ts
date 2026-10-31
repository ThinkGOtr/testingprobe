// Bilerek kırmızı test: DEMOAPP_TEST_TOKEN'ın kırmızı koşunun trace/artefaktlarına sızmadığını
// kanıtlamak için (tools/trace-token-selftest.js). Ana test dizininde değildir; CI'da koşmaz.
import { signedInTest as test } from "../../tests/fixtures";

test("trace öz sınaması: kırmızı test (kasıtlı)", async ({ catalogPage }) => {
  await catalogPage.goto();
  await catalogPage.expectCartCount(99);
});

test("trace öz sınaması: yeşil test", async ({ catalogPage }) => {
  await catalogPage.goto();
  await catalogPage.expectCartCount(0);
});
