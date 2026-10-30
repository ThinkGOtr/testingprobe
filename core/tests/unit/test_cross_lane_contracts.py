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
