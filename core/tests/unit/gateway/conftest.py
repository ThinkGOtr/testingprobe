import shutil
from pathlib import Path

import pytest

from tp_core.gateway import Budget, Gateway, PiiMasker, RetryPolicy, find_rules_dir
from tp_core.gateway.config import load_model_table
from tp_core.gateway.testing import FakeProvider, InMemoryCallRecorder

REAL_RULES = find_rules_dir()


@pytest.fixture
def rules_dir(tmp_path: Path) -> Path:
    """Gerçek rules/ kopyası (record modu yazsa bile depo kirlenmez)."""
    target = tmp_path / "rules"
    shutil.copytree(REAL_RULES, target)
    return target


@pytest.fixture
def recorder() -> InMemoryCallRecorder:
    return InMemoryCallRecorder()


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def make_gateway(rules_dir: Path, recorder: InMemoryCallRecorder, sleeps: list[float]):
    def _make(
        script=None,
        *,
        mode: str = "live",
        budget: Budget | None = None,
        masker: PiiMasker | None = None,
        **kwargs,
    ) -> tuple[Gateway, FakeProvider | None]:
        provider = FakeProvider(script or []) if mode != "replay" else None
        gw = Gateway(
            provider=provider,
            recorder=recorder,
            mode=mode,  # type: ignore[arg-type]
            models=load_model_table(rules_dir),
            rules_dir=rules_dir,
            budget=budget,
            masker=masker,
            retry=RetryPolicy(max_retries=3, base_delay_s=1.0),
            sleep=sleeps.append,
            **{"record_extras": True, **kwargs},
        )
        return gw, provider

    return _make
