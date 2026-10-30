from fastapi.testclient import TestClient

from demoapp_api import db
from demoapp_api.main import app

client = TestClient(app)


def test_health_ok(monkeypatch):
    monkeypatch.setattr(db, "check_db", lambda: "ok")
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {
        "service": "demo-app-api",
        "status": "ok",
        "version": "0.1.0",
        "checks": {"db": "ok"},
    }


def test_health_degraded(monkeypatch):
    monkeypatch.setattr(db, "check_db", lambda: "error: connection refused")
    resp = client.get("/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["service"] == "demo-app-api"
    assert body["status"] == "degraded"
    assert body["version"] == "0.1.0"
    assert body["checks"] == {"db": "error: connection refused"}


def test_check_db_without_url_reports_error(monkeypatch):
    monkeypatch.delenv("DEMOAPP_DATABASE_URL", raising=False)
    db.get_engine.cache_clear()
    try:
        assert db.check_db().startswith("error: ")
    finally:
        db.get_engine.cache_clear()
