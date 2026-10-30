"""Gerçek Postgres'e karşı: şema, tohum ve salt okuma yetkileri.

Çalıştırmak için (infra/postgres/init betikleriyle kurulmuş bir Postgres):
  DEMOAPP_TEST_PG_URL=postgresql+psycopg://demoapp:...@127.0.0.1:PORT/demoapp \
  DEMOAPP_TEST_PG_RO_URL=postgresql+psycopg://demoapp_ro:...@127.0.0.1:PORT/demoapp \
  uv run pytest -m postgres
Ortam değişkenleri yoksa atlanır.
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from demoapp_api import db
from demoapp_api.main import app

PG_URL = os.environ.get("DEMOAPP_TEST_PG_URL")
RO_URL = os.environ.get("DEMOAPP_TEST_PG_RO_URL")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not (PG_URL and RO_URL), reason="DEMOAPP_TEST_PG_URL tanımlı değil"),
]


@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setenv("DEMOAPP_DATABASE_URL", PG_URL)
    monkeypatch.setenv("DEMOAPP_TEST_MODE", "1")
    monkeypatch.setenv("DEMOAPP_TEST_TOKEN", "pg-test-tokeni")
    db.clear_caches()
    with TestClient(app) as c:
        assert (
            c.post("/test/reset", headers={"X-Demoapp-Test-Token": "pg-test-tokeni"}).status_code
            == 200
        )
        yield c
    db.get_engine().dispose()


def test_postgres_uc_uca(pg):
    assert pg.get("/health").json()["checks"] == {"db": "ok"}
    assert pg.post("/auth/login", json={"kullanici_adi": "bayi1", "parola": "Demo123!"}).is_success
    pg.post("/cart/lines", json={"urun_kod": "P-001", "adet": 7})
    cart = pg.get("/cart").json()
    assert (cart["indirim"], cart["toplam"]) == ("25.00", "150.00")
    pg.post("/cart/lines", json={"urun_kod": "P-004", "adet": 30})
    assert pg.post("/orders").status_code == 201


def test_postgres_bayi_kapsamli_kirilma(pg):
    h = {"X-Demoapp-Test-Token": "pg-test-tokeni"}
    kir = pg.post("/test/break", json={"kullanici_adi": "bayi1", "kampanya": True}, headers=h)
    assert kir.status_code == 200
    assert pg.post("/auth/login", json={"kullanici_adi": "bayi1", "parola": "Demo123!"}).is_success
    pg.post("/cart/lines", json={"urun_kod": "P-001", "adet": 7})
    assert pg.get("/cart").json()["indirim"] == "0.00"
    pg.post("/test/break", json={"kullanici_adi": "bayi1", "kampanya": False}, headers=h)
    assert pg.get("/cart").json()["indirim"] == "25.00"


def test_salt_okuma_rolu(pg):
    ro = create_engine(RO_URL)
    try:
        with ro.connect() as c:
            assert (
                c.execute(
                    text("SELECT deger FROM ayar WHERE anahtar='min_siparis_tutari'")
                ).scalar()
                == "750.00"
            )
            assert c.execute(text("SELECT count(*) FROM urun")).scalar() == 4
            assert c.execute(text("SELECT count(*) FROM kampanya")).scalar() == 1
            assert (
                c.execute(
                    text("SELECT kredi_limiti FROM bayi WHERE kullanici_adi='bayi1'")
                ).scalar()
                is not None
            )
        for sql in [
            "SELECT parola_hash FROM bayi",
            "SELECT * FROM siparis",
            "SELECT * FROM siparis_satiri",
            "SELECT * FROM sepet_satiri",
            "SELECT * FROM oturum",
            "SELECT * FROM test_kirilma",
            "UPDATE ayar SET deger='1'",
        ]:
            with ro.connect() as c, pytest.raises(DBAPIError):
                c.execute(text(sql))
    finally:
        ro.dispose()
