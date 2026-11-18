// TP3-2: proje değişimi rol hesabını değiştirince eski oturum iptal edilir; 401 / `session.ended`
// yeniden girişe götürmeden önce çerezdeki (yeni) oturum doğrulanır.
import { beforeEach, describe, expect, it } from "vitest";
import type { Kullanici } from "./api/types";
import { oturumYenilendiMi } from "./auth";

const k = { id: "u1" } as unknown as Kullanici;

beforeEach(() => sessionStorage.clear());

describe("oturumYenilendiMi", () => {
  it("çerezdeki oturum geçerliyse yenileme (giriş değil); 30 sn içinde ikinci kez yenilemez", async () => {
    let t = 1_000_000;
    expect(await oturumYenilendiMi(async () => k, () => t)).toBe(true);
    t += 5_000;
    expect(await oturumYenilendiMi(async () => k, () => t)).toBe(false);
    t += 31_000;
    expect(await oturumYenilendiMi(async () => k, () => t)).toBe(true);
  });

  it("oturum gerçekten bittiyse (me 401) yeniden giriş yolu", async () => {
    expect(
      await oturumYenilendiMi(async () => {
        throw new Error("401");
      }),
    ).toBe(false);
    expect(await oturumYenilendiMi(async () => null)).toBe(false);
  });
});
