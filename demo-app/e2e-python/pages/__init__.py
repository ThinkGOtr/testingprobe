"""Page object kütüphanesi (TS: demo-app/e2e/pages ile eşit; 011 §2.5 PO eşitliği).

Sözleşme: her sınıf `<Sınıf>(page: Page)` kurucusuyla kendi modülündedir
(`pages.<snake_case(Sınıf)>`); public metot adları TS metot adlarının snake_case biçimidir
(`addToCart` → `add_to_cart`), parametreler yalnız `str | int | float | bool`, dönüş `None`.
`kimlikler.py` saf veridir (onarım yalnız orayı değiştirir). Eşitlik: tests/birim/.
"""
