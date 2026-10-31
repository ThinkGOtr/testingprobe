"""Başarısız test girdileri: gerçek Playwright 1.64.1 JSON raporu (tests/data) üzerinde.

`tests/data/pw_1_64_failures.json` gerçek bir koşunun çıktısıdır (mutlak yollar `{E2E}` ile
değiştirildi, stdout/stderr ve config kırpıldı). Her test bir hata biçimini üretir; Demo-B'nin
"6 adet → bedava yok" case'i page object `expect*` metodunda `toHaveText` uyuşmazlığıdır.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runner.results import FAILURE_TYPES, classify_error, failures_of, summarize

DATA = Path(__file__).parent / "data" / "pw_1_64_failures.json"
GEN = "tests/generated/tpd-1.spec.ts"


@pytest.fixture
def run(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Koşu dizini düzeni: <artifacts>/runs/r1/src/e2e/results/{results.json,artifacts/…}."""
    artifacts = tmp_path / "artifacts"
    dest = artifacts / "runs" / "r1"
    e2e = dest / "src" / "e2e"
    raw = DATA.read_text(encoding="utf-8").replace("{E2E}", str(e2e))
    results = e2e / "results"
    results.mkdir(parents=True)
    (results / "results.json").write_text(raw, encoding="utf-8")
    # Ekler: rapordaki yollarda dosya oluştur (trace/screenshot/error-context).
    for path in _attachment_paths(json.loads(raw)):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.name == "error-context.md":
            p.write_text(
                "# Test info\n\n# Page snapshot\n\n```yaml\n"
                '- main:\n  - button "Sepete ekle" [ref=e4]\n```\n',
                encoding="utf-8",
            )
        else:
            p.write_bytes(b"x")
    return artifacts, dest, e2e


def _attachment_paths(node: Any) -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        if "attachments" in node:
            out += [a["path"] for a in node["attachments"] if a.get("path")]
        for v in node.values():
            out += _attachment_paths(v)
    elif isinstance(node, list):
        for v in node:
            out += _attachment_paths(v)
    return out


def _by_title(run: tuple[Path, Path, Path]) -> dict[str, dict[str, Any]]:
    artifacts, dest, e2e = run
    s = summarize(e2e / "results" / "results.json", dest, e2e_dir=e2e, rel_root=artifacts)
    return {f["title"]: f for f in failures_of(s["tests"])}


EXPECTED_TYPES = {
    "TPD-1 › 6 adet → bedava yok": "assertion",
    "locator kırık": "locator_timeout",
    "expect bulunamadı": "locator_not_found",
    "görünür değil": "locator_not_found",
    "strict": "locator_ambiguous",
    "navigasyon": "navigation",
    "test zaman aşımı": "locator_timeout",
    "veri hazırlığı": "test_data",
    "diğer": "other",
    "değer": "assertion",
    "kararsız": "assertion",
}


def test_every_failure_type_from_real_report(run: tuple[Path, Path, Path]) -> None:
    fails = _by_title(run)
    assert {t: f["failure"]["type"] for t, f in fails.items()} == EXPECTED_TYPES
    assert set(EXPECTED_TYPES.values()) <= set(FAILURE_TYPES)
    assert "geçer" not in fails  # yeşil test listede yok


def test_demo_b_boundary_case_is_assertion_with_values_and_locations(
    run: tuple[Path, Path, Path],
) -> None:
    f = _by_title(run)["TPD-1 › 6 adet → bedava yok"]
    assert f["status"] == "unexpected" and f["tags"] == [
        "TPD-1",
        "case:c1",
    ]  # JSON raporu @ önekini atar
    x = f["failure"]
    assert x["matcher"] == "toHaveText"
    assert x["locator"] == "getByTestId('cart-line-free-P-001')"
    assert (x["expected"], x["received"]) == ('"0"', '"1"')
    assert x["timeout_ms"] == 1000
    # Hata page object'in expect metodunda; testteki çağrı satırı ayrıca verilir.
    assert x["location"] == {"file": "pages/cart.page.ts", "line": 5, "column": 65}
    assert x["test_location"] == {"file": GEN, "line": 5, "column": 20}
    assert x["step"] == {"title": "Beklenen: bedava adet 0", "path": ["Beklenen: bedava adet 0"]}
    assert "\x1b" not in x["message"] and x["message"].startswith("Error: expect(locator)")
    assert x["attempt"] == 0 and x["status"] == "failed"
    assert [a["type"] for a in f["attempt_results"]] == ["assertion", "assertion"]


def test_evidence_paths_inside_run_with_relative_paths(run: tuple[Path, Path, Path]) -> None:
    artifacts, dest, _ = run
    ev = _by_title(run)["locator kırık"]["failure"]["evidence"]
    for key in ("trace", "error_context", "screenshot"):
        item = ev[key]
        assert item["exists"] is True
        assert Path(item["path"]).is_relative_to(dest.resolve())
        assert (artifacts.resolve() / item["rel"]).resolve() == Path(item["path"])
        assert item["rel"].startswith("runs/r1/src/e2e/results/artifacts/")
    assert ev["trace"]["path"].endswith("trace.zip")
    assert ev["error_context"]["path"].endswith("error-context.md")
    assert ev["screenshot"]["path"].endswith(".png")
    assert ev["video"] is None
    f = _by_title(run)["locator kırık"]["failure"]
    assert f["aria_snapshot_scope"] == "page"
    assert 'button "Sepete ekle"' in f["aria_snapshot"]
    assert f["action"] == "locator.click" and f["locator"] == "getByTestId('add-to-cart')"
    assert f["step"]["title"] == "Adım 1: Sepete ekle"


def test_flaky_attempts_and_test_timeout(run: tuple[Path, Path, Path]) -> None:
    fails = _by_title(run)
    flaky = fails["kararsız"]
    assert flaky["status"] == "flaky"
    assert [(a["status"], a["type"]) for a in flaky["attempt_results"]] == [
        ("failed", "assertion"),
        ("passed", None),
    ]
    tt = fails["test zaman aşımı"]["failure"]
    assert tt["status"] == "timedOut"
    assert "test zaman aşımı" in tt["signals"]
    assert tt["locator"] == "getByRole('button', { name: 'Yok' })"
    assert tt["location"]["file"] == GEN  # errorLocation yokken errors[].location


def test_test_data_failure_located_in_fixture(run: tuple[Path, Path, Path]) -> None:
    f = _by_title(run)["veri hazırlığı"]["failure"]
    assert f["location"]["file"] == "tests/fixtures.ts"
    assert "POST /test/reset başarısız" in f["message"]


def test_evidence_outside_run_is_dropped(tmp_path: Path) -> None:
    result = {
        "status": "failed",
        "errors": [{"message": "Error: x"}],
        "attachments": [{"name": "trace", "path": "/etc/passwd"}],
    }
    from runner.results import failure_inputs

    out = failure_inputs(result, tmp_path, tmp_path, tmp_path)
    assert out["evidence"]["trace"] is None and out["type"] == "other"


_LOC_FILL = (
    "TimeoutError: locator.fill: Timeout 5000ms exceeded.\n"
    "Call log:\n  - waiting for getByTestId('qty')"
)
_NAV_TIMEOUT = (
    "Error: page.goto: Timeout 10000ms exceeded.\n"
    'Call log:\n  - navigating to "http://demo-app-web:8080/katalog"'
)
_URL = (
    "Error: expect(page).toHaveURL(expected) failed\n\n"
    'Expected pattern: /\\/siparis\\//\nReceived string: "http://x/sepet"'
)
_COUNT = (
    "Error: expect(locator).toHaveCount(expected) failed\n\n"
    "Locator: getByTestId('min-order-warning')\nExpected: 0\nReceived: 1"
)


@pytest.mark.parametrize(
    ("messages", "loc", "kind"),
    [
        ([_LOC_FILL], None, "locator_timeout"),
        ([_NAV_TIMEOUT], None, "navigation"),
        ([_URL], None, "assertion"),
        ([_COUNT], None, "assertion"),
        (["Error: DEMOAPP_TEST_TOKEN tanımlı değil; test verisi sıfırlanamaz."], None, "test_data"),
        (["Error: herhangi"], "tests/fixtures.ts", "test_data"),
        (["Test timeout of 20000ms exceeded."], None, "test_timeout"),
        ([""], None, "other"),
    ],
)
def test_classify_error_rules(messages: list[str], loc: str | None, kind: str) -> None:
    assert classify_error(messages, loc)["type"] == kind


def test_repeat_each_groups_consistent_assertion(tmp_path: Path) -> None:
    """Gerçek `--repeat-each=3` raporu: her tekrar ayrı id; grup 3/3 assertion → tutarlı."""
    from runner.results import failure_groups

    e2e = tmp_path / "e2e"
    raw = (DATA.parent / "pw_1_64_repeat3.json").read_text(encoding="utf-8")
    p = tmp_path / "r.json"
    p.write_text(raw.replace("{E2E}", str(e2e)), encoding="utf-8")
    s = summarize(p, tmp_path, e2e_dir=e2e)
    assert [t["repeat_index"] for t in s["tests"]] == [0, 0, 1, 1, 2, 2]
    (g,) = failure_groups(s["tests"])
    assert g["title"] == "TPD-1 › 6 adet → bedava yok"
    assert g["repeats"] == 3 and len(set(g["ids"])) == 3
    assert g["statuses"] == {"unexpected": 3}
    assert g["types"] == ["assertion"] and g["consistent"] is True
    assert g["failure"]["expected"] == '"0"'


def test_mixed_repeats_are_not_consistent() -> None:
    from runner.results import failure_groups

    def t(status: str, kind: str | None) -> dict[str, Any]:
        return {
            "id": status,
            "title": "x",
            "file": "generated/a.spec.ts",
            "line": 3,
            "column": 5,
            "project": "chromium",
            "status": status,
            "failure": {"type": kind} if kind else None,
        }

    (g,) = failure_groups([t("unexpected", "assertion"), t("expected", None), t("expected", None)])
    assert g["statuses"] == {"unexpected": 1, "expected": 2} and g["consistent"] is False
    (g,) = failure_groups([t("unexpected", "assertion"), t("unexpected", "locator_timeout")])
    assert g["consistent"] is False and g["types"] == ["assertion", "locator_timeout"]
    assert failure_groups([t("expected", None)]) == []
