"""0010: CI tabloları model ↔ şema eşitliği, tp_app yetkileri, downgrade/upgrade."""

from __future__ import annotations

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from tests.unit.conftest import Db, run_alembic
from tp_core.models import Base
from tp_core.models import ci_feature as ci_feature

TABLOLAR = {"ci_tetik", "test_result_ek", "run_aria"}
INDEKS = "test_result_commit_ix_ci"


def _ilgili(fark: object) -> bool:
    metin = repr(fark)
    return any(t in metin for t in (*TABLOLAR, INDEKS))


def _farklar(url: str) -> list[object]:
    eng = create_engine(url)
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        farklar = compare_metadata(ctx, Base.metadata)
    eng.dispose()
    return [f for f in farklar if _ilgili(f)]


def test_ci_modelleri_ve_migrasyon_ayni(db: Db) -> None:
    assert set(Base.metadata.tables) >= TABLOLAR
    assert _farklar(db.owner_url) == []


def test_tp_app_ci_tablolarina_yazabilir(db: Db) -> None:
    with psycopg.connect(db.app_url.replace("+psycopg", ""), autocommit=True) as c:
        c.execute(
            "INSERT INTO ci_tetik (anahtar, tetik, kaynak, isteyen) VALUES ('x', 'deploy', 'local', 't')"  # noqa: E501
        )
        c.execute("UPDATE ci_tetik SET isteyen = 'u' WHERE anahtar = 'x'")
        c.execute("DELETE FROM ci_tetik WHERE anahtar = 'x'")
        c.execute("SELECT count(*) FROM test_result_ek")
        rid = c.execute(
            "INSERT INTO run (tetik, kaynak, sonuc) "
            "VALUES ('push', 'github', 'passed') RETURNING id"
        ).fetchone()[0]
        c.execute(
            "INSERT INTO run_aria (run_id, yol, ad, icerik, boyut, kaynak) "
            "VALUES (%s, 'a/k.aria.yml', 'k.aria.yml', '- main', 6, 'github_artefakt')",
            (rid,),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute(
                "INSERT INTO run_aria (run_id, yol, ad, icerik, boyut, kaynak) "
                "VALUES (%s, 'a/k.aria.yml', 'k.aria.yml', '- main', 6, 'github_artefakt')",
                (rid,),
            )
        c.execute("DELETE FROM run WHERE id = %s", (rid,))
        kalan = c.execute("SELECT count(*) FROM run_aria WHERE run_id = %s", (rid,)).fetchone()
        assert kalan == (0,)  # cascade


def test_downgrade_upgrade(db: Db) -> None:
    run_alembic(db.owner_url, "0009", "downgrade")
    with psycopg.connect(db.owner_url.replace("+psycopg", ""), autocommit=True) as c:
        var = c.execute(
            "SELECT count(*) FROM pg_tables WHERE tablename IN ('ci_tetik', 'test_result_ek')"
        ).fetchone()
        assert var == (0,)
    run_alembic(db.owner_url, "head")
    assert _farklar(db.owner_url) == []


def test_0015_hata_baglami_downgrade_upgrade(db: Db) -> None:
    def kolon_var() -> bool:
        with psycopg.connect(db.owner_url.replace("+psycopg", ""), autocommit=True) as c:
            return c.execute(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'test_result_ek' AND column_name = 'hata_baglami'"
            ).fetchone() == (1,)

    assert kolon_var()
    run_alembic(db.owner_url, "0014", "downgrade")
    assert not kolon_var()
    run_alembic(db.owner_url, "head")
    assert kolon_var() and _farklar(db.owner_url) == []


def test_0016_run_aria_downgrade_upgrade(db: Db) -> None:
    def tablo_var() -> bool:
        with psycopg.connect(db.owner_url.replace("+psycopg", ""), autocommit=True) as c:
            return c.execute(
                "SELECT count(*) FROM pg_tables WHERE tablename = 'run_aria'"
            ).fetchone() == (1,)

    assert tablo_var()
    run_alembic(db.owner_url, "0015", "downgrade")
    assert not tablo_var()
    run_alembic(db.owner_url, "head")
    assert tablo_var() and _farklar(db.owner_url) == []
