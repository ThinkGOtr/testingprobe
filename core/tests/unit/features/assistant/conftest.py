"""Asistan testlerinin ortak koruması (AI-ASISTAN-PLANI §12, §13).

Geliştiricinin kabuğunda tanımlı `ANTHROPIC_API_KEY` hiçbir asistan testinde görünmez: hiçbir
test yanlışlıkla canlı model yoluna giremez. Anahtar isteyen testler (`test_worker_asistan`)
kendi sahte değerini `monkeypatch.setenv` ile verir; bu fikstür onlardan önce çalışır.

`perf` işareti duvar saatiyle ölçen testleri ayırır (işaret aşağıda `pytest_configure`'da kayıtlı;
`-m 'not perf'` geçerlidir).
Bu testler varsayılan olarak ATLANIR (yük altında yanlış kırmızı verir); toplu gönderim öncesi
ya da ayrı CI adımında `TP_TEST_PERF=1` ile açılır.
"""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "perf: duvar saatiyle süre ölçen test (CI'da ayrılabilir)")


# Duvar saatine hizalı pencere (`hiz._ARTIR`) dakika sınırında sıfırlanır: her isteği ayrı
# transaction'da sayan HTTP testleri sınırı geçerse sayaç düşer ve sınır testi yanlış kırmızı
# verir. Bu pencere (~31 yıl) test boyunca tek pencere demektir; sınır davranışının kendisi
# `test_hiz_sabit_pencere_sinir_dahil`'de tek transaction ile kanıtlanır.
SABIT_PENCERE_S = 10**9


@pytest.fixture
def sabit_hiz_penceresi(monkeypatch: pytest.MonkeyPatch) -> int:
    """Her kovanın sınırı aynı kalır, penceresi `SABIT_PENCERE_S` olur."""
    from tp_core.features.assistant import hiz

    for kova, (sinir, _) in list(hiz.VARSAYILAN_SINIRLAR.items()):
        monkeypatch.setitem(hiz.VARSAYILAN_SINIRLAR, kova, (sinir, SABIT_PENCERE_S))
    return SABIT_PENCERE_S


@pytest.fixture(autouse=True)
def _canli_anahtar_yok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
