"""GÜV-Y7: CI/artefakt girdi süzgeçleri tam eşleşir (`fullmatch`).

`^…$` + `re.match` sondaki `\\n`'i geçiriyordu (`$` satır sonundan önce de eşleşir): ör.
`runs/abc\\n` koşu dizini, `<sha>\\n` checks dosyası adı, `<bitiş>.<imza>\\n` imzalı bağlantı ya da
`results\\n` yol öğesi kabul ediliyordu. Süzgeç düzeyinde sınanır.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from tp_core.features.ci import artifacts
from tp_core.features.ci import service as ci_service
from tp_core.features.triage import evidence as ev

SHA = "a" * 40


@pytest.mark.parametrize(
    ("desen", "gecerli"),
    [
        (ci_service.RUN_DIR_RE, "runs/abc-1"),
        (ci_service.SHA_RE, SHA),
        (ci_service.REF_RE, "feature/x"),
        (ci_service.SAUCE_URL_RE, "https://app.saucelabs.com/tests/abc"),
        (ev.RUN_DIR_RE, "runs/abc-1"),
    ],
)
def test_desenler_sondaki_satir_sonunu_kabul_etmez(desen, gecerli: str) -> None:
    assert desen.fullmatch(gecerli)
    for ek in ("\n", "\r\n", "\nek"):
        assert desen.fullmatch(gecerli + ek) is None


def test_validate_sha_satir_sonunu_reddeder() -> None:
    assert ci_service.validate_sha(SHA) == SHA
    with pytest.raises(ci_service.CiError):
        ci_service.validate_sha(SHA + "\n")
    with pytest.raises(ci_service.CiError):
        ci_service.validate_sha("main\n")


def test_checks_dosyasi_satir_sonlu_sha_okunmaz(tmp_path: Path) -> None:
    (tmp_path / f"{SHA}\n.json").write_text("{}")
    with patch.object(ci_service.services, "checks_root", return_value=tmp_path):
        assert ci_service._checks_dosyasi(SHA + "\n") is None


def test_kosu_dizini_satir_sonlu_dizini_reddeder(tmp_path: Path) -> None:
    assert ev.kosu_dizini(tmp_path, "runs/abc") == tmp_path / "runs/abc"
    assert ev.kosu_dizini(tmp_path, "runs/abc\n") is None


def test_artefakt_yolu_satir_sonlu_ogeyi_reddeder(tmp_path: Path) -> None:
    hedef = tmp_path / "src" / "results"
    hedef.mkdir(parents=True)
    (hedef / "a.txt").write_text("x")
    assert artifacts.coz(tmp_path, "src/results/a.txt") == (hedef / "a.txt").resolve()
    with pytest.raises(artifacts.YolHatasi):
        artifacts.coz(tmp_path, "src/results/a.txt\n")


def test_imzali_baglanti_satir_sonlu_token_gecersiz() -> None:
    run_id = uuid.uuid4()
    anahtar = b"k" * 32
    with patch.object(artifacts, "_imza_anahtari", return_value=anahtar):
        tok = artifacts.link_token(run_id, 1_000.0)
        assert tok is not None
        assert artifacts.token_gecerli_mi(run_id, tok, 1_000.0)
        assert not artifacts.token_gecerli_mi(run_id, tok + "\n", 1_000.0)
