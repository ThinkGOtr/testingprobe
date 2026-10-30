from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from jira_sim.app import create_app

PO_PASSWORD = "po-test-parola"
ADMIN_TOKEN = "admin-test-belirteci"
SIM_BASE = "http://jira-sim:8090"

READER = ("reader@sim.local", "any-token")
WRITER = ("writer@sim.local", "any-token")
PO = ("po@sim.local", PO_PASSWORD)
ADMIN = {"X-Sim-Admin-Token": ADMIN_TOKEN}


@pytest.fixture
def client() -> TestClient:
    """Simülatör (yönetim belirteci tanımlı değil: ``/sim/*`` yalnızca köken denetimiyle)."""
    return TestClient(create_app(data_path="", base_url=SIM_BASE, po_password=PO_PASSWORD))


def csrf_of(page: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m, "sayfada CSRF belirteci yok (PO girişi yapılmamış olabilir)"
    return m.group(1)


def login_po(client: TestClient, key: str = "TPD-1") -> str:
    """PO olarak giriş yapar; ``key`` sayfasındaki CSRF belirtecini döner."""
    r = client.post(
        "/giris", data={"password": PO_PASSWORD, "sonra": f"/browse/{key}"}, follow_redirects=False
    )
    assert r.status_code == 303, r.text
    return csrf_of(client.get(f"/browse/{key}").text)


@pytest.fixture
def po_client(client: TestClient) -> tuple[TestClient, str]:
    """PO olarak giriş yapmış istemci ve CSRF belirteci."""
    return client, login_po(client)
