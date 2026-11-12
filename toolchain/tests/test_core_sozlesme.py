"""Core ↔ toolchain sözleşmesi (011 inceleme turu 2, MİM-B2 / MİM-B4).

`tests/data/core_sozlesme.json` hem bu test hem core `tests/unit/test_cross_lane_contracts.py`
tarafından okunur: core `platform.check_adi` ile worker `check_name` her (lang, platform) için aynı
adı, core onarımının `test_files`'a koyduğu Java dosyaları (`platform.JAVA_KAPSAM_SONEKLERI`) ile
worker `JAVA_TEST_FILE_RE` aynı kümeyi verir.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worker import check as checks
from worker import java

SOZLESME = json.loads(
    (Path(__file__).parent / "data" / "core_sozlesme.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize(
    "girdi", SOZLESME["check_adlari"], ids=lambda g: f"{g['lang']}-{g['platform']}"
)
def test_check_name_core_check_adi_ile_ayni(girdi: dict) -> None:
    assert checks.check_name(girdi["lang"], girdi["platform"]) == girdi["check"]


def test_sozlesme_her_lang_platform_ciftini_kapsar() -> None:
    ciftler = {(g["lang"], g["platform"]) for g in SOZLESME["check_adlari"]}
    beklenen = {("ts", "web"), ("ts", None), ("java", "web"), ("java", None)}
    beklenen |= {("java", p) for p in java.APP_PLATFORMS}
    assert ciftler == beklenen
    assert set(java.LANGS) == {g["lang"] for g in SOZLESME["check_adlari"]}


def test_java_test_dosyasi_kalibi_core_kapsam_sonekleriyle_ayni() -> None:
    for yol in SOZLESME["java_kapsam_ornekleri"]["kabul"]:
        assert java.validate_java_test_file(yol) == yol
        assert yol.endswith(tuple(SOZLESME["java_kapsam_sonekleri"]))
    for yol in SOZLESME["java_kapsam_ornekleri"]["red"]:
        with pytest.raises(ValueError):
            java.validate_java_test_file(yol)
        assert not yol.endswith(tuple(SOZLESME["java_kapsam_sonekleri"]))
