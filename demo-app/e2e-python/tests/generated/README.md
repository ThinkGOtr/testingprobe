# Üretilen testler (AI Testing Probe)

Bu dizindeki `test_<story>_c<sıra>_<uuid8>.py` dosyalarını TP üretir (şablon
`rules/templates/playwright_pytest.py.j2`); elle düzenlenmez — değişiklik case'in yeniden onayı ve
yeniden üretimle yapılır. Biçim (py-guard izin listesi): tek test işlevi (ad = modül adı,
imza `(page: Page) -> None`), işaretler `uretilen`, `web`, `tp_case("<uuid>")` (+ `story`,
`dealer`), gövdede yalnız `pages.*` page object kurucuları ve metot çağrıları.

`test_tpd_1_c3_0a1b2c3d.py` örnek referans dosyasıdır (CI bu biçimi koşar).
