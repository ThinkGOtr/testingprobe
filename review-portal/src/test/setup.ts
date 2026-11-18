import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach } from "vitest";
import { demoDurumuOnbeleginiTemizle } from "../api/client";
import { mockKayitlariniSifirla, yapilandir } from "../api/http";
import { mockSifirla } from "../api/mock/handlers";
import { asistanIceriginiYukle } from "../components/asistan/AsistanPaneli";
import { kimlikKipiniAyarla } from "../lib/kimlikKipi";

// Asistan paneli içeriği tarayıcıda ayrı parçadır (ilk açılışta yüklenir, Suspense). Testlerde önceden
// yüklenir: panel açılınca içerik eş zamanlı çizilir, test sırası/tek test koşusu sonucu değiştirmez.
// Yükleme anı (Suspense yer tutucusu) asistan/tembelYukleme.test.tsx'te ayrıca sınanır.
beforeAll(() => asistanIceriginiYukle());

beforeEach(() => {
  mockSifirla();
  mockKayitlariniSifirla();
  demoDurumuOnbeleginiTemizle();
  // Uç keşfi (openapi.json) yalnızca onu sınayan testlerde açılır; diğerlerinde fetch sahtesi
  // ilk çağrıyı keşif isteğine harcamasın.
  yapilandir({ mockZorunlu: true, mockOtomatik: true, yetenekKesfi: false });
});

afterEach(() => {
  cleanup();
  // AI Probe kipi modül düzeyinde tutulur (yanıt başlığından); her test `local` ile başlar.
  kimlikKipiniAyarla(null);
  sessionStorage.clear();
  localStorage.clear();
});

// ET-07: kilitli eylem düğmeleri yerel `disabled` yerine `aria-disabled="true"` taşır (Tab sırasında
// kalır, neden okunur). Testlerde "kullanıcı için pasif" anlamı korunur: toBeDisabled/toBeEnabled
// `aria-disabled="true"` olan düğmeyi de pasif sayar.
import { expect } from "vitest";
const ariaPasif = (el: unknown) => el instanceof Element && el.getAttribute("aria-disabled") === "true";
const yerelPasif = (el: unknown) => el instanceof Element && (el as HTMLButtonElement).matches?.(":disabled");
expect.extend({
  toBeDisabled(el: unknown) {
    const pass = yerelPasif(el) || ariaPasif(el);
    return { pass, message: () => `öğe ${pass ? "pasif olmamalıydı" : "pasif (disabled ya da aria-disabled) olmalıydı"}` };
  },
  toBeEnabled(el: unknown) {
    const pass = !(yerelPasif(el) || ariaPasif(el));
    return { pass, message: () => `öğe ${pass ? "pasif olmalıydı" : "etkin olmalıydı (disabled/aria-disabled var)"}` };
  },
});
