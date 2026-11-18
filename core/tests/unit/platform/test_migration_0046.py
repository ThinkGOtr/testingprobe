"""Migrasyon 0046 (platform deposu): `script.depo`, `pull_request.depo`, PK (project_id, depo,
number); aynı numaralı PR iki depoda yaşar; downgrade yalnız varsayılan depo satırlarıyla."""

from __future__ import annotations

import psycopg
import pytest

from .conftest import Db, PgServer, run_alembic
from .test_migrations import _sil, _yeni_bos_db

EV = "test-a"


def _app(db: Db) -> psycopg.Connection:
    return psycopg.connect(db.app_url.replace("+psycopg", ""), autocommit=True)


def test_ayni_numarali_pr_farkli_depolarda_tekil(db: Db) -> None:
    with _app(db) as c:
        c.execute(
            "INSERT INTO pull_request (project_id, number, branch, baslik, head_sha, acan) "
            "VALUES ('p1', 7, 'b', 't', 's', 'bot')"
        )
        # Varsayılan depo `''` (sütun varsayılanı); aynı numara platform deposunda ayrıca var.
        c.execute(
            "INSERT INTO pull_request (project_id, depo, number, branch, baslik, head_sha, acan) "
            "VALUES ('p1', 'acme/mobil', 7, 'b', 't', 's', 'bot')"
        )
        assert c.execute(
            "SELECT depo FROM pull_request WHERE project_id = 'p1' AND number = 7 ORDER BY depo"
        ).fetchall() == [("",), ("acme/mobil",)]
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute(
                "INSERT INTO pull_request (project_id, depo, number, branch, baslik, head_sha, "
                "acan) VALUES ('p1', 'acme/mobil', 7, 'b', 't', 's', 'bot')"
            )
        assert c.execute(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'script' AND column_name = 'depo'"
        ).fetchone() == ("''::text",)


def test_0046_downgrade_ayri_depo_satiri_varken_reddedilir_yoksa_calisir(
    pg: PgServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_HOME_PROJECT", EV)
    ad, owner, dsn = _yeni_bos_db(pg, "head")
    try:
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute(
                "INSERT INTO pull_request (project_id, depo, number, branch, baslik, head_sha, "
                "acan) VALUES (%s, 'acme/mobil', 3, 'b', 't', 's', 'bot')",
                (EV,),
            )
        with pytest.raises(RuntimeError, match="varsayılan dışı depoya"):
            run_alembic(owner, "0045", "downgrade")
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("DELETE FROM pull_request")
            c.execute(
                "INSERT INTO pull_request (project_id, number, branch, baslik, head_sha, acan) "
                "VALUES (%s, 3, 'b', 't', 's', 'bot')",
                (EV,),
            )
        run_alembic(owner, "0045", "downgrade")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute(
                "SELECT count(*) FROM information_schema.columns WHERE column_name = 'depo' "
                "AND table_name IN ('script', 'pull_request')"
            ).fetchone() == (0,)
            assert c.execute("SELECT number FROM pull_request").fetchall() == [(3,)]
        run_alembic(owner, "head")  # yeniden yükseltilebilir; mevcut satır depo = ''
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT depo, number FROM pull_request").fetchall() == [("", 3)]
    finally:
        _sil(pg, ad)
