# e2e-app-python — uygulama e2e, Python hattı (pytest + Appium-Python-Client)

Java `demo-app/e2e-app` projesinin Python karşılığı (TASARIM §3.1, Ş1); tek proje üç platform
(`TP_PLATFORM=android|ios|windows`; Windows `automationName=NovaWindows`). TP bu projeye
`tests/generated/test_<story>_<platform>_c<sıra>_<uuid8>.py` üretir; conftest başka platformun
işaretini taşıyan testi seçmez.

- `ekranlar/` — ekran nesnesi kütüphanesi; Java `ekranlar/` ile eşit (metot adı = snake_case,
  `girisYap` → `giris_yap`). Eşitlik: `tests/birim/test_po_esitligi.py`. `ekranlar/kimlikler.py`
  saf veridir (Java `Kimlikler.java` ile aynı kimlikler).
- `altyapi/` — ayarlar (ortam: `APPIUM_URL`, `APP_PATH`/`APP_ID`, `APP_ACTIVITY`, `APP_ARGS`,
  `APP_WORKDIR`, `DEVICE_NAME`, `DEVICE_UDID`, `PLATFORM_VERSION`, `BEKLEME_MS`, `KIMLIK_<P>`),
  sürücü, bekleme (`TimeoutException` = locator, `AssertionError` = doğrulama), bayi kilidi, veri.
- `requirements.lock` — `toolchain/e2e-python-deps/requirements.lock` ile **bayt eşit**.

Koşu: `ci/run-python-checks.sh <android|ios|windows>`.
