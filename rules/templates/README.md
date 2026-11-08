# rules/templates — kod üretimi şablonları

`playwright_test.ts.j2`: CasesToCode'un (TEKNIK-TASARIM §8.4 adım 4) Playwright test şablonu.
`tp_core.features.codegen.render` bunu yalnızca **uygulamada doğrulanmış ve deterministik
kontrollerden geçmiş** adım → page object eşlemesiyle render eder; model TypeScript yazmaz
(Constitution IV).

- Değerler `ts` süzgecinden geçer: `JSON.stringify` eşdeğeri literal (str / sayı / bool;
  NaN/∞ reddedilir; U+2028/2029 kaçışlanır). Fikstür ve metot adları `ident` süzgecinden
  (tanımlayıcı dilbilgisi), yorumlar `comment` süzgecinden (tek satır) geçer.
- Çıktı `demo-app/e2e/eslint.config.js` `tests/generated/**` sözleşmesine uyar: yalnızca
  `../fixtures`'tan `test`, page object fikstürleri, doğrusal akış, `test.use` yalnızca
  `dealerUsername` (case bir e2e bayisiyle giriş yapıyorsa o bayiye sabitlenir).
- Başlık yorumu: case kimliği, story ve Jira Test anahtarı, onaylı case hash'i, üretim modu,
  bundle hash'i, eşleme hash'i ve şablon hash'i. Zaman damgası yoktur: aynı girdi aynı dosyayı
  verir.
- Golden çıktılar: `core/tests/unit/features/codegen/golden/` (`test_render.py`). Şablonu
  bilinçli değiştirdiğinizde `TP_UPDATE_GOLDEN=1 uv run pytest
  tests/unit/features/codegen/test_render.py` ile yenileyin ve farkı inceleyin; şablon hash'i
  her üretilen dosyanın başlığına yazıldığı için değişiklik PR'larda görünür.

`appium_testng.java.j2` (009 mobil-masaüstü §2.4, §2.8): aynı eşlemenin Android / iOS / Windows
için Java 17 + Appium + TestNG karşılığı (`render.render_java_test`; model Java yazmaz).

- Değerler `java` süzgecinden geçer: String / int / long (`L`) / double / boolean literali.
  Unicode kaçışı üretilmez (`java-araclar guard` her yerde reddeder; javac onu yorum ve literal
  içinde bile işler): ASCII dışı karakter ham UTF-8 basılır; ters bölü, tırnak, satır sonu ve
  sekme kaçışlanır; diğer kontrol/biçim/görünmez karakterler (Cc, Cf, Zl, Zp, Co, Cs, Cn)
  şablonu reddettirir.
- Sınıf `<Story><Platform>C<sıra>_<uuid8>Test` (ör. `TPD1AndroidC3_0a1b2c3dTest`): bir case'in
  her platformu ayrı dosya/dal/PR; ad guard'ın dosya adı kuralına uyar. Dosya
  `<e2e-app kökü>/src/test/java/com/antreklabs/bayi/uretilen/`. TestNG grupları: `uretilen`,
  `<platform>`, `tp-case-<uuid>`, story. `@Bayi("bayiN")` web `test.use` karşılığıdır.
- Golden: `core/tests/unit/features/codegen/golden/*.java` (`test_platform.py`); aynı test
  üretilen dosyayı gerçek `java-araclar.jar guard` ile denetler (jar yoksa atlanır).
