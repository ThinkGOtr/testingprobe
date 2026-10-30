# demo-app — Bayi Sipariş Portalı (örnek uygulama)

AI Testing Probe'un test ettiği örnek uygulama. **F0'da yalnızca iskelet ve `/health` vardır;
iş mantığı (giriş, katalog, sepet, kampanya, sipariş, geçmiş) F1'de eklenir.**

| Dizin | İçerik | Compose servisi |
|---|---|---|
| `api/` | Python 3.12 + FastAPI, `uv` ile yönetilir. `GET /health` → `demoapp` veritabanına `SELECT 1` (200 `ok` / 503 `degraded`, bkz. `specs/001-dev-foundation/contracts/health.md`). | `demo-app-api` (:8000, yalnızca iç ağ) |
| `web/` | React 18 + Vite + TypeScript, nginx ile servis edilir. `/health` statik 200; `/api/*` → `demo-app-api:8000`; SPA fallback. | `demo-app-web` (host: `127.0.0.1:8081`) |
| `e2e/` | Playwright Test (TypeScript) projesi: `pages/<sayfa>/locators.ts` (yalnızca `data-testid` sabitleri) + page object, `tests/*.spec.ts`. Raporlar: list, JUnit (`results/junit.xml`), Allure. | `test-runner` içinde çalışır |

## Kurallar

- Web arayüzündeki **her etkileşimli eleman `data-testid` taşır**; locator değerleri yalnızca
  `e2e/pages/**/locators.ts` içinde tutulur, testler page object üzerinden `getByTestId` kullanır.
- Sürümler sabittir: `package-lock.json`, `uv.lock`; `@playwright/test` sürümü kökteki
  `.playwright-version` (1.64.1) ile aynı olmalıdır.

## Yerel çalıştırma

```bash
# API
cd api && uv sync && uv run pytest
DEMOAPP_DATABASE_URL=postgresql+psycopg://demoapp:...@localhost:55432/demoapp \
  uv run uvicorn demoapp_api.main:app --port 8000

# Web
cd web && npm ci && npm run dev        # /api istekleri localhost:8000'e proxy'lenir

# E2E (çalışan bir web'e karşı; tarayıcılar toolchain imajında hazırdır)
cd e2e && npm ci && npx tsc --noEmit
BASE_URL=http://localhost:8081 npx playwright test
```

Normalde tüm servisler kökten `make up` ile başlatılır.
