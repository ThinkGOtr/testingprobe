"""Constitution X: prompt paketlerinin canlı değerlendirme durumu (`rules/evaluations.yaml`)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml

from tests.unit.gateway.demo_sources import RULES
from tp_core.gateway.errors import GatewayConfigError
from tp_core.gateway.evaluation import (
    PENDING_LABEL,
    blocking,
    evaluation_status,
    evaluation_statuses,
    load_evaluations,
    main,
    prompt_versions,
)


@pytest.fixture
def rules_copy(tmp_path: Path) -> Path:
    dst = tmp_path / "rules"
    dst.mkdir()
    shutil.copytree(RULES / "prompts", dst / "prompts")
    shutil.copy(RULES / "evaluations.yaml", dst / "evaluations.yaml")
    return dst


def _set(rules_dir: Path, bundle: str, **entry) -> None:
    path = rules_dir / "evaluations.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["bundles"][bundle] = entry
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


# --- Gerçek rules/ ---------------------------------------------------------------------------


def test_every_prompt_bundle_has_a_current_evaluation_record() -> None:
    statuses = evaluation_statuses(RULES)
    assert set(statuses) == set(prompt_versions(RULES))
    stale_or_missing = [s.bundle_id for s in statuses.values() if s.status in ("stale", "missing")]
    assert not stale_or_missing, f"evaluations.yaml güncellenmedi: {stale_or_missing}"


def test_verify_and_map_v3_is_pending_live_evaluation_without_waiver() -> None:
    """Faz 3 bulgusu: v3 + yeniden kaydedilen golden'lar canlı modelle değerlendirilmedi ve onaylı
    istisna yok. Golden'larda `recording` (canlı kayıt üst verisi) olunca bu test güncellenir."""
    st = evaluation_status(RULES, "verify-and-map")
    assert st.prompt_version == 3
    goldens = sorted((RULES / "replay" / "verify_and_map" / "golden").rglob("*.json"))
    assert goldens
    live = [p for p in goldens if '"recording"' in p.read_text(encoding="utf-8")]
    if not live:
        assert st.status == "pending"
        assert st.label == PENDING_LABEL
        assert not st.mergeable


def test_no_waiver_is_recorded_without_owner_approval() -> None:
    """İstisna yalnızca sahip onayıyla yazılır; bugün depoda onaylı istisna yoktur."""
    raw = load_evaluations(RULES)
    assert all(r["status"] != "waived" for r in raw.values())


def test_readme_status_table_matches_manifest() -> None:
    readme = (RULES / "README.md").read_text(encoding="utf-8")
    statuses = evaluation_statuses(RULES)
    for st in statuses.values():
        row = re.search(
            rf"^\| `{re.escape(st.bundle_id)}`[^|]*\| v(\d+) \| (.+) \|$", readme, re.MULTILINE
        )
        assert row, f"rules/README.md canlı değerlendirme tablosunda {st.bundle_id} satırı yok"
        assert int(row.group(1)) == st.prompt_version
        assert st.label in row.group(2)
    assert "evaluations.yaml" in readme


def test_merge_gate_reports_pending_bundles(capsys) -> None:
    code = main(["--rules-dir", str(RULES), "--check"])
    pending = blocking(RULES)
    assert code == (1 if pending else 0)
    out = capsys.readouterr()
    assert "verify-and-map@v3" in out.out
    if pending:
        assert "Constitution X" in out.err


# --- Kurallar (geçici kopya) -----------------------------------------------------------------


def test_version_bump_without_record_update_is_stale(rules_copy: Path) -> None:
    _set(rules_copy, "verify-and-map", version=2, status="pending")
    st = evaluation_status(rules_copy, "verify-and-map")
    assert st.status == "stale" and not st.mergeable


def test_missing_record_blocks_merge(rules_copy: Path) -> None:
    (rules_copy / "prompts" / "yeni-paket.md").write_text(
        "---\nid: yeni-paket\nversion: 1\n---\nx\n", encoding="utf-8"
    )
    st = evaluation_status(rules_copy, "yeni-paket")
    assert st.status == "missing"
    assert main(["--rules-dir", str(rules_copy), "--check"]) == 1


def test_waiver_requires_approver_date_reason_and_until(rules_copy: Path) -> None:
    _set(rules_copy, "verify-and-map", version=3, status="waived", waiver={"reason": "demo"})
    with pytest.raises(GatewayConfigError, match=r"waiver\.approved_by"):
        load_evaluations(rules_copy)
    _set(
        rules_copy,
        "verify-and-map",
        version=3,
        status="waived",
        waiver={"approved_by": "Sahip", "approved_at": "dün", "reason": "r", "until": "u"},
    )
    with pytest.raises(GatewayConfigError, match="YYYY-MM-DD"):
        load_evaluations(rules_copy)


def test_evaluated_requires_dated_results(rules_copy: Path) -> None:
    evaluation = {"date": "2026-11-01"}
    _set(rules_copy, "verify-and-map", version=3, status="evaluated", evaluation=evaluation)
    with pytest.raises(GatewayConfigError, match=r"evaluation\.model"):
        load_evaluations(rules_copy)


def test_pending_cannot_carry_waiver(rules_copy: Path) -> None:
    _set(rules_copy, "verify-and-map", version=3, status="pending", waiver={"approved_by": "x"})
    with pytest.raises(GatewayConfigError, match="pending"):
        load_evaluations(rules_copy)


def test_unknown_status_and_orphan_record_rejected(rules_copy: Path) -> None:
    _set(rules_copy, "verify-and-map", version=3, status="ok")
    with pytest.raises(GatewayConfigError, match="status"):
        load_evaluations(rules_copy)
    _set(rules_copy, "verify-and-map", version=3, status="pending")
    _set(rules_copy, "silinmis-paket", version=1, status="pending")
    with pytest.raises(GatewayConfigError, match="silinmis-paket"):
        evaluation_statuses(rules_copy)


def test_gate_opens_only_when_every_bundle_is_evaluated_or_waived(rules_copy: Path) -> None:
    for bundle_id, version in prompt_versions(rules_copy).items():
        _set(
            rules_copy,
            bundle_id,
            version=version,
            status="evaluated",
            evaluation={
                "date": "2026-11-01",
                "model": "claude-sonnet-5-5",
                "provider": "anthropic",
                "results": "docs/outcome/eval.md",
            },
        )
    assert blocking(rules_copy) == []
    assert main(["--rules-dir", str(rules_copy), "--check"]) == 0
    _set(
        rules_copy,
        "verify-and-map",
        version=3,
        status="waived",
        waiver={
            "approved_by": "Sahip",
            "approved_at": "2026-11-02",
            "reason": "kimlik bilgisi yok",
            "until": "ilk canlı koşu",
        },
    )
    st = evaluation_status(rules_copy, "verify-and-map")
    assert st.status == "waived" and st.mergeable and st.detail["approved_by"] == "Sahip"
    assert main(["--rules-dir", str(rules_copy), "--check"]) == 0


def test_missing_manifest_is_config_error(tmp_path: Path) -> None:
    (tmp_path / "prompts").mkdir()
    with pytest.raises(GatewayConfigError, match=r"evaluations\.yaml"):
        load_evaluations(tmp_path)
    assert main(["--rules-dir", str(tmp_path)]) == 2
