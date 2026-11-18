"""`ekranlar/kimlikler.py` saflığı ve Java `ekranlar/Kimlikler.java` ile kimlik eşitliği."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.birim

KOK = Path(__file__).resolve().parents[2]
KIMLIKLER = KOK / "ekranlar" / "kimlikler.py"
JAVA = (KOK.parent / "e2e-app" / "src" / "test" / "java" / "com" / "antreklabs" / "bayi"
        / "ekranlar" / "Kimlikler.java")  # fmt: skip
_JAVA_SINIF = re.compile(r"public static final class (\w+) \{(.*?)\n  \}", re.S)
_JAVA_SABIT = re.compile(r'public static final String (\w+) = "([^"]*)";')


def _sabit_str(d: ast.expr | None) -> bool:
    return isinstance(d, ast.Constant) and isinstance(d.value, str)


def test_saf_veri() -> None:
    for n in ast.parse(KIMLIKLER.read_text(encoding="utf-8")).body:
        assert isinstance(n, ast.Assign), f"satır {n.lineno}: yalnız atama olabilir"
        assert len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
        assert n.targets[0].id.isupper()
        assert isinstance(n.value, ast.Dict)
        for k, v in zip(n.value.keys, n.value.values, strict=True):
            assert _sabit_str(k) and isinstance(v, ast.Dict)
            assert all(_sabit_str(a) for a in v.keys) and all(_sabit_str(b) for b in v.values)
            assert set(ast.literal_eval(v)) == {"testId", "intent"}


def test_java_ile_esit() -> None:
    java = {
        m.group(1).upper(): dict(_JAVA_SABIT.findall(m.group(2)))
        for m in _JAVA_SINIF.finditer(JAVA.read_text(encoding="utf-8"))
    }
    assert java, "Kimlikler.java okunamadı"
    py = {
        n.targets[0].id: {k: v["testId"] for k, v in ast.literal_eval(n.value).items()}
        for n in ast.parse(KIMLIKLER.read_text(encoding="utf-8")).body
    }
    assert py == java
