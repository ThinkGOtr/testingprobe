# demo-app — Bayi Sipariş Portalı (örnek uygulama)

AI Testing Probe'un test ettiği örnek uygulama (web, Android/iOS ve Windows sürümleri): giriş,
katalog, sepet, "6 al 1 bedava" kampanyası, minimum sipariş tutarı, sipariş onayı ve geçmiş. Marka yoktur, tüm veri sentetiktir.

| Dizin | İçerik | Compose servisi |
|---|---|---|
| `api/` | Python 3.12 + FastAPI + SQLAlchemy 2 (`uv`). Postgres (compose) veya SQLite (CI / test-runner). Şema + deterministik tohum açılışta idempotent kurulur. | `demo-app-api` (:8000, yalnızca iç ağ) |
| `web/` | React 18 + Vite + TypeScript; nginx ile servis edilir (`/api/*` → API). `vite preview` aynı proxy'yi kullanır. | `demo-app-web` (host: `127.0.0.1:8081`) |
| `e2e/` | Playwright: page object kütüphanesi (`pages/`), elle yazılmış testler (`tests/`). | `test-runner` içinde |
| `ci/run-checks.sh` | `npm ci --ignore-scripts` → `tsc` → `eslint --no-inline-config` → `playwright test` (argümanlar aynen geçer). GitHub CI ve yerel test-runner aynı betiği kullanır. | — |
| `mobile/` | Expo SDK 58 / React Native 0.88 mobil sürüm (iOS + Android), aynı API ve aynı kimlikler. `scripts/derle-android.sh` → `build/bayi-siparis.apk`, `scripts/derle-ios.sh` → `build/BayiSiparis.app` (simülatör). Ayrıntı: [mobile/README.md](mobile/README.md) | — (cihazda; `make cihaz-baslat` kurar) |
| `desktop/` | WPF / .NET 8 Windows masaüstü sürümü, `AutomationId` = web `data-testid`. macOS'ta derlenir, yalnız Windows'ta çalışır; `scripts/yayinla.sh` → `build/<rid>/BayiSiparis.exe`. Ayrıntı: [desktop/README.md](desktop/README.md) | — (Windows VM / `windows-latest`) |
| `e2e-app/` | Java 17 + Appium java-client + TestNG (Maven): ekran nesneleri (`ekranlar/`, kimlikler `Kimlikler.java`), referans testler, üretilen testler (`uretilen/`). Ayrıntı: [e2e-app/README.md](e2e-app/README.md) | `test-runner` içinde (Java yolu) ya da host |
| `ci/run-app-checks.sh` · `ci/break-verify-app.sh` | `run-checks.sh` / `break-verify.sh`'in Java karşılıkları: `<android\|ios\|windows> [mvn argümanları]`. GitHub iş akışları (`mobil-android`, `mobil-ios`, `masaustu-windows`) aynı betiği kullanır. | — |
| `e2e-java/` | Web için Java hattı (011): Java 17 + Playwright for Java + TestNG (Maven). Page object'ler `e2e/pages` ile birebir aynı sözleşme (`LoginPage`, `CatalogPage`, …; `goto` → `goTo`), kimlikler `ekranlar/Kimlikler.java`, referans testler, üretilen testler (`uretilen/`). Ayrıntı: [e2e-java/README.md](e2e-java/README.md) | `test-runner` içinde (Java web yolu) ya da host |
| `ci/run-java-checks.sh` · `ci/break-verify-java.sh` | Web Java hattı: pom kilidi → `java-araclar guard` → derleme → birim → tarayıcı koşusu; kırarak doğrula. GitHub iş akışı `web-java` aynı betiği kullanır. | — |
| `kimlikler.json` | Erişilebilirlik kimliği sözleşmesi (009 plan §2.2): web `data-testid` listesi, ekran ve önek bilgisiyle. Web kaynağından üretilir (`cd mobile && npm run kimlik-uret`), elle düzenlenmez; mobil (`npm run kimlik-kontrol`) ve e2e-app birim denetimleri buna karşı koşar (masaüstü `scripts/kimlik-kontrol.py` web kaynağını doğrudan okur). | — |

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
| POST | `/test/break` `{kullanici_adi, kampanya?, hata?}` | Aynı koruma. **Bayi kapsamlı** demo kırılması ("kırarak doğrula") ve ekilmiş hata: `hata=<kod>` yalnızca o bayinin katalog/sepet/sipariş hesabını o hatayla çalıştırır (`test_kirilma.hata`; bayi başına tek hata); `kampanya=true` geriye uyumludur ve `hata="kampanya_bedava_yok"` ile aynıdır; `hata=null` / `kampanya=false` kaldırır. Bilinmeyen kod 422. Yanıt `{kullanici_adi, kampanya, hata}`. Diğer bayiler, paylaşılan uygulama ve MCP etkilenmez. `/test/reset` kırılmayı da kaldırır |
| GET | `/test/faults` | Aynı koruma. Ekilmiş hata kataloğu `{hatalar: [{kod, tur, ad, aciklama}]}` (bkz. "Ekilmiş hatalar") |

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
  - `TP_FAULT=<kod>` (`^[a-z0-9_]{1,40}$`): aynı yerde `/test/break {hata: kod}` açılır, test
    sonunda `{hata: null}` ile kaldırılır (token gerekir). `BREAK_CAMPAIGN=1` ile birlikteyse
    `TP_FAULT` geçerlidir. Java (`e2e-app`, `TestTabani`) aynı kuralı uygular.
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
olmayan argüman ve `await <fikstür>.<metot>(…)` dışındaki deyimler reddedilir. Tek istisna
(specs/013 K19): gizli test verisi doğrudan çağrı argümanı olarak `process.env.TP_TESTVERI_<AD>`
biçiminde ortamdan okunabilir; ad `tests/testveri-env.d.ts`'te `string` olarak bildirilmelidir
(strict + `noUncheckedIndexedAccess` altında tsc'nin geçmesi için) ve koşum ortamı (test-runner,
CI) bu değişkeni vermelidir. Sözleşme
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

## Ekilmiş hatalar

Hata kataloğu `api/src/demoapp_api/faults.py` (012 §4.6; `GET /test/faults`). Her hata **bayi
bazında** `POST /test/break {kullanici_adi, hata}` ile açılır; yalnızca o bayinin katalog, sepet ve
sipariş hesabı etkilenir (diğer bayiler, `bayi3` ve test modu dışı süreçler etkilenmez). `kod`
hataları hesap kuralını değiştirir; `veri` hataları okunan değeri o bayi için ezer, `ayar` / `urun`
/ `kampanya` tablolarına yazmaz. `/test/reset` hatayı da kaldırır. `test_kirilma.hata` kolonu,
kolonsuz eski veritabanında açılışta eklenir (SQLite ve Postgres). Test süreçleri `TP_FAULT=<kod>`
ile çalışır (web fixture, Java `TestTabani`, toolchain `/run` ve `/check` `fault`).

| Kod | Tür | Etki |
|---|---|---|
| `kampanya_bedava_yok` | kod | Bedava adet 0 (`kampanya: true` ile aynı) |
| `kampanya_tek_bedava` | kod | Bedava adet en çok 1: `min(1, adet // 6)` (6 ve 7 adette doğru görünür; 14 adette 2 yerine 1) |
| `kampanya_cift_indirim` | kod | Kampanya indirimi iki kez düşülür |
| `min_siparis_haric` | kod | Minimum sınır dahil değil (`toplam > min`) |
| `min_siparis_muafiyet_yok` | kod | Kampanyalı sepet de minimuma tabi |
| `min_siparis_500` | veri | Minimum 750,00 → 500,00 (story AC3 metnindeki eski değer) |
| `min_siparis_1000` | veri | Minimum 750,00 → 1.000,00 |
| `fiyat_p004_31` | veri | P-004 fiyatı 30,00 → 31,00 |
| `kampanya_urunu_p002` | veri | Kampanyalı ürün P-001 → P-002 |

Ürün tarafındaki kopya `rules/hata-katalogu.yaml` her hata için ayrıca ilgili kabul kriterlerini
(`ac_refs`), onaylı karar tablosunu (`tablo`: `T1` kampanya, `T2` minimum sipariş) ve hatayı
gösteren en küçük girdiyi (`ayirt_edici`: girdi, doğru ve hatalı çıktı) taşır. `kampanya_esik_7`
(`adet // 7`) katalogdan çıkarıldı: story'nin "7 adette 1 bedava" kuralıyla aynı davranıştır,
hata değildir (012 §13 K9).

**Hata → kırmızı test matrisi** (el yazımı web testleri, 33 test, Chromium, yerleşik webServer +
SQLite, `DEMO_API_PORT=18200 DEMO_WEB_PREVIEW_PORT=18281`, `workers: 2` → bayi1 ve bayi2;
`TP_FAULT=<kod> npx playwright test`; hatasız temel ve kapanış koşuları 33/33 yeşil; 2026-11-12).
Sayım 012 K12'ye göredir: bir test hatayı ancak temelde yeşilken hatalı koşuda **assertion** ile
kırmızıya dönerse yakalar; locator/zaman aşımı kırmızısı kanıt sayılmaz (tür toolchain'in
`failure.type`'ından). `tests/generated/` depoda boş olduğu için kıran testlerin tamamı el
yazısıdır (`el`): ürünün ana oranı (yalnız üretilen testler) bu suite'le **ölçülmez**; aşağıdaki
oran el yazısı suite'in oranıdır.

| Kod | Kırmızı | Assertion ile kıran testler | Kanıt sayılmayan (locator/zaman aşımı) | Sonuç |
|---|---|---|---|---|
| `kampanya_bedava_yok` | 3 | cart `kampanya: 7 adet P-001 → 1 bedava…`; order `onaylanan sipariş numarasıyla gösterilir…`; page-objects `7 adet Portakal Gazozu sepette 1 bedava…` | — | yakalandı |
| `kampanya_tek_bedava` | 0 | — | — | **kaçtı** (el yazımı testler kampanyalı üründe en çok 7 adet dener; 6 ve 7 adette iki kural aynı sonucu verir. Ayırt edici girdi 14 adet: üretilen testin işi) |
| `kampanya_cift_indirim` | 2 | cart `kampanya: 7 adet P-001…`; order `onaylanan sipariş numarasıyla…` | — | yakalandı |
| `min_siparis_haric` | 2 | cart `minimum tutara ulaşınca uyarı kalkar…` | page-objects `onaylanan sipariş geçmişte numarasıyla bulunur` (onay butonu pasif → `locator.click` zaman aşımı) | yakalandı |
| `min_siparis_muafiyet_yok` | 1 | cart `kampanyalı siparişte minimum tutar aranmaz` | — | yakalandı |
| `min_siparis_500` | 4 | a11y `sepet sayfası (uyarı ve satırlarla)`; cart `kampanyasız siparişte minimum tutar altında uyarı…`; order `minimum tutarın altındaki sepet API'de de reddedilir`; page-objects `indirimsiz sepette minimum tutar uyarısı…` | — | yakalandı |
| `min_siparis_1000` | 7 | a11y `sepet sayfası…`; cart `kampanyasız siparişte minimum…`, `minimum tutara ulaşınca…`; order `minimum tutarın altındaki sepet…`; page-objects `indirimsiz sepette…` | page-objects `onaylanan sipariş geçmişte…`, locators `menü, katalog, sepet ve sipariş sayfaları` (ikisi de `locator.click` zaman aşımı) | yakalandı |
| `fiyat_p004_31` | 5 | cart `katalog ürünleri ve fiyatları…`, `minimum tutara ulaşınca…`; mobile `satır tutarı ve Kaldır butonu…`; order `onaylanan sipariş numarasıyla…`; page-objects `onaylanan sipariş geçmişte…` | — | yakalandı |
| `kampanya_urunu_p002` | 8 | cart `katalog ürünleri…`, `kampanya: 7 adet P-001…`, `kampanyasız üründe bedava adet verilmez`, `kampanyasız siparişte minimum…`, `kampanyalı siparişte minimum tutar aranmaz`; order `onaylanan sipariş numarasıyla…`; page-objects `7 adet Portakal Gazozu…` | a11y `sepet sayfası…` (`toContainText` zaman aşımı, öğe yok → `locator_not_found`) | yakalandı |

El yazısı suite: yakalanan 8/9 (oran %89); kaçan `kampanya_tek_bedava`. Temelde kırmızı test yok,
kapanış yeşil: kredi geri alınmadı. El yazımı testler bu hatayı yakalamak için değiştirilmez; sınır
vakası onaylı T1'den üretilen testlerin işidir.

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
TP_FAULT=min_siparis_500 npx playwright test   # ekilmiş hata (bkz. "Ekilmiş hatalar"); bayi kapsamlı
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
