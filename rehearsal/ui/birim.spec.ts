// Prova yardımcılarının birim testleri (tarayıcı açılmaz): `npm run birim`.
import { expect, test } from "@playwright/test";
import { maskele, yerelZaman } from "./zaman.js";

test("yerelZaman: yerel saat, YYYYMMDD-HHMMSS (UTC değil)", () => {
  const d = new Date(2026, 10, 1, 12, 26, 3); // yerel 12:26:03
  expect(yerelZaman(d)).toBe("20261101-122603");
  // toISOString UTC verir; yerel saat dilimi UTC değilse ikisi farklıdır (eski hata).
  if (d.getTimezoneOffset() !== 0) expect(yerelZaman(d)).not.toBe(d.toISOString().replace(/[-:]/g, "").replace("T", "-").slice(0, 15));
});

test("maskele: her geçişi ve her sırrı maskeler", () => {
  const m = maskele("a=GIZLI b=GIZLI c=PO-PAROLA-1 d=GIZLI", ["GIZLI", "PO-PAROLA-1", ""]);
  expect(m).toBe("a=*** b=*** c=*** d=***");
  expect(maskele("x", [])).toBe("x");
});

test("maskele: uzun sır önce (önek çakışması kısmi bırakmaz)", () => {
  expect(maskele("parola123456", ["parola", "parola123456"])).toBe("***");
});
