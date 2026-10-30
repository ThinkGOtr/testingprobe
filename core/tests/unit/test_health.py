import pytest
from fastapi.testclient import TestClient

from tp_core.api import main


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def test_health_ok(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.db, "ping", lambda: None)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {
        "service": "core-api",
        "status": "ok",
        "version": "0.1.0",
        "checks": {"db": "ok"},
    }


def test_health_degraded(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def hata() -> None:
        raise OSError("connection refused")

    monkeypatch.setattr(main.db, "ping", hata)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json() == {
        "service": "core-api",
        "status": "degraded",
        "version": "0.1.0",
        "checks": {"db": "error: connection refused"},
    }
