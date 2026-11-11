"""Sınırlı ifade dili (012 ANALIZ §4.2): ayrıştırma, öncelik, türler, Decimal kesinliği, sınırlar,
düşmanca girdiler, Türkçe sayı metni, karar tablosu ve ilişki değerlendirmesi. DB gerektirmez."""

from __future__ import annotations

import copy
import inspect
import json
import random
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tp_core.features.karar_tablosu import ifade
from tp_core.features.karar_tablosu.ifade import (
    Degerlendirme,
    IfadeHatasi,
    adlar,
    ayristir,
    degerlendir,
    dogrula,
    esit_mi,
    girdi_donustur,
    gonderim_hatalari,
    hesapla,
    ifade_turu,
    iliski_dogrula,
    iliski_uygula,
    sayi_ayristir,
    sayi_bicimle,
    toleranslar,
)
from tp_core.gateway.config import find_rules_dir

D = Decimal

# ANALIZ §4.1 örneği (kampanya: 7 adette 1 bedava biçiminde yazılmış tablo).
TABLO: dict[str, Any] = {
    "ad": "Kampanya: 6 al 1 bedava",
    "ac_refs": ["AC2"],
    "aciklama": "Kampanyalı üründe her 7 adedin biri bedavadır",
    "girdiler": [
        {"ad": "adet", "tur": "sayi", "aciklama": "Kampanyalı üründen sepetteki adet"},
        {"ad": "birim_fiyat", "tur": "sayi", "birim": "TL"},
    ],
    "ciktilar": [
        {"ad": "bedava_adet", "tur": "sayi"},
        {"ad": "indirim", "tur": "sayi", "birim": "TL", "tolerans": "0.01"},
    ],
    "satirlar": [
        {
            "id": "R1",
            "kosul": "adet >= 7",
            "cikti": {"bedava_adet": "adet // 7", "indirim": "(adet // 7) * birim_fiyat"},
        },
        {"id": "R2", "kosul": "adet < 7", "cikti": {"bedava_adet": "0", "indirim": "0"}},
    ],
}

# ANALIZ §4.5 örneği.
ILISKI: dict[str, Any] = {
    "ad": "Adet iki katına çıkınca ara toplam iki katına çıkar",
    "ac_refs": ["AC1"],
    "tablo_ref": "T1",
    "on_kosul": "adet >= 1 ve adet * 2 <= 999",
    "donusum": {"adet": "adet * 2"},
    "iliski": {"ara_tutar": "ara_tutar * 2"},
    "aciklama": "Kampanyasız üründe geçerlidir",
}
ARA_TUTAR_TABLOSU: dict[str, Any] = {
    "ad": "Ara tutar",
    "ac_refs": ["AC1"],
    "girdiler": [{"ad": "adet", "tur": "sayi"}, {"ad": "birim_fiyat", "tur": "sayi"}],
    "ciktilar": [{"ad": "ara_tutar", "tur": "sayi"}],
    "satirlar": [{"id": "R1", "kosul": "dogru", "cikti": {"ara_tutar": "adet * birim_fiyat"}}],
}


def tablo(**degisen: Any) -> dict[str, Any]:
    t = copy.deepcopy(TABLO)
    t.update(degisen)
    return t


def hata(metin: str, degerler: dict[str, Any] | None = None) -> IfadeHatasi:
    with pytest.raises(IfadeHatasi) as bilgi:
        hesapla(metin, degerler or {})
    return bilgi.value


# ---------------------------------------------------------------------- güvenlik


def test_modul_eval_exec_kullanmaz() -> None:
    kaynak = inspect.getsource(ifade)
    for yasak in ("eval(", "exec(", "literal_eval", "compile(", "__import__", "import ast"):
        assert yasak not in kaynak.replace("re.compile(", ""), yasak


@pytest.mark.parametrize(
    "metin",
    [
        "__import__('os').system('id')",
        "__class__",
        "adet.__class__",
        "().__class__.__bases__[0]",
        "a.b",
        "a[0]",
        "lambda: 1",
        "[1, 2]",
        "{1: 2}",
        "open('/etc/passwd')",
        "exec('x')",
        "eval('1')",
        "1; 2",
        "1 if 2 else 3",
        "x := 1",
        "f'{adet}'",
        "adet\x00",
        "adet # yorum",
        "2 ** 3",
        "1 = 1",
        "a && b",
        "a || b",
        "!dogru",
        "değil dogru",
        "9" * 40,
        "1e400",
        "0x10",
        "1_000",
        "１２",
    ],
)
def test_dusmanca_girdi_yalniz_ifade_hatasi_verir(metin: str) -> None:
    """Dilin dışındaki her şey `IfadeHatasi`'dır; hiçbiri çalıştırılmaz, başka istisna sızmaz."""
    with pytest.raises(IfadeHatasi):
        hesapla(metin, {"adet": 1, "a": True, "b": False})


def test_dunder_gorunumlu_ad_yalniz_sozlukte_aranir() -> None:
    assert "bilinmeyen ad: __class__" in str(hata("__class__"))
    # Sözlükte varsa sıradan bir addır: nitelik erişimi yapılmaz.
    assert hesapla("__class__ + 1", {"__class__": 1}) == D(2)
    with pytest.raises(IfadeHatasi, match="geçersiz değer"):
        hesapla("x", {"x": object()})
    with pytest.raises(IfadeHatasi, match="geçersiz değer"):
        hesapla("x", {"x": [1]})


def test_uzunluk_siniri() -> None:
    tam = "1" + " + 1" * 74 + "   "  # 300 karakter
    assert len(tam) == ifade.AZAMI_IFADE_UZUNLUGU
    assert hesapla(tam, {}) == D(75)
    with pytest.raises(IfadeHatasi, match="en çok 300 karakter"):
        hesapla(tam + " ", {})
    with pytest.raises(IfadeHatasi, match="en çok 300 karakter"):
        ayristir("1" * 100_000)


@pytest.mark.parametrize("metin", ["", "   ", "\n\t"])
def test_bos_ifade(metin: str) -> None:
    with pytest.raises(IfadeHatasi, match="ifade boş"):
        ayristir(metin)


@pytest.mark.parametrize("deger", [None, 7, 1.5, ["1"], {"a": 1}, b"1"])
def test_metin_olmayan_ifade(deger: Any) -> None:
    with pytest.raises(IfadeHatasi, match="ifade metin olmalı"):
        ayristir(deger)


def test_derinlik_siniri_parantez() -> None:
    def ic_ice(n: int) -> str:
        return "(" * n + "1" + ")" * n

    assert hesapla(ic_ice(ifade.AZAMI_DERINLIK), {}) == D(1)
    h = hata(ic_ice(ifade.AZAMI_DERINLIK + 1))
    assert "çok derin" in h.mesaj and h.konum == ifade.AZAMI_DERINLIK
    with pytest.raises(IfadeHatasi, match="çok derin"):
        hesapla("(" * 140 + "1" + ")" * 140, {})


def test_derinlik_siniri_tekli_ve_islev() -> None:
    assert hesapla("-" * 32 + "1", {}) == D(1)
    assert hesapla("-" * 31 + "1", {}) == D(-1)
    with pytest.raises(IfadeHatasi, match="çok derin"):
        hesapla("-" * 33 + "1", {})
    with pytest.raises(IfadeHatasi, match="çok derin"):
        hesapla("degil " * 33 + "dogru", {})
    assert hesapla("degil " * 32 + "dogru", {}) is True
    with pytest.raises(IfadeHatasi, match="çok derin"):
        hesapla("taban(" * 33 + "1" + ")" * 33, {})
    assert hesapla("taban(" * 32 + "1.5" + ")" * 32, {}) == D(1)


def test_uzun_zincir_derinlik_sayilmaz() -> None:
    """Sola bağlı zincir iç içelik değildir: 300 karakterlik toplam sınırı aşmadan hesaplanır."""
    assert hesapla("+".join(["1"] * 150), {}) == D(150)
    assert hesapla(" ve ".join(["dogru"] * 30), {}) is True


def test_buyukluk_siniri() -> None:
    assert hesapla("9" * 30, {}) == D("9" * 30)
    with pytest.raises(IfadeHatasi, match="sayı çok büyük"):
        hesapla("9" * 31, {})
    h = hata("9" * 20 + " * " + "9" * 20)
    assert h.mesaj == "sayı çok büyük" and h.konum == 21
    with pytest.raises(IfadeHatasi, match="sayı çok büyük"):
        hesapla("x * x", {"x": D(10) ** 20})


# ---------------------------------------------------------------------- değerler ve öncelik


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        ("7", D(7)),
        ("25.00", D("25.00")),
        ("007", D(7)),
        ("0.5", D("0.5")),
        ('"min_siparis"', "min_siparis"),
        ("'min_siparis'", "min_siparis"),
        ('""', ""),
        ('"ali\'nin"', "ali'nin"),
        ("dogru", True),
        ("yanlis", False),
        ("  7  ", D(7)),
        ("(7)", D(7)),
        ("\t1 +\n 2", D(3)),
    ],
)
def test_degerler(metin: str, beklenen: Any) -> None:
    sonuc = hesapla(metin, {})
    assert sonuc == beklenen and type(sonuc) is type(beklenen)


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        # çarpma/bölme toplamadan önce; soldan sağa
        ("1 + 2 * 3", D(7)),
        ("(1 + 2) * 3", D(9)),
        ("10 - 4 - 3", D(3)),
        ("10 - (4 - 3)", D(9)),
        ("2 * 3 + 4 * 5", D(26)),
        ("100 / 10 / 2", D(5)),
        ("100 / (10 / 2)", D(20)),
        ("7 // 2 * 2", D(6)),
        ("7 % 4 * 2", D(6)),
        ("2 * 7 % 4", D(2)),
        ("1 + 7 // 2", D(4)),
        # tekli eksi çarpmadan sıkı bağlanır
        ("-2 * 3", D(-6)),
        ("2 * -3", D(-6)),
        ("-7 // 2", D(-4)),
        ("- -7", D(7)),
        ("+7", D(7)),
        ("-(1 + 2)", D(-3)),
        ("1 - -1", D(2)),
        ("5 - +2", D(3)),
        # karşılaştırma aritmetikten sonra
        ("1 + 2 == 3", True),
        ("1 + 2 > 2 * 2", False),
        ("2 * 3 >= 6", True),
        # degil karşılaştırmadan gevşek, ve'den sıkı; ve veya'dan sıkı
        ("degil 1 == 2", True),
        ("degil dogru ve yanlis", False),
        ("degil (dogru ve yanlis)", True),
        ("dogru veya yanlis ve yanlis", True),
        ("(dogru veya yanlis) ve yanlis", False),
        ("yanlis ve yanlis veya dogru", True),
        ("degil yanlis veya yanlis", True),
        ("degil degil dogru", True),
        ("1 < 2 ve 2 < 3 veya 1 > 2", True),
        ("1 < 2 ve (2 > 3 veya 1 < 2)", True),
    ],
)
def test_oncelik_ve_birlesme(metin: str, beklenen: Any) -> None:
    sonuc = hesapla(metin, {})
    assert sonuc == beklenen and type(sonuc) is type(beklenen)


@pytest.mark.parametrize(
    ("op", "a", "b", "beklenen"),
    [
        ("+", "0.1", "0.2", D("0.3")),
        ("-", "0.3", "0.1", D("0.2")),
        ("*", "1.10", "3", D("3.30")),
        ("/", "10", "4", D("2.5")),
        ("/", "1", "8", D("0.125")),
        ("//", "7", "2", D(3)),
        ("//", "-7", "2", D(-4)),
        ("//", "7", "-2", D(-4)),
        ("//", "-7", "-2", D(3)),
        ("//", "7.5", "2", D(3)),
        ("//", "6", "6", D(1)),
        ("//", "5", "6", D(0)),
        ("%", "7", "2", D(1)),
        ("%", "-7", "2", D(1)),
        ("%", "7", "-2", D(-1)),
        ("%", "-7", "-2", D(-1)),
        ("%", "7.5", "2", D("1.5")),
        ("%", "6", "6", D(0)),
    ],
)
def test_aritmetik_islecler(op: str, a: str, b: str, beklenen: Decimal) -> None:
    assert hesapla(f"a {op} b", {"a": D(a), "b": D(b)}) == beklenen


def test_tam_bolme_ve_kalan_python_tam_sayilariyla_ayni() -> None:
    """Özellik: tam sayılarda `//` ve `%` Python'ınkiyle aynı; a == b * (a // b) + a % b."""
    rnd = random.Random(12)
    for _ in range(500):
        a, b = rnd.randint(-500, 500), rnd.choice([n for n in range(-25, 26) if n])
        degerler = {"a": a, "b": b}
        assert hesapla("a // b", degerler) == a // b, (a, b)
        assert hesapla("a % b", degerler) == a % b, (a, b)
        assert hesapla("b * (a // b) + a % b == a", degerler) is True


def test_ondalik_tam_bolme_ozelligi() -> None:
    rnd = random.Random(7)
    for _ in range(300):
        a = D(rnd.randint(-99999, 99999)) / D(100)
        b = D(rnd.choice([n for n in range(-999, 1000) if n])) / D(100)
        q = hesapla("a // b", {"a": a, "b": b})
        r = hesapla("a % b", {"a": a, "b": b})
        assert q == q.to_integral_value() and a == b * q + r
        assert (D(0) <= r < b) if b > 0 else (b < r <= D(0)), (a, b, q, r)


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        ("1 == 1", True),
        ("1 == 1.00", True),
        ("1 != 1.00", False),
        ("1 != 2", True),
        ("1 < 2", True),
        ("2 < 2", False),
        ("2 <= 2", True),
        ("3 > 2", True),
        ("2 > 2", False),
        ("2 >= 2", True),
        ("1.999 >= 2", False),
        ('"a" == "a"', True),
        ('"a" == "A"', False),
        ('"a" != "b"', True),
        ("dogru == dogru", True),
        ("dogru != yanlis", True),
        ("(1 < 2) == dogru", True),
    ],
)
def test_karsilastirma(metin: str, beklenen: bool) -> None:
    assert hesapla(metin, {}) is beklenen


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        ("min(3, 5)", D(3)),
        ("min(5, 3)", D(3)),
        ("min(-1, 1)", D(-1)),
        ("max(3, 5)", D(5)),
        ("max(-1, -2)", D(-1)),
        ("min(1, 2) + max(3, 4)", D(5)),
        ("max(min(10, 20), 15)", D(15)),
        ("taban(2.9)", D(2)),
        ("taban(-2.1)", D(-3)),
        ("taban(3)", D(3)),
        ("tavan(2.1)", D(3)),
        ("tavan(-2.9)", D(-2)),
        ("tavan(3)", D(3)),
        ("yuvarla(2.5, 0)", D(3)),
        ("yuvarla(3.5, 0)", D(4)),
        ("yuvarla(-2.5, 0)", D(-3)),
        ("yuvarla(2.4999, 0)", D(2)),
        ("yuvarla(1.005, 2)", D("1.01")),
        ("yuvarla(1.004, 2)", D("1.00")),
        ("yuvarla(0.125, 2)", D("0.13")),
        ("yuvarla(0.135, 2)", D("0.14")),
        ("yuvarla(2.675, 2)", D("2.68")),
        ("yuvarla(10 / 3, 2)", D("3.33")),
        ("yuvarla(20 / 3, 2)", D("6.67")),
        ("yuvarla(7, 2)", D("7.00")),
        ("yuvarla(1.23456789, 2 + 2)", D("1.2346")),
        ("eger(1 < 2, 10, 20)", D(10)),
        ("eger(1 > 2, 10, 20)", D(20)),
        ('eger(dogru, "a", "b")', "a"),
        ("eger(yanlis, dogru, yanlis)", False),
        ("eger(1 < 2, eger(2 < 1, 1, 2), 3)", D(2)),
    ],
)
def test_islevler(metin: str, beklenen: Any) -> None:
    sonuc = hesapla(metin, {})
    assert sonuc == beklenen and type(sonuc) is type(beklenen)


def test_yuvarla_half_up_ozelligi() -> None:
    """Özellik: `yuvarla` Decimal ROUND_HALF_UP ile aynıdır (banker yuvarlaması değil)."""
    rnd = random.Random(2026)
    for _ in range(400):
        x = D(rnd.randint(-(10**7), 10**7)) / D(10**4)
        hane = rnd.randint(0, 4)
        beklenen = x.quantize(D(1).scaleb(-hane), rounding=ROUND_HALF_UP)
        assert hesapla("yuvarla(x, h)", {"x": x, "h": hane}) == beklenen, (x, hane)
    # float ile yanlış çıkan klasik örnekler
    assert hesapla("yuvarla(0.5, 0)", {}) == D(1)
    assert hesapla("yuvarla(1.5, 0)", {}) == D(2)
    assert str(hesapla("yuvarla(2.675, 2)", {})) == "2.68"


@pytest.mark.parametrize("hane", ["-1", "13", "1.5", "0.5"])
def test_yuvarla_hane_siniri(hane: str) -> None:
    h = hata(f"yuvarla(1.234, {hane})")
    assert "hane 0 ile 12 arasında tam sayı" in h.mesaj
    assert h.konum == len("yuvarla(1.234, ")
    assert hesapla("yuvarla(1.5, 12)", {}) == D("1.500000000000")


def test_decimal_kesinligi() -> None:
    assert hesapla("0.1 + 0.2 == 0.3", {}) is True
    assert str(hesapla("0.1 + 0.2", {})) == "0.3"
    assert str(hesapla("1.10 * 3", {})) == "3.30"
    assert str(hesapla("25.00 * 6", {})) == "150.00"
    assert str(hesapla("150.00 - 25.00", {})) == "125.00"
    assert hesapla("1 / 3 * 3 == 1", {}) is False  # bölme 60 basamakta kesilir; yuvarla gerekir
    assert hesapla("yuvarla(1 / 3 * 3, 10) == 1", {}) is True
    assert len(str(hesapla("1 / 3", {}))) == ifade.HASSASIYET + 2
    assert hesapla("0 * -1", {}).is_signed() is False  # eksi sıfır üretilmez
    assert str(hesapla("-0", {})) == "0"


def test_tembel_degerlendirme() -> None:
    assert hesapla("b != 0 ve a / b > 2", {"a": 1, "b": 0}) is False
    assert hesapla("b == 0 veya a / b > 2", {"a": 1, "b": 0}) is True
    assert hesapla("eger(b == 0, 0, a / b)", {"a": 1, "b": 0}) == D(0)
    assert hesapla("eger(b != 0, a / b, -1)", {"a": 1, "b": 0}) == D(-1)
    with pytest.raises(IfadeHatasi, match="sıfıra bölme"):
        hesapla("a / b > 2 ve b != 0", {"a": 1, "b": 0})


# ---------------------------------------------------------------------- hatalar ve konum


@pytest.mark.parametrize(
    ("metin", "mesaj", "konum"),
    [
        ("1 / 0", "sıfıra bölme", 2),
        ("1 // 0", "sıfıra bölme", 2),
        ("1 % 0", "sıfıra bölme", 2),
        ("1 / (2 - 2)", "sıfıra bölme", 2),
        ("x + 1", "bilinmeyen ad: x", 0),
        ("1 + yok", "bilinmeyen ad: yok", 4),
        ("VE", "bilinmeyen ad: VE", 0),
        ("foo(1)", "bilinmeyen işlev: foo", 0),
        ("min", "'min' bir işlevdir; 'min(…)' biçiminde çağrılır", 0),
        ("min(1)", "min işlevi 2 değer alır (1 verildi)", 0),
        ("min(1, 2, 3)", "min işlevi 2 değer alır (3 verildi)", 0),
        ("taban()", "taban işlevi 1 değer alır (0 verildi)", 0),
        ("eger(dogru, 1)", "eger işlevi 3 değer alır (2 verildi)", 0),
        ("1 +", "ifade eksik (değer bekleniyor)", 3),
        ("* 2", "beklenmeyen simge: '*'", 0),
        ("(1 + 2", "')' bekleniyor", 6),
        ("1 + 2)", "beklenmeyen simge: ')'", 5),
        ("1 2", "beklenmeyen simge: '2'", 2),
        ('1 "a"', 'beklenmeyen simge: "a"', 2),
        ("min(1 2)", "')' bekleniyor", 6),
        ("min(1,)", "beklenmeyen simge: ')'", 6),
        ("1 < 2 < 3", "karşılaştırmalar zincirlenemez; 've' ile bağlayın", 6),
        ("1 == 1 == dogru", "karşılaştırmalar zincirlenemez; 've' ile bağlayın", 7),
        ("1 = 1", "eşitlik için '==' kullanın", 2),
        ("1 & 2", "'&' yerine 've' / 'veya' kullanın", 2),
        ("!dogru", "'!' tek başına kullanılamaz; 'degil' ya da '!=' kullanın", 0),
        ("1 $ 2", "beklenmeyen karakter: '$'", 2),
        ("a.b", "beklenmeyen karakter: '.'", 1),
        ("1.", "ondalık noktadan sonra rakam bekleniyor", 1),
        ("1.2.3", "sayı biçimi geçersiz", 0),
        ("7abc", "sayı biçimi geçersiz", 0),
        (".5", "beklenmeyen karakter: '.'", 0),
        ('"açık', "metin kapatılmamış (tırnak eksik)", 0),
        ("1 + 'x", "metin kapatılmamış (tırnak eksik)", 4),
        ("ve", "beklenmeyen simge: 've'", 0),
        ("1 ve", "ifade eksik (değer bekleniyor)", 4),
        ("degil", "ifade eksik (değer bekleniyor)", 5),
    ],
)
def test_hata_mesaji_ve_konumu(metin: str, mesaj: str, konum: int) -> None:
    h = hata(metin, {})
    assert (h.mesaj, h.konum) == (mesaj, konum)
    assert str(h) == f"{mesaj} (konum {konum + 1})"  # metinde 1 tabanlı


@pytest.mark.parametrize(
    ("metin", "parca"),
    [
        ('"a" + 1', "'+' işlecinin sol tarafı sayı olmalı (metin verildi)"),
        ('1 + "a"', "'+' işlecinin sağ tarafı sayı olmalı (metin verildi)"),
        ("dogru * 2", "'*' işlecinin sol tarafı sayı olmalı (mantıksal verildi)"),
        ('"a" < "b"', "'<' işlecinin sol tarafı sayı olmalı (metin verildi)"),
        ('1 == "1"', "'==' farklı türleri karşılaştıramaz (sayı ile metin)"),
        ("dogru != 1", "'!=' farklı türleri karşılaştıramaz (mantıksal ile sayı)"),
        ("1 ve dogru", "'ve' işlecinin sol tarafı mantıksal olmalı (sayı verildi)"),
        ('yanlis veya "x"', "'veya' işlecinin sağ tarafı mantıksal olmalı (metin verildi)"),
        ("degil 1", "'degil' işlecinin değeri mantıksal olmalı (sayı verildi)"),
        ('-"a"', "'-' işlecinin değeri sayı olmalı (metin verildi)"),
        ("-dogru", "'-' işlecinin değeri sayı olmalı (mantıksal verildi)"),
        ('min(1, "a")', "min işlevinin 2. değeri sayı olmalı (metin verildi)"),
        ("taban(dogru)", "taban işlevinin 1. değeri sayı olmalı (mantıksal verildi)"),
        ("yuvarla(1, dogru)", "yuvarla işlevinin 2. değeri sayı olmalı (mantıksal verildi)"),
        ("eger(1, 2, 3)", "eger işlevinin koşulu mantıksal olmalı (sayı verildi)"),
    ],
)
def test_tur_uyusmazligi_hem_statik_hem_calisma_aninda(metin: str, parca: str) -> None:
    assert parca in str(hata(metin, {}))
    with pytest.raises(IfadeHatasi) as bilgi:
        ifade_turu(metin, {})
    assert parca in str(bilgi.value)


def test_statik_tur() -> None:
    turler = {"adet": "sayi", "kod": "metin", "kampanyali": "mantiksal"}
    assert ifade_turu("adet // 7", turler) == "sayi"
    assert ifade_turu("adet >= 7 ve kampanyali", turler) == "mantiksal"
    assert ifade_turu('eger(kampanyali, kod, "yok")', turler) == "metin"
    assert ifade_turu('kod == "P-001"', turler) == "mantiksal"
    with pytest.raises(IfadeHatasi, match="bilinmeyen ad: fiyat"):
        ifade_turu("adet * fiyat", turler)
    with pytest.raises(IfadeHatasi, match="eger işlevinin iki sonucu aynı türde olmalı"):
        ifade_turu('eger(kampanyali, 1, "bir")', turler)
    with pytest.raises(IfadeHatasi, match="geçersiz tür"):
        ifade_turu("x", {"x": "tarih"})
    # Statik denetim kısa devreden bağımsızdır: çalışmayan dal da denetlenir.
    with pytest.raises(IfadeHatasi, match="sağ tarafı mantıksal olmalı"):
        ifade_turu("yanlis ve 1", {})
    assert hesapla("yanlis ve 1", {}) is False


def test_adlar_sirali_ve_tekil() -> None:
    assert adlar("(adet // 7) * birim_fiyat + adet") == ["adet", "birim_fiyat"]
    assert adlar("min(b, a) + eger(c, a, 2)") == ["b", "a", "c"]
    assert adlar("1 + 2") == []
    assert adlar('"adet" == "x"') == []  # metin içindeki sözcük ad değildir


def test_girdi_degerleri_donusur() -> None:
    assert hesapla("a + b", {"a": 1, "b": D("0.5")}) == D("1.5")
    assert hesapla("a + 0.1", {"a": 0.2}) == D("0.3")  # float metinsel değeriyle
    assert hesapla("a", {"a": True}) is True  # bool sayı değildir
    assert "sayı olmalı (mantıksal verildi)" in str(hata("a + 1", {"a": True}))
    for kotu in (float("nan"), float("inf"), D("NaN"), D("Infinity"), None, (1,)):
        with pytest.raises(IfadeHatasi, match="geçersiz değer"):
            hesapla("a", {"a": kotu})


def test_belirleyicilik_ve_onbellek() -> None:
    metin = "yuvarla((adet // 7) * birim_fiyat / 3, 2)"
    degerler = {"adet": 15, "birim_fiyat": D("25.00")}
    ilk = hesapla(metin, degerler)
    assert all(hesapla(metin, degerler) == ilk for _ in range(50))
    assert str(ilk) == "16.67"
    assert ayristir(metin) is ayristir(metin)  # değişmez ağaç önbellekten
    with pytest.raises((AttributeError, TypeError)):
        ayristir(metin).deger = "x"  # type: ignore[misc]


def test_rastgele_ifadeler_python_tam_sayi_aritmetigiyle_ayni() -> None:
    """Özellik: rastgele tam sayı ifadeleri (+ - * // % ve parantez) Python ile aynı sonuç."""
    rnd = random.Random(99)

    def uret(derinlik: int) -> tuple[str, int]:
        if derinlik == 0 or rnd.random() < 0.3:
            n = rnd.randint(0, 20)
            return str(n), n
        sol_m, sol = uret(derinlik - 1)
        sag_m, sag = uret(derinlik - 1)
        op = rnd.choice(["+", "-", "*", "//", "%"])
        if op in ("//", "%") and sag == 0:
            op = "+"
        deger = {"+": sol + sag, "-": sol - sag, "*": sol * sag}.get(op)
        if deger is None:
            deger = sol // sag if op == "//" else sol % sag
        return f"({sol_m} {op} {sag_m})", deger

    denenen = 0
    while denenen < 300:
        metin, beklenen = uret(4)
        if len(metin) > ifade.AZAMI_IFADE_UZUNLUGU:
            continue
        denenen += 1
        assert hesapla(metin, {}) == beklenen, metin


def test_rastgele_cop_girdi_yalniz_ifade_hatasi() -> None:
    """Özellik: rastgele karakter dizileri ya değer ya `IfadeHatasi` verir; başka istisna yok."""
    rnd = random.Random(5)
    alfabe = "0123456789.+-*/%()<>=!,\"' abxyvedgilnoru_&|[]{}:;$\\\n\tçğıİş"
    for _ in range(3000):
        metin = "".join(rnd.choice(alfabe) for _ in range(rnd.randint(0, 40)))
        try:
            sonuc = hesapla(metin, {"a": 1, "b": D("2.5"), "x": True, "y": "m"})
        except IfadeHatasi as h:
            assert h.konum is None or 0 <= h.konum <= len(metin)
        else:
            assert isinstance(sonuc, Decimal | str | bool)


# ---------------------------------------------------------------------- sayı metni


@pytest.mark.parametrize(
    ("metin", "beklenen"),
    [
        ("1.250,00 TL", "1250.00"),
        ("−25,00 TL", "-25.00"),  # U+2212
        ("-25,00 TL", "-25.00"),
        ("750,00", "750.00"),
        ("7", "7"),
        ("1250.00", "1250.00"),
        ("0", "0"),
        ("0,00 TL", "0.00"),
        ("150,00 TL", "150.00"),
        ("150,00TL", "150.00"),
        ("125,5", "125.5"),
        ("1.250", "1250"),  # Türkçe binlik
        ("12.500", "12500"),
        ("125.000 TL", "125000"),
        ("1.250.000", "1250000"),
        ("1.250.000,50", "1250000.50"),
        ("1,250.00", "1250.00"),  # İngilizce yazım
        ("1,250,000", "1250000"),
        ("1,250", "1.250"),  # tek virgül ondalıktır
        ("0.125", "0.125"),
        ("1.5", "1.5"),
        ("12.50", "12.50"),
        ("1250.000", "1250.000"),
        ("1 250,00", "1250.00"),
        ("1 250,00 TL", "1250.00"),
        ("12 345", "12345"),
        ("₺1.250,00", "1250.00"),
        ("₺ 1.250,00", "1250.00"),
        ("₺-25", "-25"),
        ("-₺25", "-25"),
        ("- 25,00 TL", "-25.00"),
        ("TL 150,00", "150.00"),
        ("%20", "20"),
        ("20%", "20"),
        ("% 20", "20"),
        ("7 adet", "7"),
        ("7 adet bedava", "7"),
        ("1250,00 TL/adet", "1250.00"),
        ("+5", "5"),
        ("−0", "0"),
        ("  42  ", "42"),
        ("007", "7"),
    ],
)
def test_sayi_ayristir(metin: str, beklenen: str) -> None:
    sonuc = sayi_ayristir(metin)
    assert sonuc is not None and sonuc == D(beklenen)
    assert str(sonuc) == beklenen  # ondalık hane sayısı korunur


@pytest.mark.parametrize(
    "metin",
    [
        "",
        "   ",
        "abc",
        "TL",
        "-",
        "--5",
        "5-",
        "+-5",
        "₺--5",
        "-₺-5",
        "1.2.3",
        "1,25,0",
        "1..2",
        "1,,2",
        "7.",
        ".5",
        "1 2",
        "1 25,00",
        "3 koli 7 adet",
        "7 adet 3",
        "AC2",
        "S1",
        "P-004",
        "P004",
        "TPD-1",
        "1e5",
        "1.25e3",
        "0x10",
        "NaN",
        "Infinity",
        "٣",
        "１２",
        "7 TL'dir",
        "7 adet bedava ürün verilir",
        "1.250,00,5",
        "1,250.00.5",
        "12.34.567",
        "0.250.000",
        "5 - 3",
        "150,00 TL\nfazla",
        "9" * 31,
        "1" * 100,
    ],
)
def test_sayi_ayristir_sayi_degil(metin: str) -> None:
    assert sayi_ayristir(metin) is None


@pytest.mark.parametrize("deger", [None, 7, 7.5, D(7), ["7"], b"7", True])
def test_sayi_ayristir_metin_olmayan(deger: Any) -> None:
    assert sayi_ayristir(deger) is None


@pytest.mark.parametrize(
    ("deger", "ornek", "beklenen"),
    [
        ("300", "150,00 TL", "300,00 TL"),
        ("300.00", "150,00 TL", "300,00 TL"),
        ("-25", "150,00 TL", "-25,00 TL"),
        ("-25", "−10,00 TL", "−25,00 TL"),  # örneğin eksi glifi
        ("25", "−10,00 TL", "25,00 TL"),
        ("0", "−25,00 TL", "0,00 TL"),
        ("1500", "1.250,00 TL", "1.500,00 TL"),
        ("1234567.5", "1.250,00 TL", "1.234.567,50 TL"),
        ("999", "1.250,00 TL", "999,00 TL"),
        ("1500", "750,00", "1500,00"),  # örnekte binlik ayırıcı yok
        ("14", "7", "14"),
        ("14", "7 adet", "14 adet"),
        ("2.5", "1250.00", "2.50"),
        ("1500", "1,250.00", "1,500.00"),
        ("2500000", "1 250,00 TL", "2 500 000,00 TL"),
        ("1234567", "1.250 TL", "1.234.567 TL"),
        ("300", "₺150,00", "₺300,00"),
        ("-300", "₺-150,00", "₺-300,00"),
        ("-300", "-₺150,00", "-₺300,00"),
        ("300", "TL 150,00", "TL 300,00"),
        ("30", "%20", "%30"),
        ("30", "20%", "30%"),
        ("5", "+3", "+5"),
        ("-5", "+3", "-5"),
        ("5", "- 25,00 TL", "5,00 TL"),
        ("-5", "- 25,00 TL", "- 5,00 TL"),
        # Değer yuvarlanmaz: gereken hane yazılır.
        ("187.5", "125 TL", "187,5 TL"),
        ("187.5", "125,00 TL", "187,50 TL"),
        ("0.125", "125,00 TL", "0,125 TL"),
        ("3.5", "7", "3,5"),
        ("3.5", "1,250.00", "3.50"),
        ("1E+3", "7", "1000"),
        ("300.000", "150,00 TL", "300,00 TL"),
        # Tek noktalı belirsiz yazım bir hane eklenerek çözülür.
        ("1.234", "1250.00", "1.2340"),
    ],
)
def test_sayi_bicimle(deger: str, ornek: str, beklenen: str) -> None:
    sonuc = sayi_bicimle(D(deger), ornek)
    assert sonuc == beklenen
    assert sayi_ayristir(sonuc) == D(deger)


def test_sayi_bicimle_tam_sayi_kabul_eder_ve_hatalar() -> None:
    assert sayi_bicimle(300, "150,00 TL") == "300,00 TL"  # type: ignore[arg-type]
    for ornek in ("", "abc", "3 koli 7 adet", "AC2"):
        with pytest.raises(ValueError, match="örnek sayı biçiminde değil"):
            sayi_bicimle(D(1), ornek)
    for deger in (D("NaN"), D("Infinity"), D(10) ** 30):
        with pytest.raises(ValueError, match="sonlu ve sınır içinde"):
            sayi_bicimle(deger, "7")
    for deger in (True, "7", 7.5, None):
        with pytest.raises(ValueError, match="sayı olmalı"):
            sayi_bicimle(deger, "7")  # type: ignore[arg-type]


ORNEKLER = [
    "150,00 TL",
    "1.250,00 TL",
    "−25,00 TL",
    "-25,00 TL",
    "750,00",
    "7",
    "7 adet",
    "1250.00",
    "1,250.00",
    "1 250,00 TL",
    "₺1.250,00",
    "₺-25",
    "%20",
    "20%",
    "1.250 TL",
    "0,5",
    "0.125",
    "12 345",
    "TL 150,00",
    "+3",
]


def test_sayi_gidis_donus_ozelligi() -> None:
    """Özellik: her örnek biçiminde `sayi_ayristir(sayi_bicimle(x, örnek)) == x`; örneğin kendisi
    kendi biçiminde aynen yeniden yazılır."""
    rnd = random.Random(31)
    for ornek in ORNEKLER:
        kendi = sayi_ayristir(ornek)
        assert kendi is not None
        assert sayi_bicimle(kendi, ornek) == ornek, ornek
        for _ in range(200):
            hane = rnd.choice([0, 0, 1, 2, 2, 3, 4])
            x = D(rnd.randint(-(10**9), 10**9)).scaleb(-hane)
            yazi = sayi_bicimle(x, ornek)
            assert sayi_ayristir(yazi) == x, (x, ornek, yazi)
            # ön ek / son ek korunur
            assert yazi.endswith(ornek.lstrip("+-−₺%TL 0123456789., ")), (ornek, yazi)


def test_sayi_bicimle_belirleyici() -> None:
    assert {sayi_bicimle(D("1234.5"), "1.250,00 TL") for _ in range(20)} == {"1.234,50 TL"}


@pytest.mark.parametrize(
    ("a", "b", "tolerans", "beklenen"),
    [
        (D("150.00"), D("150"), D(0), True),
        (D("150.00"), D("150.01"), D(0), False),
        (D("150.00"), D("150.01"), D("0.01"), True),
        (D("150.00"), D("149.99"), D("0.01"), True),
        (D("150.00"), D("150.011"), D("0.01"), False),
        (D("-25"), D("25"), D(0), False),
        (7, D(7), D(0), True),
        (7, 7.0, D(0), True),
        (0.1, D("0.1"), D(0), True),
        (D(7), "7", D(0), False),  # örtük dönüşüm yok
        ("P-001", "P-001", D(0), True),
        (" P-001 ", "P-001", D(0), True),
        ("P-001", "p-001", D(0), False),
        ("7", "7,0", D(0), False),
        (True, True, D(0), True),
        (True, False, D(0), False),
        (True, 1, D(0), False),  # bool sayı değildir
        (D(1), True, D(1), False),
        (None, None, D(0), False),
        (None, D(0), D(0), False),
        (D("NaN"), D("NaN"), D(0), False),
        (float("inf"), float("inf"), D(0), False),
        ([1], [1], D(0), False),
    ],
)
def test_esit_mi(a: Any, b: Any, tolerans: Decimal, beklenen: bool) -> None:
    assert esit_mi(a, b, tolerans) is beklenen
    assert esit_mi(b, a, tolerans) is beklenen  # simetrik


def test_esit_mi_tolerans_denetimi() -> None:
    assert esit_mi(D(1), D(1)) is True  # varsayılan tolerans 0
    assert esit_mi(D(1), D("1.5"), 1) is True  # type: ignore[arg-type]
    for kotu in (D("-0.01"), D("NaN"), None, "0.01", True):
        with pytest.raises(ValueError, match="tolerans"):
            esit_mi(D(1), D(1), kotu)  # type: ignore[arg-type]


# ---------------------------------------------------------------------- şemalar


@pytest.mark.parametrize("ad", ["karar_tablosu", "metamorfik_iliski"])
def test_icerik_semalari_gecerli_ve_kapali(ad: str) -> None:
    yol = find_rules_dir() / "schemas" / "icerik" / f"{ad}.schema.json"
    sema = json.loads(yol.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(sema)
    assert sema == ifade.sema(ad)
    assert sema["additionalProperties"] is False

    def nesneler(s: Any) -> Any:
        if isinstance(s, dict):
            if s.get("type") == "object":
                yield s
            for v in s.values():
                yield from nesneler(v)
        elif isinstance(s, list):
            for v in s:
                yield from nesneler(v)

    for nesne in nesneler(sema):
        assert nesne.get("additionalProperties") is not None, nesne  # False ya da ifade şeması
        assert nesne["additionalProperties"] is False or "propertyNames" in nesne
    with pytest.raises(ValueError, match="bilinmeyen içerik şeması"):
        ifade.sema("../models")


def test_sema_sinirlari_modul_sabitleriyle_ayni() -> None:
    s = ifade.sema("karar_tablosu")
    assert s["properties"]["girdiler"]["maxItems"] == ifade.AZAMI_GIRDI == 12
    assert s["properties"]["ciktilar"]["maxItems"] == ifade.AZAMI_CIKTI == 12
    assert s["properties"]["satirlar"]["maxItems"] == ifade.AZAMI_SATIR == 60
    assert s["$defs"]["ifade"]["maxLength"] == ifade.AZAMI_IFADE_UZUNLUGU == 300
    assert set(s["$defs"]["tur"]["enum"]) == ifade.TURLER
    i = ifade.sema("metamorfik_iliski")
    assert i["$defs"]["ifade"] == s["$defs"]["ifade"] and i["$defs"]["ad"] == s["$defs"]["ad"]
    from tp_core.models import enums

    assert enums.KARAR_TABLOSU_TUR == ifade.TURLER


def test_sema_rules_dir_parametresi(tmp_path: Path) -> None:
    hedef = tmp_path / "schemas" / "icerik"
    hedef.mkdir(parents=True)
    kaynak = find_rules_dir() / "schemas" / "icerik"
    for dosya in kaynak.glob("*.json"):
        (hedef / dosya.name).write_text(dosya.read_text(encoding="utf-8"), encoding="utf-8")
    assert dogrula(TABLO, tmp_path) == []
    assert degerlendir(TABLO, {"adet": 7, "birim_fiyat": 25}, tmp_path).satir_id == "R1"


# ---------------------------------------------------------------------- dogrula


def test_ornek_tablo_gecerli() -> None:
    assert dogrula(TABLO) == []
    assert gonderim_hatalari(TABLO) == []
    assert dogrula(ARA_TUTAR_TABLOSU) == []


def test_bos_taslak_gecerli_ama_gonderilemez() -> None:
    bos = {"ad": "Yeni tablo", "ac_refs": [], "girdiler": [], "ciktilar": [], "satirlar": []}
    assert dogrula(bos) == []
    assert gonderim_hatalari(bos) == [
        "ac_refs: en az bir kabul kriteri olmalı",
        "girdiler: en az bir girdi olmalı",
        "ciktilar: en az bir çıktı olmalı",
        "satirlar: en az bir satır olmalı",
    ]
    assert degerlendir(bos, {}) == Degerlendirme()


@pytest.mark.parametrize(
    ("degisen", "beklenen"),
    [
        ({"ad": ""}, "ad: boş olamaz"),
        ({"ad": "x" * 121}, "ad: en çok 120 karakter olabilir"),
        ({"ad": 7}, "ad: metin olmalı"),
        ({"ac_refs": ["AC1", "AC1"]}, "ac_refs: yinelenen öğe var"),
        ({"ac_refs": ["ac1"]}, "ac_refs[0]: biçim geçersiz (beklenen desen: ^AC[0-9]+$)"),
        ({"ac_refs": "AC1"}, "ac_refs: liste olmalı"),
        ({"fazla": 1}, "(kök): bilinmeyen alan: fazla"),
        ({"girdiler": [{"ad": "adet"}]}, "girdiler[0]: zorunlu alan eksik: tur"),
        (
            {"girdiler": [{"ad": "adet", "tur": "tarih"}]},
            "girdiler[0].tur: şu değerlerden biri olmalı: sayi, metin, mantiksal",
        ),
        (
            {"girdiler": [{"ad": "Adet", "tur": "sayi"}]},
            "girdiler[0].ad: biçim geçersiz (beklenen desen: ^[a-z][a-z0-9_]{0,39}$)",
        ),
        (
            {"girdiler": [{"ad": "__class__", "tur": "sayi"}]},
            "girdiler[0].ad: biçim geçersiz (beklenen desen: ^[a-z][a-z0-9_]{0,39}$)",
        ),
        (
            {"girdiler": [{"ad": "adet", "tur": "sayi", "gizli": 1}]},
            "girdiler[0]: bilinmeyen alan: gizli",
        ),
        (
            {"girdiler": [{"ad": f"g{i}", "tur": "sayi"} for i in range(13)]},
            "girdiler: en çok 12 öğe olabilir",
        ),
        (
            {"ciktilar": [{"ad": f"c{i}", "tur": "sayi"} for i in range(13)]},
            "ciktilar: en çok 12 öğe olabilir",
        ),
        (
            {"satirlar": [{"id": f"R{i}", "kosul": "dogru", "cikti": {}} for i in range(61)]},
            "satirlar: en çok 60 öğe olabilir",
        ),
        (
            {"satirlar": [{"id": "1", "kosul": "dogru", "cikti": {}}]},
            "satirlar[0].id: biçim geçersiz (beklenen desen: ^R[0-9]{1,3}$)",
        ),
        (
            {"satirlar": [{"id": "R1", "kosul": "1" * 301, "cikti": {}}]},
            "satirlar[0].kosul: en çok 300 karakter olabilir",
        ),
        (
            {"satirlar": [{"id": "R1", "kosul": "", "cikti": {}}]},
            "satirlar[0].kosul: boş olamaz",
        ),
        ({"satirlar": [{"id": "R1", "kosul": "dogru"}]}, "satirlar[0]: zorunlu alan eksik: cikti"),
        (
            {"satirlar": [{"id": "R1", "kosul": "dogru", "cikti": {"bedava_adet": 0}}]},
            "satirlar[0].cikti.bedava_adet: metin olmalı",
        ),
        (
            {"satirlar": [{"id": "R1", "kosul": "dogru", "cikti": {"Kötü Ad": "0"}}]},
            "satirlar[0].cikti: alan adı geçersiz: 'Kötü Ad'",
        ),
    ],
)
def test_dogrula_sema_hatalari(degisen: dict[str, Any], beklenen: str) -> None:
    assert beklenen in dogrula(tablo(**degisen))


def test_dogrula_sema_hatasi_varken_anlam_denetimi_yapilmaz() -> None:
    hatalar = dogrula({"ad": "x"})
    assert hatalar == ["(kök): zorunlu alan eksik: ac_refs, girdiler, ciktilar, satirlar"]
    assert dogrula("tablo") == ["(kök): nesne olmalı"]  # type: ignore[arg-type]
    assert dogrula(None) == ["(kök): nesne olmalı"]  # type: ignore[arg-type]


def test_dogrula_tolerans() -> None:
    def cikti(**ek: Any) -> list[dict[str, Any]]:
        return [{"ad": "bedava_adet", "tur": "sayi"}, {"ad": "indirim", "tur": "sayi", **ek}]

    assert dogrula(tablo(ciktilar=cikti(tolerans="0"))) == []
    assert dogrula(tablo(ciktilar=cikti(tolerans="0.005"))) == []
    for kotu in ("-0.01", "0,01", "bir", "", ".5", "1e-2"):
        assert any(
            "ciktilar[1].tolerans" in h for h in dogrula(tablo(ciktilar=cikti(tolerans=kotu)))
        )
    assert "ciktilar[1].tolerans: metin olmalı" in dogrula(tablo(ciktilar=cikti(tolerans=0.01)))
    metinli = tablo(
        ciktilar=[
            {"ad": "bedava_adet", "tur": "sayi"},
            {"ad": "indirim", "tur": "metin", "tolerans": "1"},
        ],
        satirlar=[
            {"id": "R1", "kosul": "dogru", "cikti": {"bedava_adet": "0", "indirim": '"yok"'}}
        ],
    )
    assert dogrula(metinli) == ["ciktilar[1].tolerans: yalnız sayı türündeki çıktıda verilir"]
    assert toleranslar(TABLO) == {"bedava_adet": D(0), "indirim": D("0.01")}


def test_dogrula_anlam_hatalari() -> None:
    def satir(**ek: Any) -> dict[str, Any]:
        return {
            "id": "R1",
            "kosul": "adet >= 7",
            "cikti": {"bedava_adet": "0", "indirim": "0"},
        } | ek

    def tek(s: dict[str, Any], **ek: Any) -> list[str]:
        return dogrula(tablo(satirlar=[s], **ek))

    assert tek(satir()) == []
    assert tek(satir(kosul="adet")) == [
        "satirlar[0] (R1) koşul: sonuç mantıksal olmalı (sayı bulundu)"
    ]
    assert tek(satir(kosul="adet >=")) == [
        "satirlar[0] (R1) koşul: ifade eksik (değer bekleniyor) (konum 8)"
    ]
    assert tek(satir(kosul="miktar >= 7")) == [
        "satirlar[0] (R1) koşul: bilinmeyen ad: miktar (konum 1)"
    ]
    # Çıktı ifadesi başka bir çıktıya başvuramaz: yalnız girdi adları.
    assert tek(satir(cikti={"bedava_adet": "1", "indirim": "bedava_adet * birim_fiyat"})) == [
        "satirlar[0] (R1) çıktı 'indirim': bilinmeyen ad: bedava_adet (konum 1)"
    ]
    assert tek(satir(cikti={"bedava_adet": "adet > 7", "indirim": "0"})) == [
        "satirlar[0] (R1) çıktı 'bedava_adet': sonuç sayı olmalı (mantıksal bulundu)"
    ]
    assert tek(satir(cikti={"bedava_adet": "0"})) == ["satirlar[0] (R1): çıktı eksik: indirim"]
    assert tek(satir(cikti={"bedava_adet": "0", "indirim": "0", "kdv": "0"})) == [
        "satirlar[0] (R1) çıktı 'kdv': tanımlı bir çıktı değil"
    ]
    assert dogrula(tablo(satirlar=[satir(), satir()])) == [
        "satirlar[1] (R1): satır kimliği birden çok kez kullanılmış"
    ]
    cift = [{"ad": "adet", "tur": "sayi"}, {"ad": "adet", "tur": "sayi"}]
    assert "girdiler[1].ad: 'adet' adı birden çok kez kullanılmış" in dogrula(tablo(girdiler=cift))
    # Aynı ad hem girdi hem çıktı olamaz (ilişkiler ikisini tek ortamda kullanır).
    ayni = [{"ad": "adet", "tur": "sayi"}, {"ad": "indirim", "tur": "sayi"}]
    assert "ciktilar[0].ad: 'adet' adı birden çok kez kullanılmış" in dogrula(
        tablo(ciktilar=ayni, satirlar=[])
    )
    for ayrilmis in sorted(ifade.AYRILMIS_ADLAR):
        girdiler = [{"ad": ayrilmis, "tur": "sayi"}]
        assert f"girdiler[0].ad: '{ayrilmis}' ayrılmış sözcüktür, ad olamaz" in dogrula(
            tablo(girdiler=girdiler, satirlar=[])
        )


def test_dogrula_hata_sayisi_sinirli() -> None:
    satirlar = [{"id": f"R{i}", "kosul": "yok > 1", "cikti": {}} for i in range(60)]
    hatalar = dogrula(tablo(satirlar=satirlar))
    assert len(hatalar) == ifade.AZAMI_HATA


def test_dogrula_icerigi_degistirmez() -> None:
    once = copy.deepcopy(TABLO)
    dogrula(TABLO)
    degerlendir(TABLO, {"adet": 7, "birim_fiyat": 25})
    assert once == TABLO


# ---------------------------------------------------------------------- degerlendir


@pytest.mark.parametrize(
    ("adet", "satir", "bedava", "indirim"),
    [
        (0, "R2", "0", "0"),
        (6, "R2", "0", "0"),
        (7, "R1", "1", "25.00"),
        (13, "R1", "1", "25.00"),
        (14, "R1", "2", "50.00"),
        (70, "R1", "10", "250.00"),
    ],
)
def test_degerlendir_ornek_tablo(adet: int, satir: str, bedava: str, indirim: str) -> None:
    s = degerlendir(TABLO, {"adet": adet, "birim_fiyat": D("25.00")})
    assert s == Degerlendirme(satir, {"bedava_adet": D(bedava), "indirim": D(indirim)}, [], None)
    assert str(s.ciktilar["indirim"]) == indirim
    assert s.as_dict() == {
        "satir_id": satir,
        "ciktilar": {"bedava_adet": bedava, "indirim": indirim},
        "eksik_girdiler": [],
        "hata": None,
    }
    json.dumps(s.as_dict())


def test_degerlendir_ilk_eslesen_satir() -> None:
    t = tablo(
        ciktilar=[{"ad": "sonuc", "tur": "metin"}],
        satirlar=[
            {"id": "R1", "kosul": "adet >= 100", "cikti": {"sonuc": '"cok"'}},
            {"id": "R2", "kosul": "adet >= 10", "cikti": {"sonuc": '"orta"'}},
            {"id": "R3", "kosul": "adet >= 10", "cikti": {"sonuc": '"golgede"'}},
            {"id": "R4", "kosul": "dogru", "cikti": {"sonuc": '"az"'}},
        ],
    )
    assert dogrula(t) == []
    beklenen = {5: ("R4", "az"), 10: ("R2", "orta"), 99: ("R2", "orta"), 100: ("R1", "cok")}
    for adet, (satir, sonuc) in beklenen.items():
        s = degerlendir(t, {"adet": adet})
        assert (s.satir_id, s.ciktilar) == (satir, {"sonuc": sonuc}), adet


def test_degerlendir_satir_yok() -> None:
    t = tablo(satirlar=[TABLO["satirlar"][0]])
    s = degerlendir(t, {"adet": 3, "birim_fiyat": 25})
    assert s == Degerlendirme(None, {}, [], None)  # uyuşmazlık değil


def test_degerlendir_eksik_girdi_hata_firlatmaz() -> None:
    assert degerlendir(TABLO, {}) == Degerlendirme(eksik_girdiler=["adet", "birim_fiyat"])
    assert degerlendir(TABLO, {"adet": 7}).eksik_girdiler == ["birim_fiyat"]
    assert degerlendir(TABLO, {"birim_fiyat": 25, "adet": None}).eksik_girdiler == ["adet"]
    # Hiçbir ifadede kullanılmayan girdi eksik sayılmaz.
    t = tablo(girdiler=[*TABLO["girdiler"], {"ad": "bayi", "tur": "metin"}])
    assert degerlendir(t, {"adet": 7, "birim_fiyat": 25}).satir_id == "R1"
    # Tabloda olmayan fazladan girdi yok sayılır.
    assert degerlendir(TABLO, {"adet": 7, "birim_fiyat": 25, "renk": "mavi"}).satir_id == "R1"


@pytest.mark.parametrize(
    ("deger", "beklenen"),
    [
        (7, D(7)),
        (D("7.0"), D("7.0")),
        (7.5, D("7.5")),
        ("7", D(7)),
        ("25.00", D("25.00")),
        ("-3", D(-3)),
        ("25,00 TL", D("25.00")),
        ("1.250,00 TL", D("1250.00")),
        (" 7 ", D(7)),
    ],
)
def test_girdi_donustur_sayi(deger: Any, beklenen: Decimal) -> None:
    assert girdi_donustur(deger, "sayi") == beklenen


def test_girdi_donustur_diger_turler_ve_hatalar() -> None:
    assert girdi_donustur("P-001", "metin") == "P-001"
    assert girdi_donustur(True, "mantiksal") is True
    assert girdi_donustur("dogru", "mantiksal") is True
    assert girdi_donustur("False", "mantiksal") is False
    assert girdi_donustur(" yanlis ", "mantiksal") is False
    for deger, tur, mesaj in [
        (True, "sayi", "sayı bekleniyor"),
        ("yedi", "sayi", "sayı bekleniyor"),
        (None, "sayi", "sayı bekleniyor"),
        (float("nan"), "sayi", "sayı bekleniyor"),
        (D(10) ** 30, "sayi", "sayı çok büyük"),
        (7, "metin", "metin bekleniyor"),
        (1, "mantiksal", "mantıksal değer"),
        ("evet", "mantiksal", "mantıksal değer"),
        (1, "tarih", "geçersiz tür"),
    ]:
        with pytest.raises(IfadeHatasi, match=mesaj):
            girdi_donustur(deger, tur)


def test_degerlendir_sorunlari_hata_alaninda() -> None:
    s = degerlendir(TABLO, {"adet": "yedi", "birim_fiyat": 25})
    assert s == Degerlendirme(hata="girdi 'adet': sayı bekleniyor")
    s = degerlendir(TABLO, {"adet": True, "birim_fiyat": 25})
    assert s.hata == "girdi 'adet': sayı bekleniyor"
    s = degerlendir(tablo(ad=""), {"adet": 7, "birim_fiyat": 25})
    assert s.hata == "karar tablosu geçersiz: ad: boş olamaz" and s.satir_id is None
    assert degerlendir(TABLO, ["adet"]).hata == "girdiler ad → değer sözlüğü olmalı"  # type: ignore[arg-type]
    sifir = {"bedava_adet": "0", "indirim": "0"}
    bolme = tablo(satirlar=[{"id": "R1", "kosul": "birim_fiyat / adet > 1", "cikti": sifir}])
    s = degerlendir(bolme, {"adet": 0, "birim_fiyat": 25})
    assert s == Degerlendirme(hata="satır R1 koşul: sıfıra bölme (konum 13)")
    bolen = {"bedava_adet": "1", "indirim": "birim_fiyat / adet"}
    cikti_bolme = tablo(satirlar=[{"id": "R1", "kosul": "dogru", "cikti": bolen}])
    s = degerlendir(cikti_bolme, {"adet": 0, "birim_fiyat": 25})
    assert (s.satir_id, s.ciktilar) == ("R1", {})
    assert s.hata == "satır R1 çıktı 'indirim': sıfıra bölme (konum 13)"


def test_degerlendir_metin_ve_mantiksal_kolonlar() -> None:
    t = {
        "ad": "Minimum sipariş",
        "ac_refs": ["AC3"],
        "girdiler": [
            {"ad": "toplam", "tur": "sayi", "birim": "TL"},
            {"ad": "kampanyali", "tur": "mantiksal"},
            {"ad": "bayi_tipi", "tur": "metin"},
        ],
        "ciktilar": [{"ad": "kabul", "tur": "mantiksal"}, {"ad": "mesaj", "tur": "metin"}],
        "satirlar": [
            {
                "id": "R1",
                "kosul": 'kampanyali veya bayi_tipi == "vip"',
                "cikti": {"kabul": "dogru", "mesaj": '"muaf"'},
            },
            {
                "id": "R2",
                "kosul": "toplam >= 750",
                "cikti": {"kabul": "dogru", "mesaj": '"tamam"'},
            },
            {
                "id": "R3",
                "kosul": "dogru",
                "cikti": {"kabul": "yanlis", "mesaj": '"min_siparis"'},
            },
        ],
    }
    assert dogrula(t) == []
    ortak = {"kampanyali": False, "bayi_tipi": "std"}
    assert degerlendir(t, {"toplam": "750,00 TL", **ortak}).ciktilar == {
        "kabul": True,
        "mesaj": "tamam",
    }
    assert degerlendir(t, {"toplam": D("749.99"), **ortak}).ciktilar == {
        "kabul": False,
        "mesaj": "min_siparis",
    }
    s = degerlendir(t, {"toplam": 10, "kampanyali": "dogru", "bayi_tipi": "std"})
    assert (s.satir_id, s.ciktilar["mesaj"]) == ("R1", "muaf")
    assert degerlendir(t, {"toplam": 10, "kampanyali": False, "bayi_tipi": "vip"}).satir_id == "R1"
    assert degerlendir(t, {"toplam": 10, **ortak}).as_dict()["ciktilar"] == {
        "kabul": False,
        "mesaj": "min_siparis",
    }


def test_degerlendir_belirleyici_ve_tolerans_ile_karsilastirma() -> None:
    girdiler = {"adet": 14, "birim_fiyat": "25,00 TL"}
    ilk = degerlendir(TABLO, girdiler)
    assert all(degerlendir(TABLO, girdiler) == ilk for _ in range(25))
    tol = toleranslar(TABLO)
    # Case "50,00 TL" bekliyor: uyumlu. "50,01" tolerans içinde, "50,02" dışında.
    for metin, uyumlu in [("50,00 TL", True), ("50,01 TL", True), ("50,02 TL", False)]:
        assert esit_mi(sayi_ayristir(metin), ilk.ciktilar["indirim"], tol["indirim"]) is uyumlu
    assert esit_mi(sayi_ayristir("2"), ilk.ciktilar["bedava_adet"], tol["bedava_adet"]) is True
    assert esit_mi(sayi_ayristir("3"), ilk.ciktilar["bedava_adet"], tol["bedava_adet"]) is False


def test_degerlendir_ozellik_kampanya_formulu() -> None:
    """Özellik: örnek tablo her adet için `adet // 7` ve `(adet // 7) * fiyat` verir."""
    rnd = random.Random(3)
    for _ in range(300):
        adet = rnd.randint(0, 999)
        fiyat = D(rnd.randint(1, 99999)) / D(100)
        s = degerlendir(TABLO, {"adet": adet, "birim_fiyat": fiyat})
        assert s.hata is None and s.eksik_girdiler == []
        assert s.satir_id == ("R1" if adet >= 7 else "R2")
        assert s.ciktilar == {"bedava_adet": D(adet // 7), "indirim": (adet // 7) * fiyat}


# ---------------------------------------------------------------------- ilişki


def test_iliski_dogrula() -> None:
    assert iliski_dogrula(ILISKI) == []
    assert iliski_dogrula(ILISKI, ARA_TUTAR_TABLOSU) == []
    assert iliski_dogrula({"ad": "x"}) == [
        "(kök): zorunlu alan eksik: ac_refs, on_kosul, donusum, iliski"
    ]
    assert iliski_dogrula({**ILISKI, "fazla": 1}) == ["(kök): bilinmeyen alan: fazla"]
    assert iliski_dogrula({**ILISKI, "tablo_ref": "tablo"}) == [
        "tablo_ref: biçim geçersiz (beklenen desen: ^T[1-9][0-9]{0,3}$)"
    ]
    assert iliski_dogrula({**ILISKI, "donusum": {}}) == ["donusum: en az 1 alan olmalı"]
    assert iliski_dogrula({**ILISKI, "on_kosul": "adet >="}) == [
        "on_kosul: ifade eksik (değer bekleniyor) (konum 8)"
    ]
    # Tablo olmadan yalnız sözdizimi; tabloyla adlar ve türler de.
    kotu = {**ILISKI, "donusum": {"miktar": "adet * 2"}, "iliski": {"ara_tutar": "adet > 1"}}
    assert iliski_dogrula(kotu) == []
    assert iliski_dogrula(kotu, ARA_TUTAR_TABLOSU) == [
        "donusum.miktar: tabloda böyle bir girdi yok",
        "iliski.ara_tutar: sonuç sayı olmalı (mantıksal bulundu)",
    ]
    assert iliski_dogrula({**ILISKI, "on_kosul": "ara_tutar > 0"}, ARA_TUTAR_TABLOSU) == [
        "on_kosul: bilinmeyen ad: ara_tutar (konum 1)"  # ön koşul yalnız girdiler üzerinde
    ]
    assert iliski_dogrula({**ILISKI, "on_kosul": "adet * 2"}, ARA_TUTAR_TABLOSU) == [
        "on_kosul: sonuç mantıksal olmalı (sayı bulundu)"
    ]
    assert iliski_dogrula({**ILISKI, "iliski": {"adet": "adet"}}, ARA_TUTAR_TABLOSU) == [
        "iliski.adet: tabloda böyle bir çıktı yok"
    ]


def test_iliski_uygula() -> None:
    s = iliski_uygula(ILISKI, {"adet": 3, "birim_fiyat": D("25.00")}, {"ara_tutar": D("75.00")})
    assert s.gecerli and s.hata is None and s.eksik == []
    assert s.girdiler == {"adet": D(6), "birim_fiyat": D("25.00")}
    assert s.ciktilar == {"ara_tutar": D("150.00")}
    assert sayi_bicimle(s.ciktilar["ara_tutar"], "75,00 TL") == "150,00 TL"
    # Türetilen değerler tabloyla da tutarlı (ilişki ile tablo çelişmiyor).
    assert degerlendir(ARA_TUTAR_TABLOSU, s.girdiler).ciktilar == s.ciktilar


def test_iliski_uygula_on_kosul_eksik_ve_hata() -> None:
    s = iliski_uygula(ILISKI, {"adet": 500}, {"ara_tutar": D(100)})
    assert (s.gecerli, s.girdiler, s.ciktilar, s.eksik, s.hata) == (False, {}, {}, [], None)
    assert iliski_uygula(ILISKI, {"adet": 0}, {"ara_tutar": D(0)}).gecerli is False
    assert iliski_uygula(ILISKI, {}, {"ara_tutar": D(1)}).eksik == ["adet"]
    assert iliski_uygula(ILISKI, {"adet": 2}, {}).eksik == ["ara_tutar"]
    assert iliski_uygula(ILISKI, {"adet": None}, {"ara_tutar": None}).eksik == ["adet", "ara_tutar"]
    # Ön koşul yalnız kaynak girdilerle hesaplanır: çıktı adı girdi yerine geçmez.
    cikti_kosullu = {**ILISKI, "on_kosul": "ara_tutar > 0"}
    assert iliski_uygula(cikti_kosullu, {"adet": 1}, {"ara_tutar": 5}).eksik == ["ara_tutar"]
    bolmeli = {**ILISKI, "iliski": {"ara_tutar": "ara_tutar / (adet - 2)"}}
    s = iliski_uygula(bolmeli, {"adet": 2}, {"ara_tutar": 5})
    assert s.gecerli is False and s.hata == "sıfıra bölme (konum 11)"
    s = iliski_uygula(ILISKI, {"adet": "iki"}, {"ara_tutar": 5})
    assert s.gecerli is False and "sayı olmalı (metin verildi)" in (s.hata or "")
    assert iliski_uygula(ILISKI, {"adet": object()}, {}).hata == "'adet' için geçersiz değer"
