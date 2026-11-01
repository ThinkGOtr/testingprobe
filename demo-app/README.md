# demo-app — Bayi Sipariş Portalı (örnek uygulama)

AI Testing Probe'un test ettiği örnek uygulama: giriş, katalog, sepet, "6 al 1 bedava"
kampanyası, minimum sipariş tutarı, sipariş onayı ve geçmiş. Marka yoktur, tüm veri sentetiktir.

| Dizin | İçerik | Compose servisi |
|---|---|---|
| `api/` | Python 3.12 + FastAPI + SQLAlchemy 2 (`uv`). Postgres (compose) veya SQLite (CI / test-runner). Şema + deterministik tohum açılışta idempotent kurulur. | `demo-app-api` (:8000, yalnızca iç ağ) |
| `web/` | React 18 + Vite + TypeScript; nginx ile servis edilir (`/api/*` → API). `vite preview` aynı proxy'yi kullanır. | `demo-app-web` (host: `127.0.0.1:8081`) |
| `e2e/` | Playwright: page object kütüphanesi (`pages/`), elle yazılmış testler (`tests/`). | `test-runner` içinde |
| `ci/run-checks.sh` | `npm ci --ignore-scripts` → `tsc` → `eslint --no-inline-config` → `playwright test` (argümanlar aynen geçer). GitHub CI ve yerel test-runner aynı betiği kullanır. | — |

## Demo bayileri

| Kullanıcı | Parola | Bayi adı | Kredi limiti | Kim kullanır |
|---|---|---|---|---|
| `bayi1` | `Demo123!` | Merkez Bayi | 2.000,00 TL | e2e işçisi 0 (ve `dealerUsername: "bayi1"` ile sabitlenen testler) |
| `bayi2` | `Demo123!` | Sahil Bayi | 500,00 TL | e2e işçisi 1 (ve `dealerUsername: "bayi2"` ile sabitlenen testler) |
| `bayi3` | `Demo123!` | Doğrulama Bayi | 2.000,00 TL | Yalnızca kod üretimindeki doğrulama ajanı (playwright-mcp). e2e testleri kullanamaz ve sıfırlamaz (`fixtures.ts` reddeder) |

Tohum (`api/src/demoapp_api/seed.py`) deterministiktir ve her açılışta idempotent uygulanır.
`POST /test/reset {kullanici_adi: "bayi3"}` yalnızca bayi3'ün sepetini, siparişlerini ve kırılmasını
siler; tam sıfırlama (`{}`) bayi3'ü de yeniden kurar. Ajan tarayıcısı `/api/test/*`'e erişemez
(nginx 404); bayi3'ün sepeti doğrulamadan önce ya test uçlarına erişen bir servisten
(`DEMO_API_URL` + `DEMOAPP_TEST_TOKEN`) `/test/reset` ile ya da herkese açık API ile (bayi3 girişi +
`DELETE /api/cart`; siparişler kalır) boşaltılır.

## API

| Yöntem | Yol | Not |
|---|---|---|
| GET | `/health` | `SELECT 1`; 200 `ok` / 503 `degraded` |
| POST | `/auth/login` `{kullanici_adi, parola}` | `bayi_oturum` çerezi (HttpOnly, SameSite=Lax). Hata: 401 "Kullanıcı adı veya parola hatalı" |
| POST | `/auth/logout` · GET `/auth/me` | `/auth/me` oturumsuz 401 döner |
| GET | `/auth/session` | Sayfa açılışı oturum yoklaması: her zaman 200, oturumsuz `{"oturum": null}` (tarayıcı konsolunda hata üretmez) |
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
  Sözleşme bir sayfada geçtikten sonra o sayfanın aria snapshot'ı koşu çıktısına
  `results/artifacts/<test>/<sayfa>.aria.yml` (`giris`, `katalog`, `sepet`, `siparis`,
  `siparis-gecmisi`) olarak yazılır: locator onarımı (TEKNIK-TASARIM §8.7) aday rol + adı son yeşil
  koşunun bu dosyasına karşı doğrular. Kırık koşuda sözleşme önce düştüğü için dosya yazılmaz.
- Sınıflar: `LoginPage`, `CatalogPage`, `CartPage`, `OrderPage` (`pages/index.ts`). Eylem metotları
  ve `expect*` doğrulama metotları; parametreler `string`/`number`, dönüş `Promise<void>`
  (`OrderPage.readOrderNumber()` hariç). Her public metodun JSDoc'u vardır. Kod üretimi bu imzaları
  sembol tablosu olarak okur (toolchain-worker `POST /symbols`).
- `tests/page-objects.spec.ts` her public metodun elle yazılmış bir testte çağrıldığını (statik) ve
  `expect*` metotlarının yanlış değerde **assertion** hatasıyla kırmızı olduğunu doğrular.
- Elemanlar her zaman `page.getByTestId(locators.x.y.testId)` ile bulunur.

## Testler (`e2e/tests/`)

- `fixtures.ts`: paralel işçi başına bir bayi (`bayi1`, `bayi2`; bu yüzden `workers: 2`).
  `test.use({ dealerUsername: "bayi2" })` testi belirli bir e2e bayisine sabitler. Aynı bayi iki
  işçide aynı anda kullanılmasın diye her test bayisini süreçler arası dosya kilidiyle alır
  (`os.tmpdir()/demoapp-e2e-kilit-<hedef özeti>`; bekleyen sıradaki alır, çökmüş işçinin kilidi
  temizlenir; bekleme en çok 40 sn, fikstürün kendi zaman aşımıyla). Veri yalıtımı:
  - **sıfırlama** (token varsa): her testten önce o bayinin verisi `/test/reset` ile sıfırlanır
    (`X-Demoapp-Test-Token`). webServer modunda `playwright.config.ts` her koşu için rastgele token
    üretip başlattığı API'ye verir; çalışan ortamda `DEMOAPP_TEST_TOKEN` + `DEMO_API_URL` verilir.
  - **yalnızca sepet** (`TP_E2E_NO_RESET=1`, token yok): test uçları kullanılmaz; sepet herkese açık
    API ile (`DELETE /cart`) boşaltılır. Sipariş geçmişi silinemediğinden `@sifir-veri` etiketli
    testler dışlanır. Aynı uygulamaya karşı eşzamanlı iki koşu desteklenmez (bayi1/bayi2 paylaşılır).
  - `BREAK_CAMPAIGN=1`: fixture, koşunun bayisi için `/test/break` ile kırılmayı açar ve test
    sonunda kapatır (token gerekir). Her iki modda aynı yol; API sürecine env geçirilmez.
  `signedInTest` API ile oturum açar.
  Üretilen testler de bu fikstürleri kullanır (bkz. "Üretilen testler için sözleşme").
- `dealers` (bayi seçimi, sabitleme ve kilit), `page-objects` (yukarıda), `login`, `cart`, `order`, `mobile` (390 px: sepet satırı tutarı ve "Kaldır" kaydırmasız görünür), `a11y` (`@axe-core/playwright`, ihlaller ek olarak; yalnızca
  kritikte kırmızı), `locators` (locators.ts rol/ad meta verisi uygulamayla tutarlı mı).
- Raporlar `e2e/results/`: `junit.xml`, `results.json`, `allure-results/`, `html/`.

## Üretilen testler için sözleşme

Kod üretimi (TEKNIK-TASARIM §8.4) onaylı case'i doğrulanmış page object eşlemesinden **şablonla**
`e2e/tests/generated/<ad>.spec.ts` dosyasına yazar; model TypeScript yazmaz. Dosya `tsconfig.json`
(`tests/**/*.ts`) ve ESLint kapsamındadır; ESLint bu dizine ek sözleşme kuralları uygular
(`eslint.config.js`, `files: ["tests/generated/**/*.ts"]`) ve kuralların kendisi
`npm run lint:generated-selftest` ile denetlenir. Kurallar **izin listesidir**: dosyada yalnızca
`test`/`signedInTest`, `describe`/`use`, `dealerUsername`/`tag`, page object fikstürleri ve
`pages/**/*.page.ts`'teki herkese açık `async` metotlar tanımlayıcı olarak geçebilir; hesaplanmış üye
erişimi (`cartPage["page"]`), zincirli üye (`a.b.c`), `globalThis`/`fetch` gibi her başka ad, literal
olmayan argüman ve `await <fikstür>.<metot>(…)` dışındaki deyimler reddedilir. Sözleşme
`eslint.config.js` içinde kalır (toolchain-worker bu dosyayı güvenilir kopyasıyla hash'le karşılaştırır;
değiştiğinde `toolchain/e2e-deps/eslint.config.js` de güncellenmelidir).

**İzinli içe aktarma:** yalnızca `import { test } from "../fixtures";` ya da
`import { signedInTest as test } from "../fixtures";` (ikisi birlikte de olabilir). `@playwright/test`,
`pages/**` (locators dahil), Node modülleri, dinamik `import()` ve `expect` yasaktır.

**Fikstürler** (test gövdesinin parametresi olarak): `loginPage`, `catalogPage`, `cartPage`,
`orderPage`. `page`, `request`, `context`, `browser`, `process` adları kullanılamaz.
`dealer` fikstürü her testte otomatik çalışır (bayi sıfırlama, `BREAK_CAMPAIGN` kırılması, kilit).

**Bayi seçimi:**
- Case giriş adımı içermiyorsa `signedInTest`: işçinin bayisi API ile oturum açmış başlar; ilk adım
  genelde `catalogPage.goto()`.
- Case belirli bir bayiyle arayüzden giriş yapıyorsa (`LoginPage.login("bayi2", "Demo123!")`)
  `test` + dosya düzeyinde `test.use({ dealerUsername: "bayi2" });`. Böylece case metnindeki
  kullanıcı adı, parola ve bayiye özgü beklenen değerler (bayi adı, kredi limiti) literal kalır ve
  doğru bayinin verisi sıfırlanmış olur. `test.use` yalnızca `dealerUsername` alır; izinli değerler
  `bayi1`, `bayi2` (`bayi3` doğrulama ajanınındır, reddedilir).

**Gövde:** doğrusal; adım başına bir `await <po>.<metot>(<literal argümanlar>);`, ardından
`expect*` çağrıları. Argümanlar `JSON.stringify` ile basılmış `string`/`number` literal'leridir
(şablon dizgisi yok). `if`/`?:`/`&&`/döngü/`try`/`throw`/`new`/fonksiyon ve sınıf tanımı yasak;
`test.skip|fixme|fail|only|slow|setTimeout|step|extend|info` ve kanca (`beforeEach`…) yasak.
`test.describe(...)` serbesttir.

**Kullanılabilir metotlar** (tam liste: `POST /symbols`; hepsi `Promise<void>`):

| Sınıf | Eylemler | Doğrulamalar |
|---|---|---|
| `LoginPage` | `goto()`, `login(kullaniciAdi, parola)`, `logout()` | `expectLoggedIn(bayiAdi)`, `expectLoginError(mesaj)`, `expectOnLoginPage()` |
| `CatalogPage` | `goto()`, `openFromMenu()`, `setQuantity(kod, adet)`, `addToCart(kod, adet)` (adedi yazar, "Sepete ekle"ye basar, sepet isteğini bekler), `openCart()` | `expectProductVisible(kod)`, `expectProductPrice(kod, tutar)`, `expectCampaign(kod, kampanyaAdi)`, `expectCartCount(n)` |
| `CartPage` | `goto()`, `removeProduct(kod)`, `checkout()` | `expectLineQuantity(kod, adet)`, `expectFreeQuantity(kod, adet)`, `expectLineTotal(kod, tutar)`, `expectSubtotal(tutar)`, `expectDiscount(tutar)`, `expectTotal(tutar)`, `expectMinOrderWarning(metin)` (içerir), `expectNoMinOrderWarning()`, `expectCheckoutEnabled()`, `expectCheckoutDisabled()`, `expectProductNotInCart(kod)`, `expectEmpty()`, `expectCartCount(n)` |
| `OrderPage` | `gotoHistory()`, `openHistory()` | `expectConfirmation()` (onay alanı + `SP-######` numarası), `expectConfirmedTotal(tutar)`, `expectConfirmedOrderInHistory()`, `expectOrderInHistory(numara)`, `expectOrderTotalInHistory(numara, tutar)`, `expectNoOrders()` |

Tutarlar arayüz biçimindedir (`"1.250,00 TL"`); adetler `number`. `OrderPage.readOrderNumber()`
değer döndürdüğü için üretilen testte kullanılmaz (sipariş numarası case metninde olamaz); geçmiş
kontrolü `expectConfirmedOrderInHistory()` ile yapılır.

Örnek (şablonun beklenen çıktısı):

```ts
// AI-generated (Testing Probe) — case <uuid> · TPD-1 · elle düzenlemeyin
import { test } from "../fixtures";

test.use({ dealerUsername: "bayi1" });

test.describe("TPD-1 · Kampanya", () => {
  test("7 adet Portakal Gazozu → 1 adet bedava", async ({ loginPage, catalogPage, cartPage }) => {
    await loginPage.goto();
    await loginPage.login("bayi1", "Demo123!");
    await catalogPage.addToCart("P-001", 7);
    await catalogPage.openCart();
    await cartPage.expectFreeQuantity("P-001", 1);
  });
});
```

Bir doğrulama yanlış değerde Playwright `expect(...)... failed` assertion hatası verir (kurulum
hatası değil); yerel kontrol bu ayrımla "defect adayı"nı locator/eşleme hatasından ayırır.
`npm run break-verify` (`BREAK_VERIFY_GREP` ile) üretilen testlere de aynen uygulanır.

## Locator kırılması ve onarımı (`make break`, Faz 4)

- **Kırılma:** forge'daki `demo/break-locator` dalı `main` + tek commit'tir ve yalnızca
  `web/src/pages/CatalogPage.tsx`'teki "Sepete ekle" butonunun `data-testid` değerini
  `add-to-cart` → `cart-add` yapar (rol `button`, ad "Sepete ekle", ürün kartı `product-card-<kod>`
  aynı kalır). Dal `scripts/forge-init.sh` tarafından üretilir ve doğrulanır (web/src dışı ya da bu
  değer dışı fark reddedilir). `web/src` içinde `"add-to-cart"` tam olarak bir yerde geçmelidir.
- **Kırmızı:** butona basan her test `CatalogPage.addToCart` içinde
  `locator.click: Timeout … waiting for getByTestId('product-card-P-00x').getByTestId('add-to-cart')`
  ile kalır (toolchain türü `locator_timeout`). `tests/locators.spec.ts` rol/ad karşılaştırmasından önce
  testId'nin kendisini arar; kırık testId orada da assertion değil
  `expect(locator).toBeAttached() … getByTestId('product-card-P-001').getByTestId('add-to-cart') …
  element(s) not found` olarak görünür (`locator_not_found`). Kırılma yüzünden **assertion türünde
  kırmızı test oluşmaz**; triage bunu ürün hatası değil test bakımı sayar.
- **Aday:** `catalog.addToCart` `within: "product-card-"` taşır; `/locator-probe {role:"button",
  name:"Sepete ekle", url_path:"/katalog", scope_test_id:"product-card-P-001"}` kırık uygulamada
  `matches: 1, test_id: "cart-add"` döner (kapsamsız 4 eşleşme → öneri yok).
- **Onarım:** yalnızca `e2e/pages/catalog/locators.ts` → `addToCart.testId: "cart-add"`
  (ast-guard `--mode repair` geçer; başka dosya/alan değişmez). Onarımdan sonra tüm e2e yeşildir.
- `ci/locator-break-verify.sh` bu dört adımı çalışma ağacına dokunmadan (geçici kopyada, webServer
  ile) uçtan uca sınar.

### Çalışan uygulamayı forge `main`'den servis etmek

Compose `demo-app-web`'i çalışma ağacındaki `demo-app/web`'den derler (= `demo-baseline`). `make break`,
`make demo-baseline` ve `make up` içindeki `sync-web`, imajı bunun yerine forge `main` HEAD'inin `web/`
arşivinden derler (`scripts/forge-init.sh`: `forge_demo archive --ref main --path web | docker build -`)
ve servisi yeniden oluşturur; derlenen commit `/forge/demo-app-web.sha`'ya yazılır (toolchain
`TP_APP_BUILD_SHA_FILE`). `web/Dockerfile` bağımsızdır: bağlam yalnızca `web/` dizinidir, yani herhangi
bir commit'in `web/` arşivi doğrudan derlenebilir:

```bash
git --git-dir=/forge/demo-app.git archive <sha> web | tar -x --strip-components=1 -C /tmp/web
docker build -t testingprobe-demo-app-web:local \
  --build-arg DEMO_APP_BUILD_SHA=<sha> \
  --build-arg DEMO_APP_WEB_TREE="$(git --git-dir=/forge/demo-app.git rev-parse <sha>:web)" /tmp/web
docker compose up -d --no-build --no-deps --force-recreate demo-app-web
```

İsteğe bağlı derleme argümanları `DEMO_APP_BUILD_SHA` ve `DEMO_APP_WEB_TREE` (yalnızca onaltılık; boş
varsayılan) çalışan uygulamada `GET /build.json` → `{"service":"demo-app-web","sha":"…","web_tree":"…"}`
olarak döner (`Cache-Control: no-store`). Compose'un çalışma ağacı derlemesinde ikisi de `""`'dir.
Onarım PR'ı yalnızca `e2e/` değiştirdiği için `web/` ağacı (ve dolayısıyla çalışan uygulama) aynı kalır:
`web_tree` karşılaştırması merge sonrası yeniden derlemeye gerek olmadığını gösterir.

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
bash ../ci/locator-break-verify.sh             # locator kırılması: kırmızı (yalnızca getByTestId('add-to-cart')
                                               # locator hatası) → locators.ts testId onarımı → tamamı yeşil
npm run lint:generated-selftest                # üretilen test ESLint sözleşmesinin öz denetimi
node tools/scenario-neutral-check.js [--selftest]  # el yazımı testler 6. adet kampanya sınırını doğrulamaz
                                               # (senaryoya bağlı: ana yol vs f2-kod-hatasi; run-checks.sh koşar)
node tools/trace-token-selftest.js             # kırmızı koşunun trace/artefaktlarında DEMOAPP_TEST_TOKEN yok
                                               # (/test/* çağrıları izlenmeyen Node fetch ile gider)

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
