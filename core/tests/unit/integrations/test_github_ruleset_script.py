"""scripts/github-ruleset.sh — kuru çalışma gövdesi (OPS-O3 tur 2, K-T10).

`--checks` listeyi değiştirir; `--add-checks` mevcut ruleset'in zorunlu check'lerini (platform
check'leri dahil) korur ve birleştirir. Testler yalnız kuru çalışmayı koşar (API çağrısı yok).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "scripts" / "github-ruleset.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("jq") is None, reason="bash / jq yok"
)

MEVCUT = {
    "id": 1,
    "name": "tp-main",
    "rules": [
        {"type": "deletion"},
        {
            "type": "required_status_checks",
            "parameters": {
                "required_status_checks": [
                    {"context": c, "integration_id": 15368}
                    for c in (
                        "test-local",
                        "ast-guard",
                        "semgrep",
                        "mobil-android",
                        "masaustu-windows",
                    )
                ]
            },
        },
    ],
}


def _kuru(*args: str) -> tuple[str, list[str]]:
    r = subprocess.run(
        ["bash", str(SCRIPT), "--repo", "o/r", *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    govde = r.stdout[r.stdout.index("{") :]
    kurallar = json.loads(govde)["rules"]
    rsc = next(k for k in kurallar if k["type"] == "required_status_checks")
    return r.stdout, [c["context"] for c in rsc["parameters"]["required_status_checks"]]


def test_varsayilan_liste() -> None:
    _, checks = _kuru()
    assert checks == ["test-local", "ast-guard", "semgrep"]


def test_add_checks_mevcut_platform_checklerini_korur(tmp_path: Path) -> None:
    f = tmp_path / "mevcut.json"
    f.write_text(json.dumps(MEVCUT))
    _, checks = _kuru("--add-checks", "web-java,semgrep", "--existing-json", str(f))
    assert checks == [
        "test-local",
        "ast-guard",
        "semgrep",
        "mobil-android",
        "masaustu-windows",
        "web-java",
    ]


def test_add_checks_mevcut_yoksa_kuru_calismada_uyarir() -> None:
    out, checks = _kuru("--add-checks", "web-java")
    assert checks == ["test-local", "ast-guard", "semgrep", "web-java"]
    assert "BİRLEŞTİRİLİR" in out
