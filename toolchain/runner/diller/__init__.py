"""test-runner dil eklentileri (014; sözleşme specs/014-test-dilleri/plan.md §3.2).

`runner/diller/<dil>.py` modül düzeyinde `EKLENTI` (`RunnerDili`) tanımlar; keşif otomatik.
ts yolu `runner/run.py`'de kalır; java `runner/diller/java.py` (java_run sarmalayıcısı).
musteri_ci dilleri (kotlin, swift) runner eklentisi yazmaz: koşu müşterinin CI'ındadır.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import threading
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover
    import httpx

    from runner.run import RunRequest
    from toolchain_common import repos
    from toolchain_common.settings import Settings

log = logging.getLogger(__name__)


@runtime_checkable
class RunnerDili(Protocol):
    ad: str

    def validate_test_file(self, yol: str) -> str: ...

    def execute_locked(
        self, cfg: Settings, req: RunRequest, loc: repos.Located, http: httpx.Client | None
    ) -> dict[str, Any]: ...


_KILIT = threading.Lock()
_KAYIT: dict[str, RunnerDili] | None = None
_HATALAR: dict[str, str] = {}


def kayit() -> dict[str, RunnerDili]:
    global _KAYIT
    with _KILIT:
        if _KAYIT is None:
            k: dict[str, RunnerDili] = {}
            for mod in pkgutil.iter_modules(__path__):  # type: ignore[name-defined]
                if mod.name.startswith("_"):
                    continue
                try:
                    e = importlib.import_module(f"{__name__}.{mod.name}").EKLENTI
                except Exception as exc:
                    _HATALAR[mod.name] = f"{type(exc).__name__}: {exc}"
                    log.warning("runner dil eklentisi yüklenemedi: %s (%s)", mod.name, exc)
                    continue
                k[e.ad] = e
            _KAYIT = k
        return _KAYIT


def eklenti(dil: str | None) -> RunnerDili | None:
    return kayit().get(dil or "")


def adlar() -> tuple[str, ...]:
    """Koşulabilir diller: `ts` (yerleşik) + kayıtlı eklentiler."""
    return ("ts", *(a for a in kayit() if a != "ts"))


def hatalar() -> dict[str, str]:
    kayit()
    return dict(_HATALAR)


def _sifirla() -> None:
    global _KAYIT
    with _KILIT:
        _KAYIT = None
        _HATALAR.clear()
