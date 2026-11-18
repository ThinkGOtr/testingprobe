# Üretilen testler (AI Testing Probe)

Bu dizindeki `test_<story>_<platform>_c<sıra>_<uuid8>.py` dosyalarını TP üretir (şablon
`rules/templates/appium_pytest.py.j2`); elle düzenlenmez — değişiklik case'in yeniden onayı ve
yeniden üretimle yapılır. Bir case'in her platformdaki script'i ayrı dosyadır. Biçim (py-guard
izin listesi): tek test işlevi (ad = modül adı, imza `(driver) -> None`), işaretler `uretilen`,
`<platform>`, `tp_case("<uuid>")` (+ `story`, `dealer`), gövdede yalnız `ekranlar.*` ekran
nesnesi kurucuları ve metot çağrıları. `conftest.py` başka platformun testini seçmez.

`test_tpd_1_android_c3_0a1b2c3d.py` örnek referans dosyasıdır (CI bu biçimi koşar).
