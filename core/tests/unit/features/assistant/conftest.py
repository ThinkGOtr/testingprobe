"""Asistan testlerinin ortak koruması (AI-ASISTAN-PLANI §12, §13).

Geliştiricinin kabuğunda tanımlı `ANTHROPIC_API_KEY` hiçbir asistan testinde görünmez: hiçbir
test yanlışlıkla canlı model yoluna giremez. Anahtar isteyen testler (`test_worker_asistan`)
kendi sahte değerini `monkeypatch.setenv` ile verir; bu fikstür onlardan önce çalışır.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _canli_anahtar_yok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
