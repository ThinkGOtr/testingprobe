# cs-araclar — C# sembol tablosu, üretilen test koruması, kimlik yaması

014 test dilleri §3.2'nin (Ş2) deterministik uygulaması; `toolchain/java-araclar`'ın birebir karşılığı
(Roslyn `Microsoft.CodeAnalysis.CSharp` 5.12.0). Kod yalnızca **ayrıştırılır**: derlenmez, anlamsal model
kurulmaz, çalıştırılmaz. JSON sözleşmesi TS `tp-symbols` / `ast-guard` ve java-araclar ile aynıdır;
toolchain-worker `lang=csharp` (`worker/diller/csharp.py`) kullanır.

Hedef projeler: web `e2e-csharp` (Playwright .NET + NUnit; page object'ler `Pages/`) ve windows
`e2e-app-csharp` (Appium .NET + NUnit, NovaWindows; ekranlar `Ekranlar/`). Platform kökteki dizinden
algılanır (`--platform web|windows` ile zorlanır; ikisi de varsa zorunlu).

## Derleme

```bash
dotnet test CsAraclar.slnx                                   # birim testleri (örnek projeler: tests/CsAraclar.Tests/Ornekler)
dotnet publish src/CsAraclar -c Release -o <dizin>           # <dizin>/cs-araclar.dll (+ Roslyn dll'leri, ~10 MB)
dotnet run --project src/CsAraclar -c Release -- <komut> …   # demo CI betikleri
```

.NET 10 SDK. Paket sürümleri `Directory.Packages.props`'ta (merkezi), kilit `packages.lock.json`
(`dotnet restore --locked-mode` ile doğrulanır); `nuget.config` yalnız nuget.org.
Sembol golden'larını güncellemek: `CS_ARACLAR_GUNCELLE=1 dotnet test --filter SembolTests`.

## Kullanım

```bash
dotnet cs-araclar.dll symbols  --root <proje> [--platform web|windows]
dotnet cs-araclar.dll guard    --root <proje> [--platform …] [--kimlikler] [--out rapor.json] [--quiet] [--] <dosya.cs>...
dotnet cs-araclar.dll locators find  --root <proje> --test-id <id>
dotnet cs-araclar.dll locators patch --root <proje> --old <id> --new <id> [--key Grup.SABIT] [--path-prefix demo-app/e2e-csharp]
dotnet cs-araclar.dll locators diff  --base <Kimlikler.cs> --head <Kimlikler.cs> [--file <etiket>]
```

| Alt komut | Çıkış kodları | stdout |
|---|---|---|
| `symbols`, `locators find` | 0 üretildi · 2 hata | tek satır JSON; hatada `{"ok":false,"error":…}` |
| `guard`, `locators diff` | 0 geçti · 1 ihlal · 2 hata | girintili JSON rapor; özet stderr'e |
| `locators patch` | 0 yama · 1 reddedildi · 2 hata | `{"ok":true,file,key,line,before,after,diff,content}` ya da `{"ok":false,"error":…}` |

## `symbols`

```json
{"schema_version":1,"lang":"csharp","platform":"web","root":".",
 "page_objects":[{"class":"LoginPage","file":"Pages/LoginPage.cs","doc":"Bayi giriş sayfası.",
   "methods":[{"name":"LoginAsync","params":[{"name":"username","type":"string","optional":false},…],
               "returns":"void","kind":"action","async":true,"doc":"…","line":17}],
   "locators":{"Login.USERNAME":{"testId":"login-username","role":"","name":"","intent":"Kullanıcı adı alanı.",
               "prefix":false,"file":"Pages/Kimlikler.cs","line":10}}}],
 "locator_files":[{"file":"Pages/Kimlikler.cs","exports":["Nav","Login","Catalog","Cart"]}],
 "errors":[],
 "fixtures":["CartPage","CatalogPage","LoginPage"]}
```

- Page object = `Pages/` (web) / `Ekranlar/` (windows) altında `Ekran`'dan (doğrudan ya da başka bir
  page object üzerinden) türeyen, soyut olmayan üst düzey sınıf. Yalnız `public`, statik olmayan, sınıfta
  bildirilmiş metotlar; `Expect`/`Dogrula` ile başlayan → `kind:"expect"`. `async` = dönüş `Task`/`Task<T>`.
  `doc`/`intent` = `/// <summary>` ilk cümlesi.
- Tür normalleştirmesi: `string|int|long|double|boolean` (C# `bool` → `boolean`; `String`, `Int32` …
  da kabul). Dönüş `void`/`Task` → `"void"`, `T`/`Task<T>` → normal tür. Başka tür, `params`/`ref`/`out`
  parametre, genel metot ve aşırı yükleme sözleşme dışıdır (`errors`; aşırı yüklemede ilki kalır).
  İsteğe bağlı parametre (`= değer`) `optional:true`.
- `locators`: page object dosyasının başvurduğu Kimlikler sabitleri (`Kimlikler.Login.X`, `using static
  …Kimlikler;` ile `Login.X`, iç grup `Catalog.ProductCard.ADD_TO_CART`). Anahtar `Grup[.Alt].SABIT`;
  `_ONEK` → `prefix:true`. `role`/`name` yok (boş).
- `fixtures`: `Altyapi/TestTabani` sınıfının statik olmayan `public`/`protected` özellikleri, türü bir page
  object olanlar (özellik adı; şablon sınıf adını erişimci olarak kullanır: `LoginPage LoginPage`).
  Erişimcisi olmayan page object `errors`'a yazılır.

## `guard` — üretilen test izin listesi

Şablonlar: `rules/templates/playwright_nunit.cs.j2` (web), `appium_nunit.cs.j2` (windows); golden'lar
`core/tests/unit/features/codegen/golden/csharp/`. Rapor java-araclar biçimindedir (`tool:"cs-araclar"`,
`mode:"generated"`, `ok`, `noop`, `files`, `locator_files`, `violations[{code,file,line?,message}]`, `summary`).

- Yol `Tests/Generated/<Story><Platform>C<sıra>_<uuid8>Tests.cs`, sembolik bağ değil; ilk satır
  `// AI-generated — AI Testing Probe (CasesToCode).` ile başlar.
- Yalnız `//` yorumları (blok/belge yorumu → `comment_form`); önişlemci yönergesi (`#pragma`, `#if` …) yok.
  Görünmez/yön denetimi/kontrol karakteri yok (`forbidden_character`; literal içinde `\uXXXX` kaçışı
  serbest — üretici görünmez karakteri böyle basar). Kaçışlı ya da `@` önekli tanımlayıcı yok (`unicode_escape`).
- `using` kümesi tam olarak: web `System.Threading.Tasks`, `Antreklabs.Bayi.Altyapi`, `NUnit.Framework`;
  windows son ikisi. `using static`, takma ad, `global using` yok.
- Tek dosya kapsamlı `namespace Antreklabs.Bayi.Tests.Generated;`, tek `public class <DosyaAdı> : TestTabani`,
  sınıfta en çok bir `[Bayi("<bayi>")]`.
- Tek üye: `[Test]` + `[Category("…")]`* + en çok bir `[Description("…")]` taşıyan
  `public async Task Senaryo()` (web) / `public void Senaryo()` (windows).
- Gövde yalnız `await <Erişimci>.<Metot>(<arg>…);` (web) / `<Erişimci>.<Metot>(<arg>…);` (windows).
  Erişimci `fixtures`'ta, metot o page object'te olmalı; argüman sayısı (isteğe bağlılar dahil) ve literal
  türü uyumlu olmalı (string/null → string, tamsayı → int/long/double, `L` sonekli → long/double, ondalık →
  double, true/false → boolean). Argüman yalnız düz literal ya da gizli test verisi
  `Gizli("TP_TESTVERI_[A-Z0-9_]{1,64}")` (string sayılır; specs/013 K19).

İhlal kodları: `file_location`, `missing_header`, `parse_error`, `forbidden_character`, `unicode_escape`,
`comment_form`, `forbidden_import`, `missing_import`, `wrong_package`, `top_level_type`, `class_shape`,
`annotation`, `field`, `forbidden_member`, `test_method_count`, `test_method`, `test_annotation`,
`forbidden_statement`, `branch`, `loop`, `local_variable`, `lambda`, `new`, `assignment`, `call_shape`,
`thread_sleep`, `raw_driver` (`Page`, `Driver`, `Browser`, `Context`, `Playwright`, `Sayfa`, `Surucu`,
`Tarayici`, `Baglam` …), `static_call`, `field_access`, `unknown_accessor`, `unknown_method`, `arg_count`,
`arg_type`, `non_literal_argument` (+ `--kimlikler`: `forbidden_statement`, `non_literal_value`,
`invalid_testid`, `duplicate_key`, `locator_file_missing`).

### Kimlikler (`Pages/Kimlikler.cs`, `Ekranlar/Kimlikler.cs`) — saf veri

İsteğe bağlı dosya kapsamlı `namespace`, tek `public static class Kimlikler`, iç içe `public static class`
grupları ve `public const string AD = "kimlik";` sabitleri (düz literal; `+`, verbatim, ham, enterpolasyon
yok; değer `^[A-Za-z0-9][A-Za-z0-9_.:-]*$`). `using`, metot, özellik, `static readonly`, öznitelik,
önişlemci → `forbidden_statement`.

## `locators` — onarım (yalnızca kimlik değeri değişir)

- `patch`: eski değeri taşıyan TEK sabitin literal içeriğini değiştirir; dosyaya yazmaz. Önek (`_ONEK`),
  birden çok eşleşme (`--key` ile seçin), kaçışlı literal, başka kimlikle/önekle çakışma, saf olmayan
  Kimlikler → ret. Sonuç `diff` ile belirteç düzeyinde ve tek satır farkıyla yeniden doğrulanır.
- `diff`: iki sürüm arasında yalnızca kimlik literal'leri değişmiş olmalı (yorum, boşluk, ad, yapı
  değişikliği → `non_testid_change`; önek → `prefix_changed`; taban saf değil → `base_not_pure`).

## Bilinen sınırlar

- Anlamsal model yoktur: erişimci/metot denetimi sözdizimsel ad eşlemesidir (sembol tablosu üzerinden);
  derleme (`dotnet build -warnaserror`) ayrıca koşar.
- `using static …Kimlikler.Login;` ile çıplak sabit adı (`USERNAME`) `locators`'a girmez (grup adı yazılmalı).
