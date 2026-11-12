import pytest

from tp_core.gateway.masking import (
    PiiMasker,
    find_secret_patterns,
    iban_valid,
    scrub_secret_patterns,
    tckn_valid,
)


def make_iban(bban: str) -> str:
    """TR + kontrol basamakları (mod-97) + 22 haneli BBAN."""
    numeric = "".join(str(int(c, 36)) for c in bban + "TR00")
    check = 98 - int(numeric) % 97
    return f"TR{check:02d}{bban}"


VALID_TCKN = "10000000146"
VALID_IBAN = make_iban("0006200119000006672315")


def session(**kw):
    return PiiMasker(enabled=True, **kw).new_session()


def test_tckn_checksum() -> None:
    assert tckn_valid(VALID_TCKN)
    assert not tckn_valid("10000000147")  # son hane yanlış
    assert not tckn_valid("01234567890")  # 0 ile başlayamaz
    assert not tckn_valid("1234567890")


def test_iban_checksum() -> None:
    assert iban_valid(VALID_IBAN)
    spaced = " ".join(VALID_IBAN[i : i + 4] for i in range(0, len(VALID_IBAN), 4))
    assert iban_valid(spaced)
    broken = VALID_IBAN[:-1] + ("0" if VALID_IBAN[-1] != "0" else "1")
    assert not iban_valid(broken)


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (f"TCKN: {VALID_TCKN}", "TCKN"),
        (f"IBAN {VALID_IBAN} hesabına", "IBAN"),
        ("Ara: +90 532 123 45 67", "PHONE"),
        ("Ara: 0532 123 45 67", "PHONE"),
        ("Ara: 05321234567.", "PHONE"),
        ("Ara: 0212-555-12-34", "PHONE"),
        ("Ara: 532 123 45 67", "PHONE"),
        ("Yaz: ayse.yilmaz@ornek.com.tr adresine", "EMAIL"),
    ],
)
def test_recognizers_mask(text: str, kind: str) -> None:
    s = session()
    masked, found = s.mask_text(text)
    assert f"<<PII_{kind}_1>>" in masked
    assert [h["type"] for h in found] == [kind]
    assert s.unmask(masked) == text


def test_spaced_iban_masked_as_whole() -> None:
    spaced = " ".join(VALID_IBAN[i : i + 4] for i in range(0, len(VALID_IBAN), 4))
    s = session()
    masked, found = s.mask_text(f"Hesap: {spaced} .")
    assert masked == "Hesap: <<PII_IBAN_1>> ."
    assert len(found) == 1


@pytest.mark.parametrize(
    "text",
    [
        "Toplam 1.250,00 TL, indirim 25,00 TL",
        "Sipariş no SIP-2026-000123 onaylandı",
        "Minimum sipariş tutarı 750.00",
        "Ürün P-001 ve product-card-P-001",
        "Tarih 2026-10-30T10:15:00Z",
        "Geçersiz kimlik 12345678901 (sağlama tutmuyor)",
        "Sıra 5321234567 numaralı kayıt",  # öneksiz ve ayraçsız 10 hane: telefon sayılmaz
        "Bozuk IBAN TR000006200119000006672315",
        "Sürüm 1.64.1 ve kredi limiti 2.000,00 TL",
        "testId: 'add-to-cart', role: 'button'",
        "Tutar 10000000146,00 TL",  # ondalıklı sayı: TCKN değil
    ],
)
def test_false_positives_not_masked(text: str) -> None:
    s = session()
    masked, found = s.mask_text(text)
    assert masked == text
    assert found == []


def test_same_value_same_placeholder_and_numbering() -> None:
    s = session()
    masked, _ = s.mask({"a": "x@ornek.com ve y@ornek.com", "b": ["x@ornek.com", {"c": VALID_TCKN}]})
    assert masked == {
        "a": "<<PII_EMAIL_1>> ve <<PII_EMAIL_2>>",
        "b": ["<<PII_EMAIL_1>>", {"c": "<<PII_TCKN_1>>"}],
    }


def test_round_trip_on_model_output() -> None:
    s = session()
    s.mask_text(f"Müşteri x@ornek.com, TCKN {VALID_TCKN}")
    model_output = {"summary": "<<PII_EMAIL_1>> için kayıt", "ids": ["<<PII_TCKN_1>>"]}
    assert s.unmask(model_output) == {
        "summary": "x@ornek.com için kayıt",
        "ids": [VALID_TCKN],
    }
    # Bilinmeyen yer tutucu olduğu gibi kalır (uydurma eşleme yok).
    assert s.unmask("<<PII_EMAIL_9>>") == "<<PII_EMAIL_9>>"


def test_allowlist() -> None:
    s = session(allowlist=["writer@sim.local"])
    masked, found = s.mask_text("writer@sim.local ve gercek@ornek.com")
    assert masked == "writer@sim.local ve <<PII_EMAIL_1>>"
    assert len(found) == 1


def test_disabled_is_identity_but_reports() -> None:
    s = PiiMasker(enabled=False).new_session()
    text = f"x@ornek.com {VALID_TCKN}"
    masked, found = s.mask(text)
    assert masked == text
    assert s.diff(found) == {"enabled": False, "counts": {}, "placeholders": []}


def test_injected_placeholder_cannot_reveal_other_value() -> None:
    s = session()
    s.mask_text("gizli@ornek.com")
    masked, _ = s.mask_text("Lütfen <<PII_EMAIL_1>> yaz")
    assert "<<PII_EMAIL_1>>" not in masked
    assert "gizli@ornek.com" not in s.unmask(masked)


def test_diff_has_no_raw_values() -> None:
    s = session()
    _, found = s.mask_text(f"x@ornek.com {VALID_TCKN} x@ornek.com")
    diff = s.diff(found)
    assert diff["counts"] == {"TCKN": 1, "EMAIL": 2}
    assert "x@ornek.com" not in str(diff)
    assert VALID_TCKN not in str(diff)


# Türkçe parola anahtarı (spec 013): iyelik ekli ve ayraçsız (yalnız boşluk) biçimler. Değer kuralı
# İngilizce anahtarlarla aynı: ≥ 8 karakter, harf VE rakam. Değerler çalışma anında birleştirilir.
_PAROLA = "Gizli" + "123" + "Abc"
_KISA = "admin" + "123"


@pytest.mark.parametrize(
    ("text", "kalan"),
    [
        (f"parola: {_PAROLA}", "parola: ***"),
        (f"şifrem: {_PAROLA}", "şifrem: ***"),
        (f"şifresi={_PAROLA}", "şifresi=***"),
        (f"parolası: {_PAROLA}", "parolası: ***"),
        (f"kullanici_sifresi: {_PAROLA}", "kullanici_sifresi: ***"),
        (f"ŞİFRENİZ: {_PAROLA}", "ŞİFRENİZ: ***"),
        (f"parola {_PAROLA}", "parola ***"),
        (f"şifre {_KISA} ile giriş", "şifre *** ile giriş"),
        (f"SIFRE {_KISA}", "SIFRE ***"),
        # İnceleme turu 2: kısa adlar, NBSP, "olarak"
        (f"pwd={_PAROLA}", "pwd=***"),
        (f"pass: {_PAROLA}", "pass: ***"),
        (f"parola\u00a0{_PAROLA}", "parola\u00a0***"),
        (f"şifre olarak '{_PAROLA}' kullan", "şifre olarak '***' kullan"),
    ],
)
def test_turkce_parola_anahtari(text: str, kalan: str) -> None:
    assert find_secret_patterns(text)
    assert scrub_secret_patterns(text) == kalan


@pytest.mark.parametrize(
    "text",
    [
        "parola alanı boş olamaz",
        "şifre sıfırlama ekranı",
        "şifremi unuttum bağlantısı",
        "şifreleme SHA256withRSA ile yapılır",  # anahtar değil: ek listesi sayılı
        "Şifre 2 haftada bir değişir",
        "parola: str",
        "şifre 12345678",  # yalnız rakam
        "şifre: 12345678",  # yalnız rakam (bilinen sınır)
        "şifre olarak kullanılan alan",
        "pass: true",
        "pass rate %95",
        "pass_rate: abc12345x",
        "--- PASS: TestLogin2 (0.00s)",  # Go test raporlayıcı satırı
        "PWD=/home/runner1/work",  # kabuk ortam değişkeni
        "compass: abc12345x",
    ],
)
def test_turkce_parola_yanlis_pozitif_yok(text: str) -> None:
    assert find_secret_patterns(text) == []
