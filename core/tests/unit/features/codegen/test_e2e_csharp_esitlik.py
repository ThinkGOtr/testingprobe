"""C# hedef projelerin PO eşitliği (014 Ş2, TASARIM §3 "PO eşitliği testi").

`symbols-csharp-web.json` ve `symbols-csharp-windows.json`, `toolchain/cs-araclar symbols` ile
`demo-app/e2e-csharp` ve `demo-app/e2e-app-csharp` üzerinde üretilmiş anlık görüntülerdir
(yenileme: README "Sembol anlık görüntüsü"). Bu test onları referans tablolara bağlar:

- web: TS tablosu (`symbols.json`) ↔ C#: sınıf aynı, metot `PascalCase + Async`, parametre adları ve
  sırası aynı, tür `string→string`, `number→int|double`, `boolean→boolean`;
- windows: Java uygulama tablosu (`symbols-java.json`) ↔ C#: metot `PascalCase` (eşzamanlı),
  parametre adları/sırası/türleri aynı.

Böylece REPLAY golden'ları (TS / Java adlarıyla) C# eklentisinin ad dönüşümüyle (`diller/csharp.py`
`metot_adi`) birebir C# çağrılarına düşer; render edilen her çağrı C# tablosunda vardır.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tp_core.features.codegen.diller import csharp as cs

from .test_checks import golden_mapping
from .test_platform import APP_GOLDEN

HERE = Path(__file__).resolve().parent


def _tablo(ad: str) -> dict[str, Any]:
    return json.loads((HERE / ad).read_text(encoding="utf-8"))


def _metotlar(tablo: dict[str, Any]) -> dict[tuple[str, str], list[tuple[str, str]]]:
    return {
        (po["class"], m["name"]): [(p["name"], p["type"]) for p in m["params"]]
        for po in tablo["page_objects"]
        for m in po["methods"]
    }


TS_TURU = {
    "string": {"string"},
    "String": {"string"},
    "number": {"int", "double", "long"},
    "int": {"int"},
    "long": {"long"},
    "double": {"double"},
    "boolean": {"boolean"},
}


def test_csharp_tablolari_hatasiz() -> None:
    for ad in ("symbols-csharp-web.json", "symbols-csharp-windows.json"):
        t = _tablo(ad)
        assert t["lang"] == "csharp" and t["errors"] == [], ad
        siniflar = {po["class"] for po in t["page_objects"]}
        assert set(t["fixtures"]) == siniflar, ad  # her PO'nun TestTabani erişimcisi var


def _web_esitligi(ref: dict[tuple[str, str], list[tuple[str, str]]], tam: bool) -> None:
    csm = _metotlar(_tablo("symbols-csharp-web.json"))
    beklenen = {(s, cs.metot_adi(m, "web")) for s, m in ref}
    if tam:
        assert set(csm) == beklenen
    else:
        assert beklenen <= set(csm), beklenen - set(csm)
    for (sinif, metot), params in ref.items():
        karsi = csm[(sinif, cs.metot_adi(metot, "web"))]
        assert [p for p, _ in karsi] == [p for p, _ in params], (sinif, metot)
        for (_, ref_tur), (_, cs_tur) in zip(params, karsi, strict=True):
            assert cs_tur in TS_TURU.get(ref_tur, {ref_tur}), (sinif, metot, ref_tur, cs_tur)


def test_web_java_web_tablosuyla_birebir() -> None:
    """e2e-java tablosu TS kaynağıyla birebirdir (`test_e2e_java_esitlik.py`); C# onunla birebir."""
    _web_esitligi(_metotlar(_tablo("symbols-java-web.json")), tam=True)


def test_web_ts_fikstur_tablosu_alt_kume() -> None:
    """REPLAY golden'larının TS tablosu (`symbols.json`, eski olabilir) C#'ta aynı imzayla var."""
    _web_esitligi(_metotlar(_tablo("symbols.json")), tam=False)


def test_windows_java_esitligi() -> None:
    java = _metotlar(_tablo("symbols-java.json"))
    csm = _metotlar(_tablo("symbols-csharp-windows.json"))
    assert set(csm) == {(s, cs.metot_adi(m, "windows")) for s, m in java}
    for (sinif, metot), params in java.items():
        karsi = csm[(sinif, cs.metot_adi(metot, "windows"))]
        assert [p for p, _ in karsi] == [p for p, _ in params], (sinif, metot)
        assert [t.lower() for _, t in karsi] == [t.lower() for _, t in params], (sinif, metot)


def test_windows_kimlikleri_java_ile_ayni() -> None:
    java = {k: v["testId"] for po in _tablo("symbols-java.json")["page_objects"]
            for k, v in po["locators"].items()}  # fmt: skip
    csk = {k: v["testId"] for po in _tablo("symbols-csharp-windows.json")["page_objects"]
           for k, v in po["locators"].items()}  # fmt: skip
    assert csk == java


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
def test_web_replay_eslemesi_csharp_tablosunda(n: int) -> None:
    tablo = _metotlar(_tablo("symbols-csharp-web.json"))
    m = golden_mapping(n)
    for item in [*m["step_mapping"], *m["expects"]]:
        anahtar = (cs.erisimci_adi(item["po"]), cs.metot_adi(item["method"], "web"))
        assert anahtar in tablo, anahtar
        assert len(item["args"]) == len(tablo[anahtar]), anahtar


def test_windows_replay_eslemesi_csharp_tablosunda() -> None:
    tablo = _metotlar(_tablo("symbols-csharp-windows.json"))
    m = APP_GOLDEN["output"]
    for item in [*m["step_mapping"], *m["expects"]]:
        anahtar = (cs.erisimci_adi(item["po"]), cs.metot_adi(item["method"], "windows"))
        assert anahtar in tablo, anahtar
        assert len(item["args"]) == len(tablo[anahtar]), anahtar
