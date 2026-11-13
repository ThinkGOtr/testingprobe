# java-araclar — Java sembol tablosu, üretilen test koruması, kimlik yaması

009 planı §2.4, §2.5, §2.8'in deterministik uygulaması (JavaParser; kod yalnızca **ayrıştırılır**,
derlenmez ya da çalıştırılmaz). TS tarafındaki `symbols` (`tp-symbols`) ve `ast-guard` ile aynı
JSON sözleşmesi; toolchain-worker `lang=java` / `platform=android|ios|windows` ile kullanır
(`worker/java.py`).

## Derleme

```bash
./mvnw -B package          # derler + JUnit golden testleri → target/java-araclar.jar (tek jar)
```

Maven sarmalayıcısı 3.9.11 dağıtımını `distributionSha256Sum` ile doğrular. macOS'ta `/sbin/sha256sum`
stdin'den `-c` okumaz; ilk kurulumda `PATH=/usr/bin:/bin:$PATH ./mvnw …` kullanın (sonra önbellekten
gelir). Toolchain imajı sarmalayıcıyı kullanmaz: Maven'ı resmi SHA-512 ile doğrudan kurar.

## Kullanım

```bash
java -jar java-araclar.jar symbols  --root <e2e-app> [--src src/test/java]
java -jar java-araclar.jar guard    --root <e2e-app> [--kimlikler] [--out rapor.json] [--quiet] [--] <dosya.java>...
java -jar java-araclar.jar locators find  --root <e2e-app> --test-id <id>
java -jar java-araclar.jar locators patch --root <e2e-app> --old <id> --new <id> [--key Grup.SABIT] [--path-prefix demo-app/e2e-app]
java -jar java-araclar.jar locators diff  --base <Kimlikler.java> --head <Kimlikler.java> [--file <etiket>]
```

| Alt komut | Çıkış kodları | stdout |
|---|---|---|
| `symbols`, `locators find` | 0 üretildi · 2 hata | tek satır JSON; hatada `{"ok":false,"error":…}` |
| `guard`, `locators diff` | 0 geçti · 1 ihlal · 2 hata | girintili JSON rapor (TS ast-guard biçimi); özet stderr'e |
| `locators patch` | 0 yama · 1 reddedildi · 2 hata | `{"ok":true,file,key,line,before,after,diff,content}` ya da `{"ok":false,"error":…}` |

## `symbols` — TS `tp-symbols` şeması

```json
{"schema_version":1,"root":"src/test/java",
 "page_objects":[{"class":"GirisEkrani","file":"src/test/java/com/antreklabs/bayi/ekranlar/GirisEkrani.java",
   "doc":"Bayi giriş ekranı.",
   "methods":[{"name":"girisYap","params":[{"name":"kullaniciAdi","type":"String","optional":false},
               {"name":"parola","type":"String","optional":false}],
               "returns":"void","kind":"action","async":false,"doc":"…","line":14}],
   "locators":{"Giris.KULLANICI_ADI":{"testId":"login-username","role":"","name":"","intent":"Kullanıcı adı alanı.",
               "prefix":false,"file":"src/test/java/com/antreklabs/bayi/ekranlar/Kimlikler.java","line":10}}}],
 "locator_files":[{"file":"…/ekranlar/Kimlikler.java","exports":["Giris","Katalog","Sepet"]}],
 "errors":[],
 "fixtures":["girisEkrani","katalogEkrani","sepetEkrani"]}
```

- Ekran = `ekranlar/` altında `Ekran`'dan (doğrudan ya da başka bir ekran üzerinden) türeyen üst düzey
  sınıf. Yalnız `public`, statik olmayan metotlar; `dogrula` ile başlayan → `kind:"expect"`.
  `doc`/`intent` = Javadoc ilk cümlesi. `params[].type` Java türüdür.
- `locators`: ekran dosyasının başvurduğu `Kimlikler` sabitleri (`Kimlikler.Giris.X`, içe aktarılmış
  grup `Giris.X`, statik içe aktarma `X`). Anahtar `Grup.SABIT`; `_ONEK` → `prefix:true`. Java'da
  `role`/`name` yok (boş), `within` yazılmaz.
- `fixtures` (ek alan): `TestTabani`'nda bulunan ekran erişimcileri (`lowerCamel(Sınıf)()`, parametresiz,
  statik/private olmayan, dönüşü o ekran). Erişimcisi olmayan ekran `errors`'a yazılır.
- `errors` (`{file, line?, message}`): sözdizimi hataları, Kimlikler saflık ihlalleri (o öğe atlanır),
  sözleşme dışı imzalar (void olmayan dönüş, `String/int/long/double/boolean` dışı parametre, varargs,
  aşırı yükleme). Sıralama deterministiktir (dosya, sınıf; Kimlikler kaynak sırası).

## `guard` — üretilen test izin listesi (§2.8)

Rapor TS ast-guard ile aynı biçimdedir (`tool`, `schema_version`, `mode:"generated"`, `ok`, `noop`,
`changed_files`, `testid_changes`, `violations[{code,file,line?,message}]`, `summary`; ek: `files`,
`locator_files`). `--kimlikler` ayrıca `ekranlar/Kimlikler.java` saflığını denetler (TS `pr` modunun
`locators.ts` saf veri denetimi karşılığı). `uretilen/package-info.java` yalnız belge yorumu + `package`
taşıyabilir.

İhlal kodları: `file_location`, `missing_header`, `parse_error`, `unicode_escape`, `forbidden_character`,
`comment_form`, `wrong_package`, `forbidden_import`, `missing_import`, `top_level_type`, `class_shape`,
`annotation`, `test_annotation`, `field`, `forbidden_member`, `test_method_count`, `test_method`,
`forbidden_statement`, `call_shape`, `branch`, `loop`, `lambda`, `new`, `array`, `text_block`,
`this_super`, `local_variable`, `assignment`, `thread_sleep`, `raw_driver`, `static_call`,
`field_access`, `non_literal_argument`, `unknown_accessor`, `unknown_method`, `arg_count`, `arg_type`
(+ `--kimlikler`: `forbidden_statement`, `non_literal_value`, `invalid_testid`, `duplicate_key`,
`locator_file_missing`).

Ekran çağrısı argümanları literal olmalıdır; tek istisna gizli test verisidir (specs/013 K19):
doğrudan argüman olarak `System.getenv("TP_TESTVERI_…")` (niteliksiz `System`, tek string literal, ad
`^TP_TESTVERI_[A-Z0-9_]{1,64}$`) kabul edilir ve `String` sayılır. Başka ad/kapsam/biçim, zincir ya da
bağımsız deyim olarak kullanımı `non_literal_argument` / `static_call` / `field_access` ile reddedilir.

`raw_driver` hem Appium/Selenium sürücüsünü (`driver`, `driver()`, …) hem Playwright for Java
tutamaçlarını (web projesi `e2e-java`, 011 §2.6: `page`, `page()`, `browser()`, `context()`,
`playwright` ve Türkçe karşılıkları `sayfa`, `tarayici`, `baglam`) kapsar: üretilen test yalnızca ekran
erişimcilerini çağırır.

Unicode kaçışları (`\uXXXX`) her yerde yasaktır: javac onları yorum ve literal içinde bile ayrıştırmadan
önce işler (`// … \u000a kod`). Görünmez/yön denetimi karakterleri de reddedilir.

## `locators` — onarım (yalnızca kimlik değeri değişir)

- `patch`: eski değeri taşıyan TEK sabitin literal içeriğini değiştirir; dosyaya yazmaz. Önek (`_ONEK`),
  birden çok eşleşme (`--key` ile seçin), kaçışlı literal, başka kimlikle/önekle çakışma, saf olmayan
  Kimlikler → ret. Sonuç belirteç düzeyinde (`diff` ile) ve satır farkıyla yeniden doğrulanır.
- `diff`: iki sürüm arasında yalnızca kimlik literal'leri değişmiş olmalı (yorum, boşluk, ad, yapı
  değişikliği → `non_testid_change`; önek → `prefix_changed`). TS ast-guard `repair` raporu biçimi.
