"""PO eşitliği (TASARIM §3, 011 §2.5 deseni): Python page object'leri TS page object'leriyle
birebir aynı metot kümesini taşır (ad kuralı: snake_case). Tarayıcısız; playwright içe aktarılmaz
(kaynak `ast` ile okunur). REPLAY golden'ları dilden bağımsız kalır: TS tablosuna eşlenen adım
Python'da `snake_case(ad)` ile aynı metodu bulur."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.birim

KOK = Path(__file__).resolve().parents[2]
TS_PAGES = KOK.parent / "e2e" / "pages"
PY_PAGES = KOK / "pages"
# core render.snake_case ile aynı kural (`_DEVE_SINIRI`).
_DEVE_SINIRI = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_TS_SINIF = re.compile(r"export class (\w+)")
_TS_METOT = re.compile(r"^\s+async (\w+)\(", re.M)


def snake_case(ad: str) -> str:
    return _DEVE_SINIRI.sub("_", ad).lower()


def ts_tablosu() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in sorted(TS_PAGES.rglob("*.page.ts")):
        kaynak = f.read_text(encoding="utf-8")
        m = _TS_SINIF.search(kaynak)
        assert m, f"{f}: sınıf yok"
        out[m.group(1)] = set(_TS_METOT.findall(kaynak))
    return out


def py_tablosu() -> dict[str, tuple[str, set[str]]]:
    """sınıf → (modül adı, public metotlar)."""
    out: dict[str, tuple[str, set[str]]] = {}
    for f in sorted(PY_PAGES.glob("*.py")):
        agac = ast.parse(f.read_text(encoding="utf-8"))
        for dugum in agac.body:
            if isinstance(dugum, ast.ClassDef):
                metotlar = {
                    n.name
                    for n in dugum.body
                    if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
                }
                out[dugum.name] = (f.stem, metotlar)
    return out


def test_ts_kaynagi_var() -> None:
    assert TS_PAGES.is_dir(), f"TS page object dizini yok: {TS_PAGES}"
    assert len(ts_tablosu()) >= 4


def test_sinif_kumesi_esit() -> None:
    assert set(py_tablosu()) == set(ts_tablosu())


def test_modul_adi_snake_case_sinif_adi() -> None:
    """Şablon `from pages.<snake_case(Sınıf)> import <Sınıf>` yazar."""
    for sinif, (modul, _) in py_tablosu().items():
        assert modul == snake_case(sinif), sinif


@pytest.mark.parametrize("sinif", sorted(ts_tablosu()))
def test_metot_kumesi_esit(sinif: str) -> None:
    beklenen = {snake_case(m) for m in ts_tablosu()[sinif]}
    _, gercek = py_tablosu()[sinif]
    assert gercek == beklenen, (
        f"{sinif}: eksik {sorted(beklenen - gercek)}, fazla {sorted(gercek - beklenen)}"
    )


def test_parametre_turleri_izinli() -> None:
    """Public metot parametreleri yalnız str | int | float | bool (sembol tablosu sözleşmesi)."""
    izinli = {"str", "int", "float", "bool"}
    for f in sorted(PY_PAGES.glob("*_page.py")):
        for dugum in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(dugum, ast.FunctionDef) and not dugum.name.startswith("_"):
                for arg in dugum.args.args[1:]:
                    tur = ast.unparse(arg.annotation) if arg.annotation else None
                    assert tur in izinli, f"{f.name}:{dugum.name}({arg.arg}: {tur})"
