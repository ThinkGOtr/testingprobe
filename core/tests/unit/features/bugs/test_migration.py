"""0012: bug_draft_ek model ↔ şema eşitliği, tp_app yetkileri, downgrade/upgrade."""

from __future__ import annotations

import psycopg
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from tests.unit.conftest import Db, run_alembic
from tp_core.models import Base
from tp_core.models import bugs_feature as bugs_feature

TABLO = "bug_draft_ek"


def _farklar(url: str) -> list[object]:
    eng = create_engine(url)
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        farklar = compare_metadata(ctx, Base.metadata)
    eng.dispose()
    return [f for f in farklar if TABLO in repr(f)]


def test_bugs_modeli_ve_migrasyon_ayni(db: Db) -> None:
    assert TABLO in Base.metadata.tables
    assert _farklar(db.owner_url) == []


def test_tp_app_yazabilir(db: Db) -> None:
    with psycopg.connect(db.app_url.replace("+psycopg", ""), autocommit=True) as c:
        c.execute("SELECT count(*) FROM bug_draft_ek")
        c.execute("UPDATE bug_draft_ek SET hazirlik_durum = 'hazir' WHERE false")
        c.execute("DELETE FROM bug_draft_ek WHERE false")


def test_downgrade_upgrade(db: Db) -> None:
    run_alembic(db.owner_url, "0011", "downgrade")
    with psycopg.connect(db.owner_url.replace("+psycopg", ""), autocommit=True) as c:
        var = c.execute("SELECT count(*) FROM pg_tables WHERE tablename = 'bug_draft_ek'")
        assert var.fetchone() == (0,)
    run_alembic(db.owner_url, "head")
    assert _farklar(db.owner_url) == []
