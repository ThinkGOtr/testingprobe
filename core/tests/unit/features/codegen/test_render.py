"""Şablon (Jinja2) — deterministik golden çıktı ve enjeksiyon güvenliği (§8.4 adım 4).

Golden'ı güncellemek (şablon bilinçli değiştiyse):
`TP_UPDATE_GOLDEN=1 uv run pytest tests/unit/features/codegen/test_render.py`.
"""

from __future__ import annotations

import copy
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

import pytest

from tp_core.audit import content_hash
from tp_core.features.codegen import render
from tp_core.features.codegen.render import RenderError, RenderInput

from .test_checks import RULES, golden_case, golden_mapping

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden"
CASE_ID = uuid.UUID("3f9b1c2e-0000-5000-8000-0000000000c2")
DEALERS = {
    "bayi1": {"password": "Demo123!", "name": "Merkez Bayi"},
    "bayi2": {"password": "Demo123!", "name": "Sahil Bayi"},
}


def girdi(n: int = 2, **over: Any) -> RenderInput:
    case = over.pop("case", golden_case(n))
    mapping = over.pop("mapping", golden_mapping(n))
    alanlar: dict[str, Any] = {
        "case_id": CASE_ID,
        "case": case,
        "sira_no": n,
        "story_key": "TPD-1",
        "test_key": "TPD-12",
        "case_hash": content_hash(case),
        "mode": "replay",
        "bundle_hash": "b" * 64,
        "mapping": mapping,
        "dealers": DEALERS,
    }
    alanlar.update(over)
    return RenderInput(**alanlar)


@pytest.mark.parametrize("n", [2, 5, 8])
def test_golden_cikti(n: int) -> None:
    r = render.render_test(girdi(n), RULES)
    hedef = GOLDEN / f"tpd-1-c{n}.spec.ts"
    if os.environ.get("TP_UPDATE_GOLDEN") == "1":
        hedef.write_text(r.content, encoding="utf-8")
    assert r.content == hedef.read_text(encoding="utf-8")
    assert r.repo_path == f"e2e/tests/generated/tpd-1-c{n}-3f9b1c2e.spec.ts"
    assert r.test_file == f"tests/generated/tpd-1-c{n}-3f9b1c2e.spec.ts"
    assert r.dealer == "bayi1"


def test_cikti_deterministik() -> None:
    a = render.render_test(girdi(), RULES)
    b = render.render_test(girdi(), RULES)
    assert a == b
    assert "AI-generated" in a.content and "b" * 64 in a.content
    assert f"Case: TPD-1-C2 ({CASE_ID})" in a.content and "Jira Test: TPD-12" in a.content


def test_sablon_sozlesmesi() -> None:
    """demo-app/e2e/eslint.config.js `tests/generated/**` kuralları (sözdizimsel)."""
    k = render.render_test(girdi(), RULES).content
    importlar = re.findall(r"^import .*$", k, re.M)
    assert importlar == ['import { test } from "../fixtures";']
    for yasak in ("page.", "expect(", "test.step", "process", "`", "if (", "for (", " new "):
        assert yasak not in k, yasak
    assert 'test.use({ dealerUsername: "bayi1" });' in k


def test_bayisiz_case_sabitlenmez() -> None:
    m = copy.deepcopy(golden_mapping(2))
    m["step_mapping"] = [s for s in m["step_mapping"] if s["method"] != "login"]
    r = render.render_test(girdi(mapping=m), RULES)
    assert r.dealer is None and "test.use" not in r.content


@pytest.mark.parametrize(
    "kotu",
    [
        'x"); process.exit(1); ("',
        "satır\nkırığı */ // ${evil} `tpl`",
        " ayırıcı ",
        "</script><img src=x>",
    ],
)
def test_degerler_yalniz_json_literal(kotu: str) -> None:
    case = copy.deepcopy(golden_case(5))
    m = copy.deepcopy(golden_mapping(5))
    case["title"] = kotu
    case["steps"][0]["action"] = kotu
    m["expects"][1]["args"] = [kotu]
    k = render.render_test(girdi(5, case=case, mapping=m), RULES).content
    beklenen = json.dumps(kotu, ensure_ascii=False).replace(" ", "\\u2028")
    beklenen = beklenen.replace(" ", "\\u2029")
    assert f"expectMinOrderWarning({beklenen});" in k
    # Yorum satırları tek satır: eylem metni yeni satır açamaz.
    for satir in k.splitlines():
        assert " " not in satir and " " not in satir
    yorum = next(s for s in k.splitlines() if s.strip().startswith("// S1"))
    assert "\n" not in yorum
    assert k.count("\n") == render.render_test(girdi(5), RULES).content.count("\n")


def test_gecersiz_tanimlayici_ve_deger_turu() -> None:
    m = copy.deepcopy(golden_mapping(2))
    m["expects"][0]["method"] = "expectTotal(); evil"
    with pytest.raises(RenderError):
        render.render_test(girdi(mapping=m), RULES)
    m = copy.deepcopy(golden_mapping(2))
    m["expects"][0]["args"] = [{"a": 1}]
    with pytest.raises(RenderError):
        render.render_test(girdi(mapping=m), RULES)
    with pytest.raises(RenderError):
        render.ts_literal(float("nan"))


def test_ts_literal() -> None:
    assert render.ts_literal('Şeftali "1L"') == '"Şeftali \\"1L\\""'
    assert render.ts_literal(7) == "7" and render.ts_literal(True) == "true"
    assert render.ts_literal("a b") == '"a\\u2028b"'


def test_parse_dealers_ve_slug() -> None:
    src = (RULES.parent / "demo-app/e2e/tests/fixtures.ts").read_text("utf-8")
    d = render.parse_dealers(src)
    assert d["bayi1"] == {"password": "Demo123!", "name": "Merkez Bayi"}
    assert "bayi3" not in d  # doğrulama ajanının bayisi e2e listesinde değil
    assert render.slug("TPD-1", 3, CASE_ID) == "tpd-1-c3-3f9b1c2e"
    assert render.slug("../x", 3, CASE_ID) == "serbest-c3-3f9b1c2e"
