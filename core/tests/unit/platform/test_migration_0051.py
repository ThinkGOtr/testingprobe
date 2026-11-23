"""Migrasyon 0051: `run`, `test_result`, `ci_tetik` tetik CHECK'leri `sauce`'u kabul eder; downgrade
(sauce satırı yokken) eski kümeye döner ve yeniden yükseltilebilir."""

from __future__ import annotations

import psycopg
import pytest

from .conftest import PgServer, run_alembic
from .test_migrations import _sil, _yeni_bos_db

EV = "test-a"
KISIT = "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = ANY(%s)"
ADLAR = ["run_tetik_ck", "test_result_tetik_ck", "ci_tetik_tetik_ck"]


def _tanimlar(dsn: str) -> dict[str, str]:
    with psycopg.connect(dsn, autocommit=True) as c:
        return {ad: tanim for ad, tanim in c.execute(KISIT, (ADLAR,)).fetchall()}


def test_0051_sauce_tetik(pg: PgServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_HOME_PROJECT", EV)
    ad, owner, dsn = _yeni_bos_db(pg, "head")
    try:
        t = _tanimlar(dsn)
        assert set(t) == set(ADLAR)
        assert all("sauce" in v for v in t.values())
        run_alembic(owner, "0050", "downgrade")
        t = _tanimlar(dsn)
        assert all("sauce" not in v and "manual" in v for v in t.values())
        run_alembic(owner, "head")
        assert all("sauce" in v for v in _tanimlar(dsn).values())
    finally:
        _sil(pg, ad)
