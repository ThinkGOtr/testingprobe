import contextlib

import pytest
from fastapi.testclient import TestClient

from demoapp_api import db
from demoapp_api.main import app

TEST_TOKEN = "birim-test-tokeni"
TEST_HEADERS = {"X-Demoapp-Test-Token": TEST_TOKEN}


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMOAPP_DATABASE_URL", f"sqlite:///{tmp_path / 'demoapp.db'}")
    monkeypatch.setenv("DEMOAPP_TEST_MODE", "1")
    monkeypatch.setenv("DEMOAPP_TEST_TOKEN", TEST_TOKEN)
    monkeypatch.delenv("BREAK_CAMPAIGN", raising=False)
    db.clear_caches()
    yield
    with contextlib.suppress(RuntimeError):
        db.get_engine().dispose()
    db.clear_caches()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def giris(c: TestClient, kullanici: str = "bayi1", parola: str = "Demo123!"):
    return c.post("/auth/login", json={"kullanici_adi": kullanici, "parola": parola})


@pytest.fixture
def bayi1(client):
    assert giris(client).status_code == 200
    return client
