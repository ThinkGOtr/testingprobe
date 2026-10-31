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
