"""Asistan testlerinin ortak koruması (AI-ASISTAN-PLANI §12, §13).

Geliştiricinin kabuğunda tanımlı `ANTHROPIC_API_KEY` hiçbir asistan testinde görünmez: hiçbir
test yanlışlıkla canlı model yoluna giremez. Anahtar isteyen testler (`test_worker_asistan`)
kendi sahte değerini `monkeypatch.setenv` ile verir; bu fikstür onlardan önce çalışır.

`perf` işareti duvar saatiyle ölçen testleri ayırır (`-m 'not perf'` ile dışarıda bırakılır;
yavaş/paylaşılan CI'da `TP_TEST_PERF=0` da atlar).
"""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "perf: duvar saatiyle süre ölçen test (CI'da ayrılabilir)")


@pytest.fixture(autouse=True)
def _canli_anahtar_yok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
