"""Çekirdeğin başka şeritlerle paylaştığı sözleşmelerin kopyaları çekirdekle aynı kalmalı.

1. review-portal/src/api/sozlesme/durum-makineleri.json — portalın durum birlikleri bu dosyadan
   denetlenir. Çekirdekte MACHINES değişip dosya yeniden üretilmezse çekirdeğin kendi paketi kırılır
   (yeniden üretmek: review-portal içinde `npm run sozlesme:durumlar`).
2. .github/golden-drift/drift_sources.py — CI'daki golden-drift işi (anayasa II: ajan bağımlılığı
   yok) tp_core'u kuramadığı için üç küçük kuralı kopyalar. Kopyalar tp_core.gateway ile eşit
   olmalı.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tp_core.gateway import bundle, replay
from tp_core.gateway.config import load_model_table
from tp_core.workflow.states import MACHINES

REPO = Path(__file__).resolve().parents[3]
STATE_EXPORT = REPO / "review-portal" / "src" / "api" / "sozlesme" / "durum-makineleri.json"
DRIFT_SOURCES = REPO / ".github" / "golden-drift" / "drift_sources.py"
RULES = REPO / "rules"


def _machines_export() -> dict:
    # review-portal/scripts/durum_makineleri.py ile aynı biçim
    return {
        ad: {
            "initial": m.initial,
            "states": sorted(m.states),
            "transitions": {k: sorted(v) for k, v in sorted(m.transitions.items())},
        }
        for ad, m in sorted(MACHINES.items())
    }


@pytest.mark.skipif(not STATE_EXPORT.exists(), reason="review-portal yok")
def test_portal_durum_disa_aktarimi_machines_ile_ayni() -> None:
    checked_in = json.loads(STATE_EXPORT.read_text(encoding="utf-8"))
    assert checked_in == _machines_export(), (
        "review-portal/src/api/sozlesme/durum-makineleri.json çekirdek MACHINES'ten farklı; "
        "review-portal içinde `npm run sozlesme:durumlar` çalıştırın ve "
        "portal birliklerini güncelleyin"
    )


@pytest.fixture(scope="module")
def drift() -> ModuleType:
    if not DRIFT_SOURCES.exists():
        pytest.skip(".github/golden-drift yok")
    spec = importlib.util.spec_from_file_location("drift_sources_parity", DRIFT_SOURCES)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclass'lar modülü sys.modules'te arar
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return mod


@pytest.mark.parametrize(
    "args",
    [
        ("TPD-1", {}),
        ("TPD-1", {"case_no": 1}),
        ("TPD-3", {"case_no": 12}),
        ("TPD-1", {"check_round": 2}),
        ("TPD-4", {"check_round": 3}),
    ],
)
def test_golden_name_ayni(drift: ModuleType, args: tuple[str, dict]) -> None:
    key, kw = args
    assert drift.golden_name(key, **kw) == replay.golden_name(key, **kw)


@pytest.mark.parametrize(
    "kw", [{"case_no": 0}, {"check_round": 0}, {"case_no": 1, "check_round": 2}]
)
def test_golden_name_hatalari_ayni(drift: ModuleType, kw: dict) -> None:
    with pytest.raises(ValueError):
        replay.golden_name("TPD-1", **kw)
    with pytest.raises(ValueError):
        drift.golden_name("TPD-1", **kw)


def test_model_amaclari_ayni(drift: ModuleType) -> None:
    assert drift.model_purposes() == set(load_model_table(RULES).purposes)


def test_sema_adi_kurali_ayni(drift: ModuleType) -> None:
    assert drift._NAME_RE.pattern == bundle._NAME_RE.pattern
    for purpose in sorted(drift.model_purposes()):
        if (RULES / "schemas" / f"{purpose}.schema.json").exists():
            assert drift.load_schema(purpose) == bundle.load_schema(RULES, purpose)


# --------------------------------------------------------------- core ↔ toolchain (011 tur 2)

TOOLCHAIN_SOZLESME = REPO / "toolchain" / "tests" / "data" / "core_sozlesme.json"


@pytest.fixture(scope="module")
def toolchain_sozlesme() -> dict:
    if not TOOLCHAIN_SOZLESME.exists():
        pytest.skip("toolchain yok")
    return json.loads(TOOLCHAIN_SOZLESME.read_text(encoding="utf-8"))


def test_check_adi_toolchain_check_name_ile_ayni(toolchain_sozlesme: dict) -> None:
    """MİM-B2: core `platform.check_adi` ↔ toolchain worker `check_name` (toolchain tarafı aynı
    dosyayı `toolchain/tests/test_core_sozlesme.py`'de sınar)."""
    from tp_core.features.codegen import platform as p

    for g in toolchain_sozlesme["check_adlari"]:
        assert p.check_adi(g["platform"], g["lang"]) == g["check"], g
    ciftler = {(g["lang"], g["platform"] or p.WEB) for g in toolchain_sozlesme["check_adlari"]}
    beklenen = {(d, pl) for pl in p.PLATFORMLAR for d in p.TAM_HAT_DILLERI if p.gecerli_cift(pl, d)}
    assert ciftler == beklenen


def test_java_kapsam_sonekleri_toolchain_ile_ayni(toolchain_sozlesme: dict) -> None:
    """MİM-B4: onarımın `test_files`'a koyduğu Java testleri toolchain'in kabul ettiği küme."""
    from tp_core.features.codegen import platform as p

    assert list(p.JAVA_KAPSAM_SONEKLERI) == toolchain_sozlesme["java_kapsam_sonekleri"]
    assert set(p.JAVA_KAPSAM_SONEKLERI) <= set(p.JAVA_TEST_SONEKLERI)
    for yol in toolchain_sozlesme["java_kapsam_ornekleri"]["kabul"]:
        assert p.java_kapsam_dosyasi_mi(yol), yol
    for yol in toolchain_sozlesme["java_kapsam_ornekleri"]["red"]:
        assert not p.java_kapsam_dosyasi_mi(yol), yol
    assert not p.java_kapsam_dosyasi_mi("src/test/java/a/birim/KimlikTest.java")
