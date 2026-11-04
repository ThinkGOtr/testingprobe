"""Platform testleri: gerçek Postgres fikstürleri `tests/unit/conftest.py`'dedir (tüm şeritler
tek oturum konteynerini paylaşır). Burada fikstür olmayan yardımcılar yeniden verilir ve asistan
şeridi kapatılır (`_asistan_seridi_kapali`)."""

import pytest

from tests.unit.conftest import (  # noqa: F401
    CORE_DIR,
    PAROLA,
    SESSION_SECRET,
    Db,
    PgServer,
    alembic_config,
    run_alembic,
)


@pytest.fixture(autouse=True)
def _asistan_seridi_kapali(monkeypatch: pytest.MonkeyPatch) -> None:
    """Platform worker testlerinde asistan şeridi kapalı (`TP_WORKER_ASISTAN_SERIT=0`).

    `tp_core.features.assistant` içe aktarıldığında `assistant.answer` global `REGISTRY`'ye
    kaydolur; şerit açıkken `worker.run` asistan iş parçacıkları ve kalp atışı başlatır. Hangi
    testin modülü önce içe aktardığına göre değişmesin diye burada hep kapalıdır; asistan şeridini
    sınayan test `monkeypatch.delenv`/`setenv` ile açar (asistan şeridinin kendi testleri
    `tests/unit/features/assistant/test_worker_asistan.py`'dedir).
    """
    monkeypatch.setenv("TP_WORKER_ASISTAN_SERIT", "0")
