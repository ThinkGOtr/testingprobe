"""`pages/kimlikler.py` saflığı ve TS `pages/**/locators.ts` ile testId/intent eşitliği."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.birim

KOK = Path(__file__).resolve().parents[2]
KIMLIKLER = KOK / "pages" / "kimlikler.py"
TS_PAGES = KOK.parent / "e2e" / "pages"
_TS_GRUP = re.compile(r"export const (\w+) = \{(.*?)\n\} as const;", re.S)
_TS_GIRDI = re.compile(r"^\s+(\w+): \{(.*)\},?$", re.M)
_TS_ALAN = re.compile(r'(\w+): "((?:[^"\\]|\\.)*)"')


def _sabit_str(d: ast.expr) -> bool:
    return isinstance(d, ast.Constant) and isinstance(d.value, str)


def py_kimlikler() -> dict[str, dict[str, dict[str, str]]]:
    return {
        n.targets[0].id: ast.literal_eval(n.value)  # type: ignore[union-attr]
        for n in ast.parse(KIMLIKLER.read_text(encoding="utf-8")).body
    }


def ts_kimlikler() -> dict[str, dict[str, dict[str, str]]]:
    out: dict[str, dict[str, dict[str, str]]] = {}
    for f in sorted(TS_PAGES.rglob("locators.ts")):
        for grup in _TS_GRUP.finditer(f.read_text(encoding="utf-8")):
            out[grup.group(1)] = {
                g.group(1): dict(_TS_ALAN.findall(g.group(2)))
                for g in _TS_GIRDI.finditer(grup.group(2))
            }
    return out


def test_saf_veri() -> None:
    """Yalnız üst düzey `AD = {str: {str: str}}` atamaları: içe aktarma, işlev, ifade yok."""
    for n in ast.parse(KIMLIKLER.read_text(encoding="utf-8")).body:
        assert isinstance(n, ast.Assign), f"satır {n.lineno}: yalnız atama olabilir"
        assert len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
        assert n.targets[0].id.isupper()
        assert isinstance(n.value, ast.Dict)
        for k, v in zip(n.value.keys, n.value.values, strict=True):
            assert k is not None and _sabit_str(k)
            assert isinstance(v, ast.Dict), f"satır {v.lineno}: girdi sözlük olmalı"
            assert all(a is not None and _sabit_str(a) for a in v.keys)
            assert all(_sabit_str(b) for b in v.values)


def test_ts_ile_esit() -> None:
    ts = ts_kimlikler()
    assert ts, "TS locators.ts okunamadı"
    py = py_kimlikler()
    assert set(py) == {ad.upper() for ad in ts}
    for ad, girdiler in ts.items():
        assert py[ad.upper()] == girdiler, ad
