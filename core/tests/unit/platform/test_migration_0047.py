"""Migrasyon 0047 (014 test dilleri): `script_dil_ck` kotlin + swift'i kabul eder; downgrade
(kotlin/swift satırı yokken) eski dört dile döner ve yeniden yükseltilebilir."""

from __future__ import annotations

import psycopg
import pytest

from .conftest import PgServer, run_alembic
from .test_migrations import _sil, _yeni_bos_db

EV = "test-a"
KISIT = "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'script_dil_ck'"


def test_0047_dil_kisiti_ve_geri_alma(pg: PgServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_HOME_PROJECT", EV)
    ad, owner, dsn = _yeni_bos_db(pg, "head")
    try:
        with psycopg.connect(dsn, autocommit=True) as c:
            tanim = c.execute(KISIT).fetchone()[0]
        assert "kotlin" in tanim and "swift" in tanim
        run_alembic(owner, "0046", "downgrade")
        with psycopg.connect(dsn, autocommit=True) as c:
            tanim = c.execute(KISIT).fetchone()[0]
        assert "kotlin" not in tanim and "python" in tanim
        run_alembic(owner, "head")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert "swift" in c.execute(KISIT).fetchone()[0]
    finally:
        _sil(pg, ad)
