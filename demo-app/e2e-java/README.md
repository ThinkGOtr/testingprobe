# e2e-java — web e2e (Playwright for Java + TestNG)

Bayi Sipariş Portalı'nın **web** arayüzü için Java test projesi (specs/011-uretim-dili §2.5). Kod
üretimi "üretim dili = java" seçildiğinde onaylı case'leri buradaki page object'lere şablonla
(`rules/templates/playwright_testng.java.j2`) çevirir; proje page object kütüphanesini, test tabanını
ve rapor/kanıt altyapısını sağlar. TypeScript karşılığı `../e2e`, uygulama (Appium) karşılığı
`../e2e-app`; konvansiyon e2e-app ile aynıdır (toolchain/java-araclar değişmeden çalışır).

```
src/test/java/com/antreklabs/bayi/
  altyapi/   TestTabani (Playwright yaşam döngüsü, fikstür erişimcileri), Tarayici (iş parçacığı başına
             Playwright + Chromium), Ayarlar, Bayiler/@Bayi/BayiKilidi, TestVerisi (/test/reset, /test/break),
             OturumAcik (signedIn), Kanit, ExtentRaporu
  ekranlar/  Ekran (taban), LoginPage, CatalogPage, CartPage, OrderPage, Kimlikler (data-testid, saf veri)
  testler/   elle yazılmış testler (*Test.java; TS login/cart/order/dealers karşılıkları)
  uretilen/  şablondan üretilen testler (tek yazar: AI Testing Probe) + package-info.java
  birim/     tarayıcısız birim/sözleşme testleri (grup "birim")
araclar/KirmiziDenetimi.java   kırarak doğrulamanın kırmızı adım denetimi
testng.xml                     tarayıcı süiti (testler + uretilen; parallel="classes", 2 iş parçacığı)
```

## Page object sözleşmesi (TS ile birebir)

- `ekranlar/` sınıf adları, public metot adları, parametre adları ve sırası `../e2e/pages` ile **aynıdır**
  (`LoginPage.login(username, password)`, `CatalogPage.addToCart(productCode, quantity)`); tür eşlemesi
  `string→String`, `number→int` (tamsayı) / `double`, `boolean→boolean`; dönüş `void`
  (`OrderPage.readOrderNumber()` TS'deki gibi `String` döner; yalnız elle yazılmış testler kullanır).
- **Ayrılmış sözcük istisnası:** TS metot adı Java'da ayrılmış sözcükse Java adı tek bir sabit tablodan
  gelir (`JAVA_AD_ESLEME`; core: `tp_core.features.codegen.platform`). Bugün tek giriş:
  `goto` → `goTo` (`LoginPage/CatalogPage/CartPage.goTo()`).
- Fikstür adları TS `interface Fixtures` ile aynı: `TestTabani`'nda `dealer()`, `signedIn()`,
  `loginPage()`, `catalogPage()`, `cartPage()`, `orderPage()` (+ elle yazılmış testler için `page()`).
- Eşitlik iki yerde sabitlenir: `core/tests/unit/features/codegen/test_e2e_java_esitlik.py` (TS kaynağı ↔
  `symbols-java-web.json`) ve `birim/SozlesmeBirimTesti` (Kimlikler ↔ TS `locators.ts` ↔ `../kimlikler.json`).

### Kimlikler (`ekranlar/Kimlikler.java`)

Saf veri: iç içe `public static final class` grupları + `public static final String` sabitleri. Grup =
TS locator dosyası (`nav`, `login`, `catalog`, `cart`, `order` → `Nav`, `Login`, …), sabit adı = TS
anahtarının BÜYÜK_HARF karşılığı; önekler `_ONEK` ile biter (`cart.lineQuantity` → `Cart.LINE_QUANTITY_ONEK`).
TS `within` (kapsamlı locator) şöyle modellenir: kapsayıcının içinde aranan kimlikler, kapsayıcının adını
taşıyan iç gruptadır — `Catalog.ProductCard.ADD_TO_CART` kapsayıcısı `Catalog.PRODUCT_CARD_ONEK` +
ürün kodudur (`Ekran.kapsam(...)` / `kapsamda(...)`). Onarım yalnızca literal değeri değiştirir
(`java-araclar locators patch`).

## Üretilen test biçimi

`uretilen/<Story>WebC<sıra>_<uuid8>Test.java`; örnek (TS altını `golden/tpd-1-c2.spec.ts`'nin karşılığı):
`uretilen/TPD1WebC2_3f9b1c2eTest.java`. Yalnız `// AI-generated` başlık yorumları, üç import
(`altyapi.Bayi`, `altyapi.TestTabani`, `org.testng.annotations.Test`), en çok bir `@Bayi("…")`, tek
`@Test(groups = {"uretilen", "web", "tp-case-<uuid>", …}, description = "…")` metodu ve
`erisimci().metot(literal, …);` satırları. `java-araclar guard` denetler.

Örnek, Java web şablonunun gerçek render çıktısıdır: `core/tests/unit/features/codegen/golden/
TPD1WebC2_3f9b1c2eTest.java` ile **bayt eşittir** (`test_e2e_java_esitlik.py` sabitler). Golden
değişirse örneği kopyalayın ve `ci/run-java-checks.sh` ile guard + derleme + koşuyu doğrulayın.

## Kurulum ve koşu

Java 17. Maven depoda yok: sarmalayıcı (`./mvnw`, 3.9.x, SHA-256 doğrulamalı). macOS'ta ilk kurulumda
`PATH=/usr/bin:/bin:$PATH ./mvnw …` (bkz. toolchain/java-araclar/README.md).

### Tarayıcı kurulumu

Testler tarayıcıyı **indirmez** (`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`); Chromium
`PLAYWRIGHT_BROWSERS_PATH`'ten (verilmezse Playwright'ın varsayılan önbelleği: macOS
`~/Library/Caches/ms-playwright`, Linux `~/.cache/ms-playwright`) açılır. Playwright for Java sürücüsü
depo kökündeki `.playwright-version` ile aynı çekirdeği paketler (`birim/SurumBirimTesti`), bu yüzden TS
hattının indirdiği tarayıcı burada da kullanılır:

```bash
npx --yes "playwright@$(cat ../../.playwright-version)" install chromium
```

### Komutlar

```bash
./mvnw -q test-compile                 # derleme
./mvnw -q test -Dgroups=birim          # birim/sözleşme testleri (tarayıcı ve uygulama gerekmez)
BASE_URL=http://127.0.0.1:8081 DEMO_API_URL=http://127.0.0.1:18000 DEMOAPP_TEST_TOKEN=… ./mvnw test
../ci/run-java-checks.sh               # pom kilidi → guard → derleme → birim → tarayıcı (CI ile aynı)
../ci/break-verify-java.sh             # kırarak doğrula: yeşil → kırmızı → yeşil (token gerekir)
```

`break-verify-java.sh` yalnız **`kampanya` grubunu** koşar (`BREAK_VERIFY_GROUPS` ile değişir);
`uretilen/` testleri (grup `uretilen`, `web`, …) ve diğer gruplar kırarak doğrulamaya girmez —
onların kırmızısı tam koşuda (`run-java-checks.sh`) görülür.

Test JVM'i: pom `argLine` = `-Xmx512m -Dfile.encoding=UTF-8` (test-runner bellek sınırı; kodlama
JVM açılışında verilir). `-DargLine=…` ile değiştirilebilir.

Uygulamayı yerelde ayrı portlarda başlatmak (paylaşılan yığına dokunmadan):
`PORT=18181 DEMO_API_PORT=18100 DEMOAPP_TEST_TOKEN=$(openssl rand -hex 24) scripts/github-demo-serve.sh`
(repo kökünden), sonra `BASE_URL=http://127.0.0.1:18181 DEMO_API_URL=http://127.0.0.1:18100`.

| Sistem özelliği | Ortam | Varsayılan |
|---|---|---|
| `base.url` | `BASE_URL` | `http://127.0.0.1:8081` |
| `demo.api.url` | `DEMO_API_URL`, `API_URL` | `<base.url>/api` (web vekili; compose nginx `/api/test/`'i açmaz → API'yi verin) |
| `demoapp.test.token` | `DEMOAPP_TEST_TOKEN` | — (yoksa `TP_E2E_NO_RESET=1` ile yalnız sepet yalıtımı; `sifir-veri` testleri atlanır) |
| `break.campaign` | `BREAK_CAMPAIGN` | — (`1`: bayi kapsamlı kampanya kırılması) |
| `headless` | `HEADLESS` | `true` |
| `bekleme.ms` / `gezinme.ms` | `BEKLEME_MS` / `GEZINME_MS` | 5000 / 10000 (TS expect/action ve navigation) |
| `bayi.kilit.ms` | `BAYI_KILIT_MS` | 40000 |
| `kanit.dizini` | `KANIT_DIZINI` | `target/kanit` |

Veri yalıtımı TS fixtures ile aynıdır: her test bayisini (`bayi1`/`bayi2`, işçi yuvası ya da `@Bayi`)
süreçler arası kilitle alır ve yalnız o bayinin verisini `POST /test/reset` ile sıfırlar; doğrulama
ajanının bayisi (`bayi3`) hiçbir zaman kullanılmaz. Eşzamanlı test sayısı bayi sayısını aşarsa
(`thread-count`), yuva bekleyen test bir yuva boşalana dek `bayi.kilit.ms` kadar bekler; sonra hata. Token yalnız `HttpClient` başlığında taşınır
(Playwright isteği olmadığı için trace'e düşmez).

## Raporlar ve kanıt (`target/`)

`surefire-reports/TEST-*.xml` (JUnit), `allure-results/`, `extent-report/index.html` (tek dosya, çevrimdışı),
başarısız testte `kanit/<Sınıf>.<metot>/{ekran.png, trace.zip, sayfa.html}` (trace:
`npx playwright show-trace trace.zip`), `guard.json` (run-java-checks.sh).

- **Extent:** test adı `@Test(description)` (yoksa `Sınıf › metot`), altında `Sınıf.metot`;
  kategoriler TestNG gruplarıdır, `tp-case-*` hariç (case kimliği testin ayrıntısında
  `Testing Probe case: <uuid>` satırı). `extent.json` arşivi yalnız `-Dextent.tekrar=<i>/<n>` ile
  `i > 1` tekrarında geri yüklenir (tekrarlar tek raporda); tekrarsız koşu ve ilk tekrar arşivi
  siler — `clean`'siz yeniden koşuda eski sonuçlar rapora karışmaz.
- **Extent ekran/bellek:** başarısız testin `ekran.png`'si modele ve arşive dosya yolu olarak girer,
  koşu sonunda base64 gömülür; en çok 50 ekran (koşu geneli, önceki tekrarlar dahil), fazlası
  `../kanit/…` bağlantısı. Rapor ve arşiv geçici dosyaya yazılıp atomik taşınır: yazım (ör. bellek
  yetersizliği) yarıda kalırsa önceki geçerli `index.html` kalır, yanına `index.uyari.txt` yazılır.
  Ara yazım her 25 testte / 30 sn'de bir; kesintide (SIGTERM) kapanış kancası son durumu yazar.
- **Allure:** `TestTabani` gruplardan etiket ekler: her grup `tag`, Jira anahtarı biçimindeki grup
  (`TPD-1`) `story`, `tp-case-<uuid>` ayrıca `tp-case=<uuid>` (`altyapi/TestGruplari`).

## Sembol tablosu fikstürü

`core/tests/unit/features/codegen/symbols-java-web.json` bu projenin `java-araclar symbols` çıktısıdır.
Page object ya da Kimlikler değişince yenileyin (komut: `test_e2e_java_esitlik.py` modül belgesi):

```bash
(cd toolchain/java-araclar && ./mvnw -B -q package -DskipTests)
java -jar toolchain/java-araclar/target/java-araclar.jar symbols --root demo-app/e2e-java \
  | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin), ensure_ascii=False, indent=1))' \
  > core/tests/unit/features/codegen/symbols-java-web.json
```

Jar derliyse eşitlik testi fikstürün güncelliğini de denetler.
