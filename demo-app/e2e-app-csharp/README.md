# demo-app/e2e-app-csharp — Windows masaüstü e2e (C# / .NET 10, Appium .NET + NUnit)

Bayi Sipariş Portalı'nın Windows sürümünün (`demo-app/desktop`, WPF) testleri: **.NET 10 + Appium .NET
istemcisi (`Appium.WebDriver`) + NUnit**, sürücü **NovaWindows** (`automationName=NovaWindows`;
WinAppDriver kullanılmaz). Yalnız **Windows** platformu. Java karşılığı `../e2e-app` (Appium + TestNG);
ekranlar, metotlar, bayi kuralları ve test verisi kancaları onunla birebir aynı anlamdadır. Tasarım:
`aip-review/test-dilleri/TASARIM.md` §3.2 (Ş2).

## Yapı

```
Antreklabs.Bayi.E2eApp.csproj, Directory.Packages.props,   KİLİTLİ: toolchain/e2e-csharp-deps/windows/
packages.lock.json, nuget.config                           altındaki güvenilir kopyalarla bayt eşit
Altyapi/   (Antreklabs.Bayi.Altyapi)  TestTabani, Ayarlar, Bayiler, BayiAttribute, OturumAcikAttribute,
           BayiKilidi, TestVerisi, Bekle, Kanit, Kimlik, SurucuFabrikasi, UygulamaOturumu
Ekranlar/  (Antreklabs.Bayi.Ekranlar) Kimlikler (saf veri), Ekran (taban), GirisEkrani, KatalogEkrani,
           SepetEkrani, OnayEkrani, SiparisEkrani
Tests/     (Antreklabs.Bayi.Tests)    elle yazılmış referans testler (*Tests.cs; Java testler/ karşılığı)
Tests/Generated/ (Antreklabs.Bayi.Tests.Generated)  şablondan üretilen testler — tek yazar AI Testing Probe
Birim/     (Antreklabs.Bayi.Birim)    cihazsız birim/sözleşme testleri ([Category("birim")])
```

Proje kuralları: `net10.0`, `Nullable` açık, `ImplicitUsings` kapalı, uyarılar hata, kilit dosyası
zorunlu, `Platform=AnyCPU` sabit (ortamdaki `PLATFORM` MSBuild özelliğine dönüşmesin).
`Directory.Build.*`, başka `.props/.targets/.rsp` YOKTUR: MSBuild bunları kendiliğinden okur ve kod
çalıştırabilir; kontrol betiği ve toolchain reddeder.

## Ekran sözleşmesi (Java e2e-app ile birebir)

- Ekran adları Java ile aynı; `public` metot adı Java adının **PascalCase** biçimi (`girisYap` →
  `GirisYap`, `dogrulaToplam` → `DogrulaToplam`), parametre adları/sırası aynı; tür eşlemesi
  `String→string`, `int→int`, `long→long`, `double→double`, `boolean→bool`; dönüş `void`.
- Appium .NET istemcisi **eşzamanlıdır**: `…Async` soneki yoktur (web C# projesinin aksine).
- `TestTabani` her ekran için **sınıf adıyla aynı adlı** `protected` özellik verir (`GirisEkrani`,
  `KatalogEkrani`, `SepetEkrani`, `OnayEkrani`, `SiparisEkrani`); üretilen testler yalnız bunları çağırır.
- `Ekranlar/Kimlikler.cs` saf veridir: `public static class Kimlikler` + iç içe `public static class
  <Grup>` + yalnız `public const string SABIT = "…";`. Adlar Java `Kimlikler.java` ile birebir
  (onarım anahtarı `Grup.SABIT`); `_ONEK` ⇔ değer `-` ile biter; değerler `../kimlikler.json`'dadır.
- Eşitlik `Birim/SozlesmeTests` ile sabitlenir (Java kaynağı ve kimlikler.json okunur).

## Üretilen test biçimi

`Tests/Generated/<Story>WindowsC<sıra>_<uuid8>Tests.cs`, şablon `rules/templates/appium_nunit.cs.j2`.
Örnek `Tests/Generated/TPD1WindowsC2_3f9b1c2eTests.cs`, core golden'ı
(`core/tests/unit/features/codegen/golden/csharp/`) ile **bayt eşittir**. İçerik: `// AI-generated`
başlık yorumları, iki `using` (`Antreklabs.Bayi.Altyapi`, `NUnit.Framework`), dosya kapsamlı ad alanı,
en çok bir `[Bayi("…")]`, `TestTabani`'ndan türeyen tek sınıf, tek `[Test]` `Senaryo()` metodu
(kategoriler `uretilen`, `windows`, `tp-case-<uuid>`, story) ve `Erişimci.Metot(literal, …);` satırları.
Gizli test verisi `Gizli("TP_TESTVERI_…")` ile ortamdan okunur (tanımsızsa açık hata). Denetim:
`toolchain/cs-araclar guard`. JUnit kimliği `Antreklabs.Bayi.Tests.Generated.<Sınıf>.Senaryo`.

## Hata türleri (triage ve kırarak doğrulama buna dayanır)

| Durum | İstisna | İleti |
|---|---|---|
| Beklenti sağlanmadı (`Dogrula…`) | `NUnit.Framework.AssertionException` | `<açıklama>: beklenen <x>, görülen <y> (N ms)` (Java `Bekle.dogrula` ile aynı) |
| Öğe yok / tıklanamadı (eylem ön koşulu) | `OpenQA.Selenium.WebDriverTimeoutException` | `Expected condition failed: öğe görünmedi: kimlik '<id>' (tried for N second(s) with 250 milliseconds interval)` (ya da `öğe tıklanabilir olmadı: kimlik …`; kapsayıcıda `'<kap>' içinde '<id>'`) — Java FluentWait iletisiyle aynı |
| Sepete ekleme reddedildi | `NUnit.Framework.AssertionException` | `sepete ekleme başarısız: <mesaj>` |
| Hazırlık (token, /test/*, giriş) | `System.InvalidOperationException` | `/test/…`, `DEMOAPP_TEST_TOKEN`, `giriş başarısız` geçer |

JUnit XML (JunitXml.TestLogger) hata türünü `type` özniteliğine yazmaz (`type="failure"`); NUnit
iletisi ayırt eder: beklenmeyen istisna `"<Tam.Tür.Adı> : <ileti>"`, `[SetUp]` (TestTabani hazırlığı)
hatası `"SetUp : <Tür> : <ileti>"` ile başlar; `AssertionException` iletisi düz metindir.

## Ayarlar (yalnız ortam; `Altyapi/Ayarlar.cs`)

| Ortam | Varsayılan | Not |
|---|---|---|
| `PLATFORM` | `windows` | başka değer açık hata |
| `APPIUM_URL` | `http://127.0.0.1:4723` | Appium 3 + NovaWindows |
| `APP_PATH` / `APP_ID` | — | exe yolu ya da AUMID (biri zorunlu) |
| `APP_ARGS`, `APP_WORKDIR` | — | NovaWindows `appArguments` / `appWorkingDir`; tek tırnak ve denetim karakteri reddedilir |
| `DEVICE_NAME` | — | bilgi |
| `DEMO_API_URL` | `http://127.0.0.1:8081/api` | `/test/*` kökü |
| `DEMOAPP_TEST_TOKEN` | — | **Sır**; yalnız `HttpClient` başlığında (`X-Demoapp-Test-Token`) |
| `BREAK_CAMPAIGN` | — | `1`: bayi kapsamlı kampanya kırılması |
| `TP_FAULT` | — | ekilmiş hata kodu (`^[a-z0-9_]{1,40}$`) |
| `TP_E2E_NO_RESET` | — | `1` + token yok: yalnız sepet yalıtımı; `sifir-veri` testleri atlanır |
| `BEKLEME_MS` / `BAYI_KILIT_MS` | 10000 / 40000 | |
| `KANIT_DIZINI` | `kanit` | başarısız testte `<dizin>/<Sınıf>.<Metot>/{ekran.png, sayfa-kaynagi.xml}` |

Bayi kilidi dizini Java uygulama e2e'siyle ortaktır (`$TMP/demoapp-e2e-app-kilit-<özet>/`).
Kategoriler: `duman`, `kampanya` (kırarak doğrulama kümesi), `uretilen`, `sifir-veri`, `birim`.

## Komutlar

```bash
dotnet restore --locked-mode
dotnet build -warnaserror
dotnet test --no-build --filter "Category=birim"                       # cihazsız
APPIUM_URL=… APP_PATH=… DEMO_API_URL=… DEMOAPP_TEST_TOKEN=… \
  dotnet test --no-build --filter "Category!=birim" --logger "junit;LogFilePath=results/junit.xml"
../ci/run-app-csharp-checks.sh windows          # kilit → guard → build → birim → cihaz (CI ile aynı)
TEST_FILTER='Category=duman' ../ci/run-app-csharp-checks.sh windows
../ci/break-verify-app-csharp.sh windows        # yeşil → kırmızı (yalnız assertion) → yeşil
```

Sonuçlar `results/`: `junit.xml`, `birim/junit.xml`, `allure-results/`, `kanit/`, `guard.json`.
CI: `.github/workflows/masaustu-windows-csharp.yml` (check `masaustu-windows-csharp`).
