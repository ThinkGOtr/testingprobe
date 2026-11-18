"""Migrasyon 0050 (IA-16): `failure_karar_kaynagi_ck` `human`'ı kabul eder; downgrade (human
satırı yokken) eski kümeye döner ve yeniden yükseltilebilir."""

from __future__ import annotations

import psycopg
import pytest

from .conftest import PgServer, run_alembic
from .test_migrations import _sil, _yeni_bos_db

EV = "test-a"
KISIT = (
    "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'failure_karar_kaynagi_ck'"
)


def test_0050_karar_kaynagi_human(pg: PgServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_HOME_PROJECT", EV)
    ad, owner, dsn = _yeni_bos_db(pg, "head")
    try:
        with psycopg.connect(dsn, autocommit=True) as c:
            assert "human" in c.execute(KISIT).fetchone()[0]
        run_alembic(owner, "0049", "downgrade")
        with psycopg.connect(dsn, autocommit=True) as c:
            tanim = c.execute(KISIT).fetchone()[0]
        assert "human" not in tanim and "llm" in tanim
        run_alembic(owner, "head")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert "human" in c.execute(KISIT).fetchone()[0]
    finally:
        _sil(pg, ad)
