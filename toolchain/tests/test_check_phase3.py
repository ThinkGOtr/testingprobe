"""Faz 3 `/check`: üretilen testler (tests/generated), local-ci kayıt kuralı, triage girdileri."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import Forge, requires_ast_guard, requires_e2e_node_modules, requires_node
from tests.test_check import RUN_OK, _calls, _localforge_parse, fake_tools, runner_client
from toolchain_common.settings import settings
from worker import check as checks
from worker.app import app

GEN = "tests/generated/tpd-1-c1.spec.ts"

# demo-app/e2e/tools/generated-lint-selftest.js "sablon-oturumlu" ile aynı biçim (şablon çıktısı).
GENERATED_OK = (
    'import { signedInTest as test } from "../fixtures";\n'
    "\n"
    'test.describe("TPD-1 · 7 adet Portakal Gazozu → 1 adet bedava", () => {\n'
    '  test("TPD-1 · c1", async ({ catalogPage, cartPage }) => {\n'
    "    await catalogPage.goto();\n"
    '    await catalogPage.addToCart("P-001", 7);\n'
    "    await catalogPage.openCart();\n"
    '    await cartPage.expectFreeQuantity("P-001", 1);\n'
    "  });\n"
    "});\n"
)

FAILURE = {
    "id": "x-1",
    "title": "TPD-1 · 6 adet › bedava yok",
    "file": "generated/tpd-1-c2.spec.ts",
    "line": 4,
    "tags": ["@TPD-1"],
    "status": "unexpected",
    "attempts": 3,
    "attempt_results": [],
    "failure": {"type": "assertion", "expected": '"0"', "received": '"1"'},
}
SAGLIK = {"ok": True, "zaman": "2026-10-31T00:00:00+00:00", "web": {}, "api": {}, "hata": None}


def _execute(**kw: Any) -> tuple[dict[str, Any], list]:
    client, calls = runner_client(kw.pop("response", None))
    return checks.execute(settings(), checks.CheckRequest(**kw), runner_client=client), calls


# ------------------------------------------------------------------ local-ci kayıt kuralı


def test_scoped_check_is_not_recorded_by_default(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    head = forge.commit("tp/case-c1", {f"e2e/{GEN}": "// üretildi\n"})
    report, calls = _execute(sha=head, test_files=[GEN], repeat_each=3)
    assert report["conclusion"] == "success"
    assert report["check_recorded"] is False and report["checks_path"] is None
    assert report["kapsam"] == {
        "tam": False,
        "test_files": [GEN],
        "grep": None,
        "repeat_each": 3,
        "retries": 0,
        "break_campaign": False,
    }
    assert not (env / "checks").exists()
    assert calls[0]["body"]["test_files"] == [GEN]

    # grep de kapsamı daraltır
    report, _ = _execute(sha=head, grep="@TPD-1")
    assert report["check_recorded"] is False

    # Tam kapsam (dosya/grep yok) = PR CI'ının yerel karşılığı → kaydedilir.
    report, _ = _execute(sha=head, retries=1, repeat_each=1)
    assert report["check_recorded"] is True and report["kapsam"]["tam"] is True
    assert _localforge_parse(env / "checks" / f"{head}.json") == [
        {"name": "local-ci", "status": "completed", "conclusion": "success", "url": None}
    ]


def test_record_check_false_never_writes(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    report, _ = _execute(sha=forge.main, record_check=False)
    assert report["check_recorded"] is False
    assert not (env / "checks").exists()


def test_break_with_record_check_true_is_never_recorded(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    report, _ = _execute(
        sha=forge.main, break_campaign=True, record_check=True, response={**RUN_OK}
    )
    assert report["check_recorded"] is False
    assert not (env / "checks").exists()


def test_api_rejects_record_check_with_break(env: Path, forge: Forge) -> None:
    client = TestClient(app)
    for body in (
        {"sha": forge.main, "break": True, "record_check": True},
        {"sha": forge.main, "env": {"BREAK_CAMPAIGN": "1"}, "record_check": True},
    ):
        resp = client.post("/check", json=body)
        assert resp.status_code == 422, resp.text
        assert "local-ci" in resp.json()["detail"]


# ------------------------------------------------------------------ üretilen test dosyaları


def test_missing_test_file_fails_before_tools(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    report, calls = _execute(sha=forge.main, test_files=[GEN])
    assert report["failed_steps"] == ["deps"]
    assert report["deps"]["missing_test_files"] == [GEN]
    assert "commit'te yok" in report["deps"]["error"]
    assert _calls(tmp_path) == [] and calls == []
    # Kapsamlı kontrol kapıya yazılmaz (başarısız olsa da).
    assert report["check_recorded"] is False
    assert not (env / "checks").exists()


def test_api_accepts_nested_generated_paths_and_rejects_escape(env: Path, forge: Forge) -> None:
    client = TestClient(app)
    for bad in ("tests/generated/../x.spec.ts", "/abs.spec.ts", "tests/generated/x.ts", "-x"):
        resp = client.post("/check", json={"sha": forge.main, "test_files": [bad]})
        assert resp.status_code == 422, bad


# ------------------------------------------------------------- triage girdileri üst düzeyde


def test_failures_and_saglik_are_lifted_to_report(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    run = {
        **RUN_OK,
        "status": "failed",
        "saglik": SAGLIK,
        "failures": [FAILURE],
        "tests": [
            {"status": "unexpected"},
            {"status": "expected"},
            {"status": "flaky"},
        ],
    }
    report, calls = _execute(sha=forge.main, response=run, keep=True)
    assert report["conclusion"] == "failure" and report["failed_steps"] == ["run"]
    assert report["saglik"] == SAGLIK
    assert report["failures"] == [FAILURE]
    assert report["test_counts"] == {
        "toplam": 3,
        "expected": 1,
        "unexpected": 1,
        "flaky": 1,
        "skipped": 0,
    }
    assert calls[0]["body"]["keep"] is True
    # checks dosyasındaki rapor da aynı girdileri taşır (core oradan da okuyabilir)
    doc = json.loads((env / "checks" / f"{forge.main}.json").read_text())
    assert doc["report"]["failures"][0]["failure"]["type"] == "assertion"


def test_saglik_failure_is_reported_as_environment_input(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path)))
    bad = {**SAGLIK, "ok": False, "hata": "Demo uygulaması sağlık kontrolü başarısız — web"}
    report, _ = _execute(
        sha=forge.main,
        response={**RUN_OK, "status": "error", "saglik": bad, "tests": [], "failures": []},
    )
    assert report["saglik"]["ok"] is False
    assert report["failures"] == []
    assert report["conclusion"] == "failure"


def test_static_failure_has_null_saglik(
    env: Path, forge: Forge, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_NODE", str(fake_tools(tmp_path, tsc_exit=2)))
    report, _ = _execute(sha=forge.main)
    assert report["saglik"] is None and report["failures"] == []
    assert report["test_counts"]["toplam"] == 0


# --------------------------------------------- gerçek tsc/eslint: tests/generated kapsanıyor


def test_e2e_tsconfig_and_eslint_cover_generated_dir() -> None:
    """Üretilen testlerin yeri e2e tsconfig'ine dahil, ESLint'te yok sayılmıyor (statik)."""
    from tests.conftest import DEMO_E2E

    tsconfig = json.loads((DEMO_E2E / "tsconfig.json").read_text(encoding="utf-8"))
    assert "tests/**/*.ts" in tsconfig["include"]
    eslint = (DEMO_E2E / "eslint.config.js").read_text(encoding="utf-8")
    ignores = eslint.split("ignores:", 1)[1].split("]", 1)[0]
    assert "tests" not in ignores and "generated" not in ignores


@requires_node
@requires_e2e_node_modules
@requires_ast_guard
def test_real_tools_compile_and_lint_generated_tests(
    env: Path, forge: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gerçek tsc/eslint/ast-guard (pr, base = main) tests/generated/ altındaki dosyayı görür."""
    monkeypatch.setenv("TP_NODE", "node")
    ok = forge.commit("tp/case-c1", {f"e2e/{GEN}": GENERATED_OK})
    report, calls = _execute(sha=ok, test_files=[GEN], repeat_each=3)
    assert report["tsc"]["ok"], report["tsc"]
    assert report["eslint"]["ok"], report["eslint"]
    assert report["ast_guard"]["ok"], report["ast_guard"]
    assert report["ast_guard"]["base_sha"] == forge.main and report["ast_guard"]["mode"] == "pr"
    assert calls[0]["body"]["repeat_each"] == 3 and calls[0]["body"]["test_files"] == [GEN]

    # Tür hatası (string yerine sayı beklenen argüman) üretilen dosyada tsc'ye takılır.
    bad_type = forge.commit(
        "tp/case-c2",
        {
            f"e2e/{GEN}": GENERATED_OK.replace(
                'expectFreeQuantity("P-001", 1)', "expectFreeQuantity(1, 1)"
            )
        },
    )
    report, _ = _execute(sha=bad_type, test_files=[GEN])
    assert report["failed_steps"] == ["tsc"]
    assert any(d["file"] == GEN for d in report["tsc"]["diagnostics"]), report["tsc"]

    # Ham `page` erişimi üretilen testte ESLint'e takılır (tsc geçer).
    raw_page = forge.commit(
        "tp/case-c3",
        {
            f"e2e/{GEN}": GENERATED_OK.replace(
                "async ({ catalogPage, cartPage })", "async ({ page, catalogPage, cartPage })"
            ).replace("    await catalogPage.goto();\n", '    await page.goto("/");\n')
        },
    )
    report, _ = _execute(sha=raw_page, test_files=[GEN])
    assert report["failed_steps"] == ["eslint"], report["tsc"]
    assert any(m["file"] == GEN for m in report["eslint"]["messages"]), report["eslint"]
