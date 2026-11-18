"""PO eşitliği: Python ekran nesneleri Java e2e-app `ekranlar/` ile birebir aynı metot kümesini
taşır (ad kuralı: snake_case, `girisYap` → `giris_yap`). Cihazsız; appium içe aktarılmaz."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.birim

KOK = Path(__file__).resolve().parents[2]
JAVA_EKRANLAR = KOK.parent / "e2e-app" / "src" / "test" / "java" / "com" / "antreklabs" / "bayi" / "ekranlar"
PY_EKRANLAR = KOK / "ekranlar"
_DEVE_SINIRI = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_JAVA_SINIF = re.compile(r"public class (\w+) extends Ekran")
_JAVA_METOT = re.compile(r"public void (\w+)\(")


def snake_case(ad: str) -> str:
    return _DEVE_SINIRI.sub("_", ad).lower()


def java_tablosu() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in sorted(JAVA_EKRANLAR.glob("*.java")):
        kaynak = f.read_text(encoding="utf-8")
        m = _JAVA_SINIF.search(kaynak)
        if m:
            out[m.group(1)] = set(_JAVA_METOT.findall(kaynak))
    return out


def py_tablosu() -> dict[str, tuple[str, set[str]]]:
    out: dict[str, tuple[str, set[str]]] = {}
    for f in sorted(PY_EKRANLAR.glob("*.py")):
        for dugum in ast.parse(f.read_text(encoding="utf-8")).body:
            if isinstance(dugum, ast.ClassDef) and dugum.name != "Ekran":
                out[dugum.name] = (
                    f.stem,
                    {n.name for n in dugum.body
                     if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")},
                )  # fmt: skip
    return out


def test_java_kaynagi_var() -> None:
    assert len(java_tablosu()) >= 5, JAVA_EKRANLAR


def test_sinif_kumesi_esit() -> None:
    assert set(py_tablosu()) == set(java_tablosu())


def test_modul_adi_snake_case_sinif_adi() -> None:
    for sinif, (modul, _) in py_tablosu().items():
        assert modul == snake_case(sinif), sinif


@pytest.mark.parametrize("sinif", sorted(java_tablosu()))
def test_metot_kumesi_esit(sinif: str) -> None:
    beklenen = {snake_case(m) for m in java_tablosu()[sinif]}
    _, gercek = py_tablosu()[sinif]
    assert gercek == beklenen, (
        f"{sinif}: eksik {sorted(beklenen - gercek)}, fazla {sorted(gercek - beklenen)}"
    )


def test_ekranlar_taban_sinifindan_turer() -> None:
    for f in sorted(PY_EKRANLAR.glob("*_ekrani.py")):
        for dugum in ast.parse(f.read_text(encoding="utf-8")).body:
            if isinstance(dugum, ast.ClassDef):
                assert [ast.unparse(b) for b in dugum.bases] == ["Ekran"], f.name
