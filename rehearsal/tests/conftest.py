from __future__ import annotations

from typing import Any

import pytest

from tp_rehearsal.runner import Baglam


class SahteSaat:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def uyu(self, s: float) -> None:
        self.t += s


class SahteApi:
    """Yol → yanıt eşlemesi; çağrılar kaydedilir."""

    def __init__(self, yanitlar: dict[str, Any] | None = None) -> None:
        self.yanitlar = yanitlar or {}
        self.cagrilar: list[tuple[str, str, str]] = []

    def get(self, rol: str, yol: str) -> Any:
        self.cagrilar.append((rol, "GET", yol))
        y = self.yanitlar[yol]
        return y() if callable(y) else y


@pytest.fixture
def saat() -> SahteSaat:
    return SahteSaat()


@pytest.fixture
def baglam(saat: SahteSaat):
    def yap(kip: str = "prova", api: Any = None) -> Baglam:
        loglar: list[str] = []
        b = Baglam(
            kip=kip,
            api=api or SahteApi(),
            jira=None,
            yigin=None,
            ortam=None,
            log=loglar.append,
            saat=saat,
            uyu=saat.uyu,
        )
        b.veri["_loglar"] = loglar
        return b

    return yap
