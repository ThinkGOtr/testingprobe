"""Beklenen değer kaynağı normu ve eşlemenin deterministik kontrolleri (§8.4 adım 3)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tp_core.features.codegen import checks
from tp_core.features.codegen.normalize import find_source, tokens, tr_lower, value_tokens

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
RULES = REPO / "rules"


def symbols() -> checks.SymbolTable:
    return checks.SymbolTable(json.loads((HERE / "symbols.json").read_text(encoding="utf-8")))


def golden_case(n: int) -> dict[str, Any]:
    data = json.loads((RULES / "replay/case_generation/golden/TPD-1.json").read_text("utf-8"))
    return data["output"]["cases"][n - 1]


def golden_mapping(n: int) -> dict[str, Any]:
    p = RULES / f"replay/verify_and_map/golden/TPD-1-C{n}.json"
    return json.loads(p.read_text("utf-8"))["output"]


FIXTURES = {"loginPage", "catalogPage", "cartPage", "orderPage", "dealer", "signedIn"}


# ------------------------------------------------------------------------- norm


def test_turkce_kucuk_harf() -> None:
    assert tr_lower("İSTANBUL IĞDIR") == "istanbul ığdır"
    assert tokens("SİPARİŞ") == tokens("sipariş")


@pytest.mark.parametrize(
    ("deger", "metin"),
    [
        ("1.250,00 TL", "Toplam 1250 TL"),
        (1250, "Toplam 1.250,00 TL"),
        ("150,00 TL", "toplam 150 tl"),
        ("−25,00 TL", "indirim −25,00 TL"),
        ("Minimum sipariş tutarı 750,00 TL", '"MİNİMUM SİPARİŞ TUTARI 750,00 TL" uyarısı'),
        ("P-001", "P-001 satırında adet 7"),
        (7, "P-001 satırında adet 7"),
        (12.5, "oran 12,5"),
    ],
)
def test_kaynak_bulunur(deger: Any, metin: str) -> None:
    assert find_source(deger, [metin]) == metin


@pytest.mark.parametrize(
    ("deger", "metin"),
    [
        (1, "P-001 satırında adet 7"),  # ürün kodundaki 001 ayrı sayı sayılmaz
        ("151,00 TL", "toplam 150,00 TL"),
        ("150,00 TL", "toplam 150,00"),  # para birimi de geçmeli
        (True, "true"),  # mantıksal değer metinden kaynaklanamaz
        ("", "her şey"),
        ("Minimum tutar", "Minimum sipariş tutarı"),  # ardışık olmalı
        ("+1", "bedava adet 1"),  # işaret/noktalama da metinde geçmeli
        ("1)", "bedava adet 1"),
        ("1;", "bedava adet 1"),
        ("Toplam.", "Toplam 150,00 TL"),
        (5, "stok -5"),  # eksi işareti sayının parçasıdır
        ("25,00 TL", "indirim −25,00 TL"),
        (-5, "stok 5"),
    ],
)
def test_kaynaksiz(deger: Any, metin: str) -> None:
    assert find_source(deger, [metin]) is None


def test_sayi_simgesi() -> None:
    assert value_tokens(1250) == value_tokens("1.250,00") == ["#1250"]
    assert value_tokens(0) == value_tokens("0,00") == ["#0"]


# ------------------------------------------------------------- golden eşlemeleri


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6, 8, 9, 10])
def test_golden_eslemeler_kontrollerden_gecer(n: int) -> None:
    sonuc = checks.check_mapping(golden_mapping(n), golden_case(n), symbols(), fixtures=FIXTURES)
    assert sonuc.ok, sonuc.ozet()
    assert len(sonuc.kaynaklar) == len(golden_mapping(n)["expects"])


def test_kredi_limiti_case_i_eksik_metotla_insana_gider() -> None:
    sonuc = checks.check_mapping(golden_mapping(7), golden_case(7), symbols(), fixtures=FIXTURES)
    assert not sonuc.ok
    assert sonuc.engel_turu == "missing_method"
    assert "eksik metot" in sonuc.ozet()


def test_uydurma_beklenen_deger_reddedilir() -> None:
    m = copy.deepcopy(golden_mapping(2))
    m["expects"][-1]["args"] = ["175,00 TL"]  # toplam 150; 175 yalnız ara toplamda geçer
    sonuc = checks.check_mapping(m, golden_case(2), symbols())
    assert sonuc.ok  # 175,00 TL beklenen metinde (ara toplam) geçiyor: kaynaklı
    m["expects"][-1]["args"] = ["999,00 TL"]
    sonuc = checks.check_mapping(m, golden_case(2), symbols())
    assert sonuc.engel_turu == "unsourced_value"
    assert "kaynağı olmayan beklenen değer" in sonuc.ozet()


def test_beklenen_deger_yalniz_eylem_metninde_gecerse_reddedilir() -> None:
    m = copy.deepcopy(golden_mapping(1))
    case = golden_case(1)
    # "Demo123!" yalnızca adım verisinde geçer, beklenen metinde değil.
    m["expects"] = [{"po": "LoginPage", "method": "expectLoginError", "args": ["Demo123!"]}]
    sonuc = checks.check_mapping(m, case, symbols())
    assert sonuc.engel_turu == "unsourced_value"


def test_bilinmeyen_metot_ve_imza() -> None:
    table = symbols()
    case = golden_case(2)
    m = copy.deepcopy(golden_mapping(2))
    m["step_mapping"][2]["method"] = "addToBasket"
    assert checks.check_mapping(m, case, table).engel_turu == "unknown_method"
    m = copy.deepcopy(golden_mapping(2))
    m["step_mapping"][2]["args"] = ["P-001", "7"]  # number yerine metin
    s = checks.check_mapping(m, case, table)
    assert s.engel_turu == "unknown_method" and "tür uyumsuz" in s.ozet()
    m = copy.deepcopy(golden_mapping(2))
    m["step_mapping"][2]["args"] = ["P-001"]
    assert "argüman bekler" in checks.check_mapping(m, case, table).ozet()
    m = copy.deepcopy(golden_mapping(2))
    m["step_mapping"][2]["args"] = ["P-001", True]
    assert "tür uyumsuz" in checks.check_mapping(m, case, table).ozet()


def test_assertion_adim_eslemesine_gizlenemez() -> None:
    m = copy.deepcopy(golden_mapping(2))
    m["step_mapping"].append(
        {
            "step_id": "S4",
            "po": "CartPage",
            "method": "expectTotal",
            "args": ["150,00 TL"],
            "verified": True,
            "evidence_ref": None,
        }
    )
    s = checks.check_mapping(m, golden_case(2), symbols())
    assert "eylem (action) metodu değil" in s.ozet()


def test_dogrulanmamis_ve_eksik_adim() -> None:
    m = copy.deepcopy(golden_mapping(2))
    m["step_mapping"][1]["verified"] = False
    s = checks.check_mapping(m, golden_case(2), symbols())
    assert s.engel_turu == "unverified_step" and "S2" in s.ozet()
    m = copy.deepcopy(golden_mapping(2))
    del m["step_mapping"][3]
    s = checks.check_mapping(m, golden_case(2), symbols())
    assert "S4: adım eşlenmedi" in s.ozet()
    m = copy.deepcopy(golden_mapping(2))
    m["step_mapping"][0]["step_id"] = "S9"
    assert "case'te böyle bir adım yok" in checks.check_mapping(m, golden_case(2), symbols()).ozet()


def test_dogrulamasiz_test_reddedilir() -> None:
    m = copy.deepcopy(golden_mapping(2))
    m["expects"] = []
    assert "doğrulama (expect) yok" in checks.check_mapping(m, golden_case(2), symbols()).ozet()


def test_girdi_degeri_de_case_metninden_gelmeli() -> None:
    m = copy.deepcopy(golden_mapping(2))
    m["step_mapping"][2]["args"] = ["P-004", 7]
    s = checks.check_mapping(m, golden_case(2), symbols())
    assert s.engel_turu == "unsourced_value" and "girdisi 'P-004'" in s.ozet()


def test_gecersiz_tanimlayici_ve_eksik_fikstur() -> None:
    m = copy.deepcopy(golden_mapping(2))
    m["expects"][0]["po"] = "CartPage;process"
    assert "geçersiz ad" in checks.check_mapping(m, golden_case(2), symbols()).ozet()
    s = checks.check_mapping(golden_mapping(2), golden_case(2), symbols(), fixtures={"loginPage"})
    assert "cartPage" in s.ozet() and "fikstürü" in s.ozet()


def test_fixtures_in_okur() -> None:
    src = (REPO / "demo-app/e2e/tests/fixtures.ts").read_text("utf-8")
    assert {"loginPage", "catalogPage", "cartPage", "orderPage"} <= checks.fixtures_in(src)
    assert checks.fixtures_in("const x = 1;") == set()


def test_sembol_tablosu_model_gorunumu() -> None:
    tablo = symbols().for_prompt()
    cart = next(p for p in tablo if p["class"] == "CartPage")
    assert {"name": "productCode", "type": "string"} in next(
        m["params"] for m in cart["methods"] if m["name"] == "expectLineQuantity"
    )
    assert all("file" not in v for v in cart["locators"].values())


def test_isaretli_ve_noktalamali_degerler_metin_araligiyla_eslesir() -> None:
    assert find_source(-5, ["stok -5 adet"]) == "stok -5 adet"
    assert find_source("7 adet sepete eklendi.", ['status "7 adet sepete eklendi."'])
    assert find_source("5-6", ["5-6 adet"]) == "5-6 adet"  # aralıktaki tire işaret değildir
    assert find_source("Demo123!", ["parola Demo123!"]) == "parola Demo123!"
    assert tokens("a (b)") == ["a", "(", "b", ")"]


# ------------------------------------------------------------- eşleme sırası


def _c3() -> tuple[dict[str, Any], dict[str, Any]]:
    return golden_case(3), golden_mapping(3)


def test_golden_eslemesi_sirali() -> None:
    case, out = _c3()
    assert checks.check_mapping(out, case, symbols(), fixtures=FIXTURES).ok


def test_ters_sirali_eslemesi_reddedilir() -> None:
    case, out = _c3()
    out = copy.deepcopy(out)
    out["step_mapping"].reverse()
    sonuc = checks.check_mapping(out, case, symbols(), fixtures=FIXTURES)
    assert not sonuc.ok and sonuc.engel_turu == "unverified_step"
    assert any("adım sırasına uymuyor" in b.mesaj for b in sonuc.bulgular)


def test_araya_giren_adim_reddedilir() -> None:
    case, out = _c3()
    out = copy.deepcopy(out)
    sm = out["step_mapping"]
    # S1, S2, S1 … : giriş sayfasına sonradan yeniden dönülmüş
    sm.insert(2, copy.deepcopy(sm[0]))
    sonuc = checks.check_mapping(out, case, symbols(), fixtures=FIXTURES)
    assert not sonuc.ok
    assert any("yeniden eşlenmiş" in b.mesaj for b in sonuc.bulgular)


def test_ayni_cagri_iki_kez_reddedilir() -> None:
    """S3 addToCart('P-001', 6) iki kez: sepette 12 olur ve assertion hatası defect sanılırdı."""
    case, out = _c3()
    out = copy.deepcopy(out)
    sm = out["step_mapping"]
    i = next(i for i, m in enumerate(sm) if m["method"] == "addToCart")
    sm.insert(i + 1, copy.deepcopy(sm[i]))
    sonuc = checks.check_mapping(out, case, symbols(), fixtures=FIXTURES)
    assert not sonuc.ok and sonuc.engel_turu == "unverified_step"
    assert any("art arda iki kez" in b.mesaj for b in sonuc.bulgular)


def test_adim_basina_cagri_siniri() -> None:
    case, out = _c3()
    out = copy.deepcopy(out)
    sm = out["step_mapping"]
    i = next(i for i, m in enumerate(sm) if m["method"] == "addToCart")
    ekler = []
    for n in range(checks.MAX_ADIM_CAGRI):
        m = copy.deepcopy(sm[i])
        m["args"] = ["P-001", n + 1]
        ekler.append(m)
    sm[i + 1 : i + 1] = ekler
    sonuc = checks.check_mapping(out, case, symbols(), fixtures=FIXTURES)
    assert any("çağrı eşlenmiş" in b.mesaj for b in sonuc.bulgular)
