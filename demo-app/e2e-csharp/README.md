# e2e-csharp — web e2e (Playwright .NET + NUnit, .NET 10)

Bayi Sipariş Portalı'nın **web** arayüzü için C# test projesi (specs 014 test dilleri §3.2). Kod
üretimi "üretim dili = csharp" seçildiğinde onaylı case'leri buradaki page object'lere şablonla
(`rules/templates/playwright_nunit.cs.j2`) çevirir; proje page object kütüphanesini, test tabanını ve
rapor/kanıt altyapısını sağlar. TypeScript karşılığı `../e2e`, Java karşılığı `../e2e-java`.

```
Altyapi/     TestTabani (NUnit tabanı: Playwright yaşam döngüsü, erişimciler, Gizli), Tarayici (süreç başına
             Playwright + Chromium), Ayarlar, Bayiler/[Bayi]/BayiKilidi, TestVerisi (/test/reset, /test/break),
             [OturumAcik] (signedIn), Kanit, Montaj (paralellik + koşu sonu kapanışı)
Pages/       Ekran (taban), LoginPage, CatalogPage, CartPage, OrderPage, Kimlikler (data-testid, saf veri)
Tests/       elle yazılmış testler (*Tests.cs; TS login/cart/order/dealers karşılıkları)
Tests/Generated/  şablondan üretilen testler (tek yazar: AI Testing Probe)
Birim/       tarayıcısız birim/sözleşme testleri (kategori "birim")
araclar/kirmizi_denetimi.py   kırarak doğrulamanın kırmızı adım denetimi (yalnız Python stdlib)
```

Kök dosyalar: `Antreklabs.Bayi.E2e.csproj`, `Directory.Packages.props` (merkezi, tam sabit sürümler),
`packages.lock.json` (kilit; restore `--locked-mode`), `nuget.config` (yalnız nuget.org). Bu dört dosya
toolchain'deki güvenilir kopyalarla (`toolchain/e2e-csharp-deps/web/`) **bayt eşit** olmalıdır; başka
`.props/.targets/.rsp/.sln(x)/global.json` kabul edilmez (MSBuild bunları okur ve kod çalıştırabilir).
Çözüm dosyası bilerek yoktur: kökte proje + çözüm birlikte olunca `dotnet build` hangisini derleyeceğini
seçemez (MSB1011) ve kilit denetimi bir girdi daha izlemek zorunda kalır.

| Paket | Sürüm |
|---|---|
| Microsoft.Playwright | 1.64.1 (= depo kökü `.playwright-version`; `Birim/SurumTests`) |
| NUnit / NUnit3TestAdapter | 4.6.1 / 6.3.1 |
| Microsoft.NET.Test.Sdk | 18.12.0 |
| JunitXml.TestLogger | 8.1.0 |
| Allure.NUnit | 2.15.0 (geçişli: AspectInjector 2.8.1 — derleme zamanı IL dokuyucusu) |

## Page object sözleşmesi (TS ile birebir)

- `Pages/` sınıf adları, parametre adları ve sırası `../e2e/pages` ile **aynıdır**; metot adı TS adının
  PascalCase + `Async` biçimidir: `LoginPage.LoginAsync(username, password)`,
  `CatalogPage.AddToCartAsync(productCode, quantity)`, `goto` → `GotoAsync`. Tür eşlemesi
  `string→string`, `number→int`, `boolean→bool`; dönüş `Task` (`OrderPage.ReadOrderNumberAsync()` TS'deki
  gibi `Task<string>` döner; yalnız elle yazılmış testler kullanır).
- Erişimci adları page object sınıf adlarıdır: `TestTabani`'nda `LoginPage`, `CatalogPage`, `CartPage`,
  `OrderPage` (+ elle yazılmış testler için `Page`, `Dealer`, `SignedInAsync()`).
- Eşitlik `Birim/SozlesmeTests` ile sabitlenir: page object'ler ↔ TS `*.page.ts`, Kimlikler ↔ TS
  `locators.ts` ↔ `../kimlikler.json` ↔ Java `Kimlikler.java` (sabit adları birebir), `TestTabani`
  erişimcileri.

### Kimlikler (`Pages/Kimlikler.cs`)

Saf veri: `public static class Kimlikler` içinde iç içe `public static class` grupları + `public const
string` sabitleri. Grup ve sabit adları Java `Kimlikler.java` ile aynıdır (`Nav`, `Login`, `Catalog`,
`Cart`, `Order`; `cart.lineQuantity` → `Cart.LINE_QUANTITY_ONEK`); önekler `_ONEK` ile biter. TS
`within` kapsayıcının adını taşıyan iç gruptadır (`Catalog.ProductCard.ADD_TO_CART`, kapsayıcı
`Catalog.PRODUCT_CARD_ONEK` + ürün kodu; `Ekran.Kapsam(...)` / `Kapsamda(...)`). Onarım yalnızca literal
değeri değiştirir (`cs-araclar locators patch`).

## Üretilen test biçimi

`Tests/Generated/<Story>WebC<sıra>_<uuid8>Tests.cs`, ad alanı `Antreklabs.Bayi.Tests.Generated`; örnek
`TPD1WebC2_3f9b1c2eTests.cs` şablonun gerçek render çıktısıdır ve
`core/tests/unit/features/codegen/golden/csharp/TPD1WebC2_3f9b1c2eTests.cs` ile **bayt eşittir**. Yalnız
`// AI-generated` başlık yorumları, üç `using` (`System.Threading.Tasks`, `Antreklabs.Bayi.Altyapi`,
`NUnit.Framework`), en çok bir `[Bayi("…")]`, `TestTabani`'ndan türeyen tek sınıf, tek `[Test]` metodu
`Senaryo` (`[Category("uretilen")]`, `[Category("web")]`, `[Category("tp-case-<uuid>")]`, story,
`[Description]`) ve `await <Erişimci>.<Metot>Async(literal, …);` satırları. Gizli test verisi (013 K19)
`Gizli("TP_TESTVERI_…")` ile ortamdan okunur (tanımsızsa açık hata; değer iletiye yazılmaz).
`cs-araclar guard` denetler. JUnit kimliği `Antreklabs.Bayi.Tests.Generated.<Sınıf>.Senaryo`.

## Hata türleri (triage ve kırmızı denetimi bunlara dayanır)

Playwright .NET 1.64'te doğrulanmış davranış:

| Durum | İstisna | İleti |
|---|---|---|
| Beklenti karşılanmadı (`Expect(…).To…Async`) | Playwright `Microsoft.Playwright.PlaywrightException` atar; page object'ler (`Ekran.DogrulaAsync`) bunu **`NUnit.Framework.AssertionException`**'a çevirir, ileti aynen | `Locator expected to have text 'y'` / `But was: 'x'` / `Call log:` / `  - Expect "ToHaveTextAsync" GetByTestId("a") with timeout 5000ms` / `  - waiting for GetByTestId("a")`; URL için `Page URL expected to match regex '/sepet$'` |
| Beklentide eleman hiç yok | aynı (`AssertionException`) | `Locator expected to be visible` / `Error: element(s) not found` (kırmızı SAYILMAZ: locator kaynaklı) |
| Eylemde eleman bulunamadı / süre aşımı (`ClickAsync`, `FillAsync`) | **`System.TimeoutException`** (Playwright .NET kendi TimeoutException türünü kullanmaz) | `Timeout 5000ms exceeded.` / `Call log:` / `  - waiting for GetByTestId("x")` |
| Gezinme hatası | `Microsoft.Playwright.PlaywrightException` | `net::ERR_… at <url>` / `navigating to "<url>"` |
| Sepete ekleme yanıtı başarısız | `AssertionException` | `sepete ekleme isteği başarısız: <durum>` |
| Hazırlık (test verisi, kilit, tarayıcı) | `InvalidOperationException` / `ArgumentException` (SetUp'ta) | `/test/reset …`, `demo API'ye ulaşılamadı`, `Chromium açılamadı …` |

**JUnit XML'de tür:** JunitXml.TestLogger her hatayı `<failure type="failure" message="…">` yazar (gerçek
istisna türü `type`'ta yoktur). Tür NUnit iletisinin önekinden okunur:

- NUnit doğrulama hatası (`AssertionException`): ileti **öneksizdir** (`Locator expected to have text …`).
- Diğer istisnalar: `<Tam.Tür.Adı> : <ileti>` (ör. `System.TimeoutException : Timeout 5000ms exceeded.`,
  `Microsoft.Playwright.PlaywrightException : net::ERR_CONNECTION_REFUSED …`); iç istisnalar
  `  ----> <Tür> : …` satırlarıyla eklenir.
- Hazırlık/kapanış hatası: `SetUp : <Tür> : …` / `TearDown : <Tür> : …`.

Önerilen kalıplar: tür öneki `^(?:(?:OneTime)?(?:SetUp|TearDown) : )?([A-Za-z_][\w.`]*(?:Exception|Error)) : `;
doğrulama = önek yok; locator = `System.TimeoutException` + `waiting for GetByTestId("…")` ya da doğrulamada
`element(s) not found`; gezinme = `net::ERR_`.

## Kurulum ve koşu

.NET SDK 10. Paketler `dotnet restore --locked-mode` ile kilit dosyasından gelir.

### Tarayıcı kurulumu

Testler tarayıcıyı **indirmez** (`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`); Chromium `PLAYWRIGHT_BROWSERS_PATH`'ten
(verilmezse Playwright'ın varsayılan önbelleği) açılır. Microsoft.Playwright sürücüsü depo kökündeki
`.playwright-version` ile aynı çekirdeği paketler (derleme çıktısında `.playwright/`), bu yüzden TS
hattının indirdiği tarayıcı burada da kullanılır:

```bash
npx --yes "playwright@$(cat ../../.playwright-version)" install chromium
```

### Komutlar

```bash
dotnet build -warnaserror                                   # derleme
dotnet test --filter "Category=birim"                       # birim/sözleşme testleri (tarayıcı gerekmez)
BASE_URL=http://127.0.0.1:8081 DEMO_API_URL=http://127.0.0.1:18000 DEMOAPP_TEST_TOKEN=… \
  dotnet test --filter "Category!=birim" --logger "junit;LogFilePath=results/junit.xml"
../ci/run-csharp-checks.sh               # kilit → guard → derleme → birim → tarayıcı (CI ile aynı)
../ci/break-verify-csharp.sh             # kırarak doğrula: yeşil → kırmızı → yeşil (token gerekir)
```

Tek test dosyası: `--filter "FullyQualifiedName~.TPD1WebC2_3f9b1c2eTests."`. `break-verify-csharp.sh`
yalnız **`kampanya` kategorisini** koşar (`BREAK_VERIFY_CATEGORY` ile değişir).

Paralellik: sınıflar paralel, en çok 2 (bayi sayısı; `Altyapi/Montaj.cs`), her test kendi fikstür örneğini
alır (`FixtureLifeCycle.InstancePerTestCase`).

| Ortam | Varsayılan |
|---|---|
| `BASE_URL` | `http://127.0.0.1:8081` |
| `DEMO_API_URL`, `API_URL` | `<BASE_URL>/api` (web vekili; compose nginx `/api/test/`'i açmaz → API'yi verin) |
| `DEMOAPP_TEST_TOKEN` | — (yoksa `TP_E2E_NO_RESET=1` ile yalnız sepet yalıtımı; `sifir-veri` testleri atlanır) |
| `BREAK_CAMPAIGN` | — (`1`: bayi kapsamlı kampanya kırılması) |
| `TP_FAULT` | — (ekilmiş hata kodu `^[a-z0-9_]{1,40}$`; BREAK_CAMPAIGN ile birlikteyse bu geçerli) |
| `HEADLESS` | `true` |
| `BEKLEME_MS` / `GEZINME_MS` | 5000 / 10000 (expect/eylem ve gezinme) |
| `BAYI_KILIT_MS` | 40000 |
| `KANIT_DIZINI` | `results/kanit` (çalışma dizinine göre; betikler mutlak yol verir) |
| `ALLURE_CONFIG` | — (Allure.Net.Commons: `{"allure":{"directory":"<dizin>"}}` içeren JSON'un yolu; verilmezse `bin/<yapılandırma>/net10.0/allure-results`) |
| `TP_TESTVERI_*` | gizli test verisi (`Gizli(...)`) |

Veri yalıtımı TS fixtures ve e2e-java ile aynıdır: her test bayisini (`bayi1`/`bayi2`, işçi yuvası ya da
`[Bayi]`) süreçler arası kilitle alır ve yalnız o bayinin verisini `POST /test/reset` ile sıfırlar;
doğrulama ajanının bayisi (`bayi3`) hiçbir zaman kullanılmaz. Token yalnız `HttpClient` başlığında
taşınır (Playwright isteği olmadığı için trace'e düşmez).

## Raporlar ve kanıt (`results/`)

`junit.xml` (tarayıcı koşusu), `birim/junit.xml`, `allure-results/`, başarısız testte
`kanit/<Sınıf>.<Metot>/{ekran.png, trace.zip, sayfa.html}` (trace: `npx playwright show-trace trace.zip`),
`guard.json` (run-csharp-checks.sh). Kanıt toplanamazsa yalnız `kanit-hatasi.txt` yazılır; testin asıl
hatası gölgelenmez.
