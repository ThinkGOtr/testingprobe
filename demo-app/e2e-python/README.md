# e2e-python — web e2e, Python hattı (pytest + pytest-playwright)

TS `demo-app/e2e` projesinin Python karşılığı (test dilleri TASARIM §3.1, Ş1). TP bu projeye
`tests/generated/test_<story>_c<sıra>_<uuid8>.py` üretir, derler (compile + py-guard) ve koşar.

- `pages/` — page object kütüphanesi; TS `pages/` ile eşit (metot adı = snake_case). Eşitlik:
  `tests/birim/test_po_esitligi.py`. `pages/kimlikler.py` saf veridir (onarım yalnız onu değiştirir).
- `conftest.py` — bayi seçimi/kilidi, `/test/reset`, `BREAK_CAMPAIGN` / `TP_FAULT`, kanıt.
- `requirements.lock` — `toolchain/e2e-python-deps/requirements.lock` ile **bayt eşit** olmalı
  (TP `deps` adımı ve `ci/run-python-checks.sh` denetler). Bağımlılık değişikliği önce oraya girer.

Koşu: `ci/run-python-checks.sh web` (kırarak doğrulama: `ci/break-verify-python-checks.sh web`).
