"""Depo tanımsız proje (Home'da kod deposu bağlanmamış, GitHub kipi): `codegen.pr_sync` her
dakika `GITHUB_REPO gerekli` hatası vermez; sessizce atlar (proje başına tek info) ve bir sonraki
turu yine planlar (depo sonradan bağlanırsa senkron başlar)."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from sqlalchemy import Engine, text

from tp_core.config import get_settings
from tp_core.features.codegen import service


def test_depo_tanimsiz_projede_pr_sync_sessizce_atlar(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("TP_FORGE", "github")
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    monkeypatch.delitem(service._factories, "forge", raising=False)
    monkeypatch.setattr(service, "_DEPOSUZ_BILDIRILEN", set())
    get_settings.cache_clear()
    ctx: Any = None  # run_pr_sync bağlamı kullanmaz
    try:
        with caplog.at_level(logging.DEBUG, logger=service.log.name):
            for _ in range(2):
                assert service.run_pr_sync(ctx, engine) == {"atlandi": "depo_yok"}
        kayitlar = [r for r in caplog.records if "PR senkronu atlandı" in r.getMessage()]
        assert [r.levelno for r in kayitlar] == [logging.INFO, logging.DEBUG]
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        with engine.begin() as conn:
            planli = conn.execute(
                text("SELECT count(*) FROM job WHERE tur = :t "),
                {"t": service.PR_SYNC_JOB},
            ).scalar_one()
        assert planli >= 1  # sonraki tur yine planlı
    finally:
        get_settings.cache_clear()
