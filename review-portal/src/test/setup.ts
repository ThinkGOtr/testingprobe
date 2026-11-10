import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach } from "vitest";
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
