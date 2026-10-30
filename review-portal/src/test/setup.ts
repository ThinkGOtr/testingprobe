import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";
import { mockKayitlariniSifirla, yapilandir } from "../api/http";
import { mockSifirla } from "../api/mock/handlers";

beforeEach(() => {
  mockSifirla();
  mockKayitlariniSifirla();
  // Uç keşfi (openapi.json) yalnızca onu sınayan testlerde açılır; diğerlerinde fetch sahtesi
  // ilk çağrıyı keşif isteğine harcamasın.
  yapilandir({ mockZorunlu: true, mockOtomatik: true, yetenekKesfi: false });
});

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  localStorage.clear();
});
