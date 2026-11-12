"""scripts/github-ruleset.sh — kuru çalışma gövdesi (OPS-O3 tur 2, K-T10).

`--checks` listeyi değiştirir; `--add-checks` mevcut ruleset'in zorunlu check'lerini (platform
check'leri dahil) korur ve birleştirir; mevcut liste boşsa --checks taban alınır (OPS-D1);
--apply'da --existing-json yok sayılır (MİM-D8). API çağrısı yok: --apply testleri sahte `gh`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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


def _mevcut_rsc(checks: list[str] | None) -> dict[str, object]:
    kurallar: list[dict[str, object]] = [{"type": "deletion"}]
    if checks is not None:
        kurallar.append(
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [
                        {"context": c, "integration_id": 15368} for c in checks
                    ]
                },
            }
        )
    return {"id": 1, "name": "tp-main", "rules": kurallar}


@pytest.mark.parametrize("checks", [None, []], ids=["kural-yok", "liste-bos"])
def test_add_checks_mevcut_bos_ise_checks_tabani(tmp_path: Path, checks: list[str] | None) -> None:
    """OPS-D1: mevcut ruleset'te zorunlu check yoksa yalnız --add-checks yazılıp temel check'ler
    düşmez; --checks (varsayılan) taban alınır."""
    f = tmp_path / "mevcut.json"
    f.write_text(json.dumps(_mevcut_rsc(checks)))
    out, sonuc = _kuru("--add-checks", "web-java", "--existing-json", str(f))
    assert sonuc == ["test-local", "ast-guard", "semgrep", "web-java"]
    assert "zorunlu check içermiyor" in out
    _, sonuc = _kuru(
        "--checks",
        "test-local,mobil-android",
        "--add-checks",
        "web-java",
        "--existing-json",
        str(f),
    )
    assert sonuc == ["test-local", "mobil-android", "web-java"]


FAKE_GH = r"""
import json, os, sys
st = os.environ["FAKE_STATE"]
a = sys.argv[1:]
with open(os.path.join(st, "gh.log"), "a") as f:
    f.write(" ".join(a) + "\n")
yol = next((x for x in a if x.startswith(("orgs/", "repos/"))), "")
if yol.startswith("orgs/"):
    print("7")
elif "-X" in a:
    with open(os.path.join(st, "govde.json"), "w") as f:
        f.write(sys.stdin.read())
    print("güncellendi: tp-main (#1)")
elif yol.endswith("/rulesets"):
    print("1")
elif yol.endswith("/rulesets/1"):
    with open(os.path.join(st, "canli.json")) as f:
        print(f.read())
else:
    sys.exit(97)
"""


def _apply(tmp_path: Path, canli: dict[str, object], *args: str) -> tuple[str, list[str]]:
    """--apply: sahte `gh` (PATH) ile; gerçek API çağrısı yok."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(f"#!{sys.executable}\n{FAKE_GH}")
    gh.chmod(0o755)
    (tmp_path / "canli.json").write_text(json.dumps(canli))
    r = subprocess.run(
        ["bash", str(SCRIPT), "--repo", "o/r", "--apply", *args],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_STATE": str(tmp_path),
        },
    )
    assert r.returncode == 0, r.stderr + r.stdout
    govde = json.loads((tmp_path / "govde.json").read_text())
    rsc = next(k for k in govde["rules"] if k["type"] == "required_status_checks")
    return r.stderr, [c["context"] for c in rsc["parameters"]["required_status_checks"]]


def test_apply_existing_json_yok_sayilir_canli_okunur_ve_uyarir(tmp_path: Path) -> None:
    """MİM-D8: --apply'da --existing-json yok sayılır (canlı ruleset), fark varsa uyarı."""
    eski = tmp_path / "eski.json"
    eski.write_text(json.dumps(_mevcut_rsc(["test-local"])))
    canli = _mevcut_rsc(["test-local", "ast-guard", "semgrep", "masaustu-windows"])
    hata, sonuc = _apply(tmp_path, canli, "--add-checks", "web-java", "--existing-json", str(eski))
    assert sonuc == ["test-local", "ast-guard", "semgrep", "masaustu-windows", "web-java"]
    assert "yok sayılır" in hata
    assert "canlı ruleset'ten farklı" in hata


def test_apply_canli_liste_bos_ise_checks_tabani(tmp_path: Path) -> None:
    hata, sonuc = _apply(tmp_path, _mevcut_rsc([]), "--add-checks", "web-java")
    assert sonuc == ["test-local", "ast-guard", "semgrep", "web-java"]
    assert "zorunlu check yok" in hata
