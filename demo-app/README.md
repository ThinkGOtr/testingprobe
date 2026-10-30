# demo-app — Bayi Sipariş Portalı (örnek uygulama)

AI Testing Probe'un test ettiği örnek uygulama: giriş, katalog, sepet, "6 al 1 bedava"
kampanyası, minimum sipariş tutarı, sipariş onayı ve geçmiş. Marka yoktur, tüm veri sentetiktir.

| Dizin | İçerik | Compose servisi |
|---|---|---|
| `api/` | Python 3.12 + FastAPI + SQLAlchemy 2 (`uv`). Postgres (compose) veya SQLite (CI / test-runner). Şema + deterministik tohum açılışta idempotent kurulur. | `demo-app-api` (:8000, yalnızca iç ağ) |
| `web/` | React 18 + Vite + TypeScript; nginx ile servis edilir (`/api/*` → API). `vite preview` aynı proxy'yi kullanır. | `demo-app-web` (host: `127.0.0.1:8081`) |
| `e2e/` | Playwright: page object kütüphanesi (`pages/`), elle yazılmış testler (`tests/`). | `test-runner` içinde |
| `ci/run-checks.sh` | `npm ci --ignore-scripts` → `tsc` → `eslint --no-inline-config` → `playwright test` (argümanlar aynen geçer). GitHub CI ve yerel test-runner aynı betiği kullanır. | — |

## API

| Yöntem | Yol | Not |
|---|---|---|
| GET | `/health` | `SELECT 1`; 200 `ok` / 503 `degraded` |
| POST | `/auth/login` `{kullanici_adi, parola}` | `bayi_oturum` çerezi (HttpOnly, SameSite=Lax). Hata: 401 "Kullanıcı adı veya parola hatalı" |
| POST | `/auth/logout` · GET `/auth/me` | |
| GET | `/products` | `[{kod, ad, fiyat, kampanya}]` |
| GET | `/cart` | satırlar (`adet`, `bedava_adet`, `satir_tutari`…), `ara_toplam`, `indirim`, `toplam`, `min_siparis_tutari`, `onaylanabilir`, `uyarilar` |
| POST | `/cart/lines` `{urun_kod, adet}` · PUT/DELETE `/cart/lines/{kod}` · DELETE `/cart` | Ekleme adetleri toplar (en fazla 999) |
| POST | `/orders` | 201; minimum altı (kampanyasız sipariş) / boş sepet 422 |
| GET | `/orders` · `/orders/{numara}` | Yalnızca kendi siparişleri |
| POST | `/test/reset` `{kullanici_adi?}` | Yalnızca `DEMOAPP_TEST_MODE=1` **ve** `DEMOAPP_TEST_TOKEN` tanımlıyken (aksi halde 404); `X-Demoapp-Test-Token` başlığı eşleşmezse 403. Kullanıcı verilirse yalnızca onun sepeti/siparişleri/kırılması; yoksa tam sıfırlama. Web nginx'i `/api/test/` yolunu dışarı açmaz (404) |
| POST | `/test/break` `{kullanici_adi, kampanya}` | Aynı koruma. **Bayi kapsamlı** demo kırılması ("kırarak doğrula"): `kampanya=true` iken yalnızca o bayinin sepet/sipariş hesabında indirim uygulanmaz (`test_kirilma` tablosu); diğer bayiler, paylaşılan uygulama ve MCP etkilenmez. `/test/reset` kırılmayı da kaldırır |

Tutarlar JSON'da `"1250.00"` metni; arayüzde `1.250,00 TL` (tr-TR).

**İş kuralları:**
- Kampanya: `api/src/demoapp_api/campaign.py` → `bedava_adet()`; kampanyalı ürünün satırında her 6 adette 1 bedava.
- Minimum sipariş tutarı `ayar.min_siparis_tutari` (tohum: 750.00) tablosundan okunur; indirim sonrası
  toplama uygulanır. Sepette kampanyalı ürün varsa (kampanyalı sipariş) minimum tutar aranmaz.

**Ortam:** `DEMOAPP_DATABASE_URL` (zorunlu; `postgresql+psycopg://…` veya `sqlite:///…`),
`DEMOAPP_TEST_MODE=1` + `DEMOAPP_TEST_TOKEN=<sır>` (`/test/*`), `BREAK_CAMPAIGN=1` (süreç geneli
kırılma; yalnızca yerel deneme için — koşu başına kırılma `/test/break` ile yapılır).

**Salt okuma rolü:** `infra/postgres/init/02-demoapp-ro.sh` `demoapp_ro` rolünü (salt okuma
oturumu, 5 sn sorgu sınırı) ve `demoapp`'a `public` şemada CREATE yetkisini kurar. API tabloları
kurduktan sonra `demoapp_ro`'ya yalnızca `urun`, `kampanya`, `ayar` ve `bayi`'nin
`id, kullanici_adi, ad, kredi_limiti, olusturma` kolonlarında SELECT verir; sipariş, sepet,
oturum tabloları ve parola özeti kapalıdır.

## Page object kütüphanesi (`e2e/pages/`)

- `pages/<alan>/locators.ts` **saf veridir** (`export const x = { key: { testId, role, name, within?, intent } } as const;`).
  Sonu `-` ile biten testId'ler önektir; page object ürün kodunu / sipariş numarasını ekler
  (`product-card-` + `P-001`). Locator onarımı yalnızca `testId` değerini değiştirebilir.
- `within` (isteğe bağlı): kapsayıcının testId öneki. Aynı rol + ad her ürün kartında tekrarlandığından
  (`addToCart`, `quantityInput`) eleman `within` + ürün kodu kapsayıcısında aranır
  (`product-card-P-001` içinde "Sepete ekle"). `tests/locators.spec.ts`, sayfada birden fazla
  elemana uyan her rol + adın `within` taşıdığını ve her kapsayıcıda tam olarak bir elemana uyduğunu doğrular.
- Sınıflar: `LoginPage`, `CatalogPage`, `CartPage`, `OrderPage` (`pages/index.ts`). Eylem metotları
  ve `expect*` doğrulama metotları; parametreler `string`/`number`, dönüş `Promise<void>`
  (`OrderPage.readOrderNumber()` hariç). Kod üretimi bu imzaları sembol tablosu olarak okur.
- Elemanlar her zaman `page.getByTestId(locators.x.y.testId)` ile bulunur.

## Testler (`e2e/tests/`)

- `fixtures.ts`: paralel işçi başına bir bayi (`bayi1`, `bayi2`; bu yüzden `workers: 2`). Veri yalıtımı:
  - **sıfırlama** (token varsa): her testten önce o bayinin verisi `/test/reset` ile sıfırlanır
    (`X-Demoapp-Test-Token`). webServer modunda `playwright.config.ts` her koşu için rastgele token
    üretip başlattığı API'ye verir; çalışan ortamda `DEMOAPP_TEST_TOKEN` + `DEMO_API_URL` verilir.
  - **yalnızca sepet** (`TP_E2E_NO_RESET=1`, token yok): test uçları kullanılmaz; sepet herkese açık
    API ile (`DELETE /cart`) boşaltılır. Sipariş geçmişi silinemediğinden `@sifir-veri` etiketli
    testler dışlanır. Aynı uygulamaya karşı eşzamanlı iki koşu desteklenmez (bayi1/bayi2 paylaşılır).
  - `BREAK_CAMPAIGN=1`: fixture, koşunun bayisi için `/test/break` ile kırılmayı açar ve test
    sonunda kapatır (token gerekir). Her iki modda aynı yol; API sürecine env geçirilmez.
  `signedInTest` API ile oturum açar.
  Üretilen testler de bu fikstürü (`dealer.username`) kullanmalıdır.
- `login`, `cart`, `order`, `mobile` (390 px: sepet satırı tutarı ve "Kaldır" kaydırmasız görünür), `a11y` (`@axe-core/playwright`, ihlaller ek olarak; yalnızca
  kritikte kırmızı), `locators` (locators.ts rol/ad meta verisi uygulamayla tutarlı mı).
- Raporlar `e2e/results/`: `junit.xml`, `results.json`, `allure-results/`, `html/`.

## Yerel çalıştırma

```bash
# Birim testleri (API)
cd api && uv sync && uv run ruff check && uv run pytest
# Gerçek Postgres'e karşı (02-demoapp-ro.sh ile kurulmuş):
DEMOAPP_TEST_PG_URL=postgresql+psycopg://demoapp:…@127.0.0.1:55432/demoapp \
DEMOAPP_TEST_PG_RO_URL=postgresql+psycopg://demoapp_ro:…@127.0.0.1:55432/demoapp uv run pytest -m postgres

# E2E — uygulamayı Playwright webServer ile kendisi başlatır (SQLite, CI ile aynı yol)
cd e2e && npx playwright install chromium
bash ../ci/run-checks.sh                       # web önizleme portu 18081 (compose'un 8081'iyle çakışmaz)
npm run break-verify                           # yeşil → kırmızı (yalnızca kampanya testleri, assertion ile) → yeşil

# E2E — çalışan bir uygulamaya karşı: sıfırlama/kırılma API'ye doğrudan gider (nginx /api/test/'i
# açmaz) ve API'de DEMOAPP_TEST_TOKEN tanımlı olmalıdır (test-runner: DEMO_API_URL=http://demo-app-api:8000).
BASE_URL=http://… DEMO_API_URL=http://… DEMOAPP_TEST_TOKEN=… npx playwright test
BASE_URL=http://… DEMO_API_URL=http://… DEMOAPP_TEST_TOKEN=… npm run break-verify
# Token yoksa (ör. bugünkü compose demo-app-api): yalnızca sepet yalıtımı, @sifir-veri hariç
BASE_URL=http://127.0.0.1:8081 TP_E2E_NO_RESET=1 npx playwright test
```

`run-checks.sh` ortamı: `SKIP_INSTALL=1` (bağımlılıklar hazır, çevrimdışı), `DEMO_API_COMMAND`
(`uv` yoksa API başlatma komutu; `--host 127.0.0.1 --port $DEMO_API_PORT` dinlemeli),
`DEMO_API_PORT` (18000), `DEMO_WEB_PREVIEW_PORT` (18081).
