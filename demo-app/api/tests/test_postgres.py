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


def test_postgres_ekilmis_hata_ve_eski_sema(pg):
    """Veri hatası Postgres'te de bayi kapsamlıdır; `hata` kolonu olmayan (önceki sürümle
    kurulmuş) veritabanına kolon açılışta eklenir ve salt okuma yetkileri yerinde kalır."""
    h = {"X-Demoapp-Test-Token": "pg-test-tokeni"}
    motor = db.get_engine()
    with motor.begin() as c:
        c.execute(text("ALTER TABLE test_kirilma DROP COLUMN hata"))
    assert db.kolonlari_tamamla(motor) == ["test_kirilma.hata"]
    assert db.kolonlari_tamamla(motor) == []  # idempotent
    db.init_db()  # yetkiler yeniden verilir; hata vermez

    kir = pg.post(
        "/test/break", json={"kullanici_adi": "bayi1", "hata": "fiyat_p004_31"}, headers=h
    )
    assert kir.json() == {"kullanici_adi": "bayi1", "kampanya": False, "hata": "fiyat_p004_31"}
    assert pg.post("/auth/login", json={"kullanici_adi": "bayi1", "parola": "Demo123!"}).is_success
    fiyat = {u["kod"]: u["fiyat"] for u in pg.get("/products").json()}
    assert fiyat["P-004"] == "31.00"
    pg.post("/cart/lines", json={"urun_kod": "P-004", "adet": 25})
    assert pg.get("/cart").json()["toplam"] == "775.00"
    with motor.connect() as c:  # tabloya yazılmadı
        assert str(c.execute(text("SELECT fiyat FROM urun WHERE kod='P-004'")).scalar()) == "30.00"
    pg.post("/test/break", json={"kullanici_adi": "bayi1", "hata": None}, headers=h)
    assert pg.get("/cart").json()["toplam"] == "750.00"
    assert pg.get("/test/faults", headers=h).status_code == 200
    test_salt_okuma_rolu(pg)


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
