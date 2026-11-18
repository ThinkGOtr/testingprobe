"""rules/ci-sablonlari/xcresult_junit.py: xcresult JSON → JUnit (bağımlılıksız betik)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tp_core.features import musteri_ci as mci
from tp_core.features.ci.parse import parse_junit

BETIK = Path(__file__).resolve().parents[5] / "rules" / "ci-sablonlari" / "xcresult_junit.py"


@pytest.fixture(scope="module")
def xj():
    spec = importlib.util.spec_from_file_location("xcresult_junit", BETIK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ORNEK = {
    "devices": [{"deviceName": "iPhone 16"}],
    "testNodes": [
        {
            "name": "Bayi",
            "nodeType": "Test Plan",
            "result": "Failed",
            "children": [
                {
                    "name": "BayiUITests",
                    "nodeType": "UI test bundle",
                    "children": [
                        {
                            "name": "GirisTests",
                            "nodeType": "Test Suite",
                            "children": [
                                {
                                    "name": "testGiris()",
                                    "nodeType": "Test Case",
                                    "nodeIdentifier": "GirisTests/testGiris()",
                                    "result": "Passed",
                                    "durationInSeconds": 3.25,
                                },
                                {
                                    "name": "testHataliSifre()",
                                    "nodeType": "Test Case",
                                    "result": "Failed",
                                    "duration": "1m 2s",
                                    "children": [
                                        {
                                            "nodeType": "Failure Message",
                                            "name": "GirisTests.swift:20: XCTAssertTrue failed",
                                        }
                                    ],
                                },
                                {
                                    "name": "testAtla()",
                                    "nodeType": "Test Case",
                                    "result": "Skipped",
                                    "duration": "250ms",
                                },
                                {
                                    "name": "testBeklenen()",
                                    "nodeType": "Test Case",
                                    "result": "Expected Failure",
                                },
                            ],
                        }
                    ],
                }
            ],
        }
    ],
}


@pytest.mark.parametrize(
    ("dugum", "sn"),
    [
        ({"durationInSeconds": 1.5}, 1.5),
        ({"duration": "2.5s"}, 2.5),
        ({"duration": "1m 2s"}, 62.0),
        ({"duration": "250ms"}, 0.25),
        ({"duration": "0,5s"}, 0.5),
        ({"duration": "3"}, 3.0),
        ({"duration": "?"}, 0.0),
        ({}, 0.0),
    ],
)
def test_sure(xj, dugum, sn):
    assert xj.sure_saniye(dugum) == pytest.approx(sn)


def test_junit_donusumu_tp_ayristiricisiyla_okunur(xj, tmp_path):
    girdi = tmp_path / "t.json"
    girdi.write_text(json.dumps(ORNEK), encoding="utf-8")
    cikti = tmp_path / "junit" / "xcresult-junit.xml"
    assert xj.main(["--json", str(girdi), "--cikti", str(cikti)]) == 0
    satirlar = {t.test_adi: t for t in parse_junit(cikti.read_bytes())}
    assert set(satirlar) == {"testGiris", "testHataliSifre", "testAtla", "testBeklenen"}
    assert satirlar["testGiris"].sonuc == "passed" and satirlar["testGiris"].sure_ms == 3250
    assert satirlar["testGiris"].dosya == "BayiUITests.GirisTests"
    assert satirlar["testHataliSifre"].sonuc == "failed"
    assert "XCTAssertTrue failed" in satirlar["testHataliSifre"].hata_mesaji
    assert satirlar["testAtla"].sonuc == "skipped"
    assert satirlar["testBeklenen"].sonuc == "passed"
    # tp-results düzeninde müşteri CI ayrıştırması
    s = mci.tp_results_ayristir({"junit/xcresult-junit.xml": cikti.read_bytes()}, "ios", "swift")
    assert s.sayac == {"toplam": 4, "gecen": 2, "basarisiz": 1, "flaky": 0, "atlanan": 1}


def test_xcresult_yoksa_sessiz_cikar(xj, tmp_path):
    cikti = tmp_path / "j.xml"
    assert xj.main(["--xcresult", str(tmp_path / "yok.xcresult"), "--cikti", str(cikti)]) == 0
    assert not cikti.exists()
    assert (
        xj.main(["--xcresult", str(tmp_path / "yok.xcresult"), "--cikti", str(cikti), "--siki"])
        == 2
    )


def test_bozuk_json(xj, tmp_path):
    g = tmp_path / "b.json"
    g.write_text("{", encoding="utf-8")
    assert xj.main(["--json", str(g), "--cikti", str(tmp_path / "j.xml")]) == 0
    assert xj.main(["--json", str(g), "--cikti", str(tmp_path / "j.xml"), "--siki"]) == 2


def test_kontrol_karakterleri_temizlenir(xj):
    veri = {
        "testNodes": [
            {
                "nodeType": "Test Case",
                "name": "testX()",
                "result": "Failed",
                "children": [{"nodeType": "Failure Message", "name": "kötü\x01mesaj"}],
            }
        ]
    }
    satir = parse_junit(xj.junit_xml(xj.testleri_topla(veri)))[0]
    assert satir.hata_mesaji == "kötümesaj" and satir.dosya == "XCUITest"


def test_betik_bagimliliksiz():
    import ast

    agac = ast.parse(BETIK.read_text(encoding="utf-8"))
    modul = set()
    for n in ast.walk(agac):
        if isinstance(n, ast.Import):
            modul |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            modul.add((n.module or "").split(".")[0])
    import sys

    assert modul <= set(sys.stdlib_module_names) | {"__future__"}
