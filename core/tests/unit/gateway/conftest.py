import shutil
from pathlib import Path

import pytest
import yaml

from tp_core.gateway import Budget, Gateway, PiiMasker, RetryPolicy, find_rules_dir
from tp_core.gateway.config import load_model_table
from tp_core.gateway.testing import FakeProvider, InMemoryCallRecorder

REAL_RULES = find_rules_dir()


@pytest.fixture
def rules_dir(tmp_path: Path) -> Path:
    """Gerçek rules/ kopyası (record modu yazsa bile depo kirlenmez)."""
    target = tmp_path / "rules"
    shutil.copytree(REAL_RULES, target)
    _degerlendirmeyi_sifirla(target)
    return target


def _degerlendirmeyi_sifirla(rules: Path) -> None:
    """Kopyadaki canlı değerlendirme durumunu `pending`e döndürür.

    Depodaki `rules/evaluations.yaml` gerçek canlı koşularla (`make eval-live --update-status`)
    değişir; geçici kopya üzerinde çalışan testler deterministik bir başlangıç (hiçbir paket
    değerlendirilmemiş, istisna yok) ister. Depodaki gerçek durumu `RULES` üzerinden okuyan testler
    bundan etkilenmez.
    """
    path = rules / "evaluations.yaml"
    metin = path.read_text(encoding="utf-8")
    # Açıklama başlığı (yorumlar) korunur; yalnızca kayıtlar yeniden yazılır.
    baslik = metin[: metin.index("\nversion:") + 1] if "\nversion:" in metin else ""
    data = yaml.safe_load(metin)
    for kayit in (data.get("bundles") or {}).values():
        kayit["status"] = "pending"
        kayit.pop("evaluation", None)
        kayit.pop("waiver", None)
        kayit["note"] = "test kopyası: canlı değerlendirme yapılmadı"
    govde = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    path.write_text(baslik + govde, encoding="utf-8")
    sonuclar = rules / "evaluation" / "results"
    if sonuclar.is_dir():
        shutil.rmtree(sonuclar)


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
