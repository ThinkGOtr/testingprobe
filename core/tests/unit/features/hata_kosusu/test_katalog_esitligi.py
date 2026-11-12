"""Ürün kataloğu (`rules/hata-katalogu.yaml`) ile demo uygulama kataloğu aynı mı (ANALIZ §4.6).

Demo uygulama ayrı bir pakettir ve core'a bağımlılık olarak eklenmez; kataloğu kaynak dosyadan
(`demo-app/api/src/demoapp_api/faults.py`) çalıştırmadan, sözdizim ağacıyla okunur.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tp_core.features.hata_kosusu.katalog import katalog

KOK = Path(__file__).resolve().parents[5]
FAULTS = KOK / "demo-app" / "api" / "src" / "demoapp_api" / "faults.py"


def _demo_katalogu() -> dict[str, str]:
    agac = ast.parse(FAULTS.read_text(encoding="utf-8"))
    sabitler: dict[str, str] = {}
    for dugum in agac.body:
        hedef = dugum.target if isinstance(dugum, ast.AnnAssign) else None
        if isinstance(dugum, ast.Assign) and len(dugum.targets) == 1:
            hedef = dugum.targets[0]
        deger = getattr(dugum, "value", None)
        if (
            isinstance(hedef, ast.Name)
            and isinstance(deger, ast.Constant)
            and isinstance(deger.value, str)
        ):
            sabitler[hedef.id] = deger.value

    def coz(d: ast.expr) -> str:
        if isinstance(d, ast.Constant) and isinstance(d.value, str):
            return d.value
        if isinstance(d, ast.Name) and d.id in sabitler:
            return sabitler[d.id]
        raise AssertionError(f"çözülemeyen değer: {ast.dump(d)}")

    sonuc: dict[str, str] = {}
    for dugum in ast.walk(agac):
        if (
            isinstance(dugum, ast.Call)
            and isinstance(dugum.func, ast.Name)
            and dugum.func.id == "Hata"
        ):
            alanlar = {k.arg: k.value for k in dugum.keywords if k.arg}
            konumsal = list(dugum.args)
            kod = coz(alanlar["kod"] if "kod" in alanlar else konumsal[0])
            tur = coz(alanlar["tur"] if "tur" in alanlar else konumsal[1])
            sonuc[kod] = tur
    return sonuc


@pytest.mark.skipif(not FAULTS.exists(), reason="demo-app kaynağı yok")
def test_urun_ve_demo_katalogu_ayni():
    demo = _demo_katalogu()
    urun = {h["kod"]: h["tur"] for h in katalog()}
    assert len(demo) == 9
    assert demo == urun
