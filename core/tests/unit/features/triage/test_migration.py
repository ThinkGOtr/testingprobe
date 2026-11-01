"""0011: triage tabloları model ↔ şema eşitliği, tp_app yetkileri, downgrade/upgrade."""

from __future__ import annotations

import psycopg
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from tests.unit.conftest import Db, run_alembic
from tp_core.models import Base
from tp_core.models import triage_feature as triage_feature

TABLOLAR = {"failure_ek", "triage_kosu"}


def _farklar(url: str) -> list[object]:
    eng = create_engine(url)
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        farklar = compare_metadata(ctx, Base.metadata)
    eng.dispose()
    return [f for f in farklar if any(t in repr(f) for t in TABLOLAR)]


def test_triage_modelleri_ve_migrasyon_ayni(db: Db) -> None:
    assert set(Base.metadata.tables) >= TABLOLAR
    assert _farklar(db.owner_url) == []


def test_tp_app_triage_tablolarina_yazabilir(db: Db) -> None:
    with psycopg.connect(db.app_url.replace("+psycopg", ""), autocommit=True) as c:
        c.execute("SELECT count(*) FROM failure_ek")
        c.execute("SELECT count(*) FROM triage_kosu")
        c.execute(
            "INSERT INTO run (id, tetik) VALUES ('00000000-0000-0000-0000-000000000001', 'push')"
        )
        c.execute(
            "INSERT INTO triage_kosu (run_id, durum) "
            "VALUES ('00000000-0000-0000-0000-000000000001', 'done')"
        )
        c.execute("UPDATE triage_kosu SET neden = 'x'")
        c.execute("DELETE FROM triage_kosu")


def test_downgrade_upgrade(db: Db) -> None:
    run_alembic(db.owner_url, "0010", "downgrade")
    with psycopg.connect(db.owner_url.replace("+psycopg", ""), autocommit=True) as c:
        var = c.execute(
            "SELECT count(*) FROM pg_tables WHERE tablename IN ('failure_ek', 'triage_kosu')"
        ).fetchone()
        assert var == (0,)
    run_alembic(db.owner_url, "head")
    assert _farklar(db.owner_url) == []
