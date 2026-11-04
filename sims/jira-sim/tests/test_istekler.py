"""İstek sayacı (``/sim/istekler``) ve kısıtlı yorum provası (AI-ASISTAN-PLANI §5.6, §13)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from jira_sim.adf import text_to_adf
from tests.conftest import READER, SIM_BASE, WRITER

R = "/rest/api/3"
AYNI_KOKEN = {"Origin": SIM_BASE}


def test_sayac_yontem_ve_yol_sayar_sim_uclarini_saymaz(client: TestClient) -> None:
    assert client.get("/sim/istekler").json() == {"toplam": 0, "yontemler": {}, "son": []}
    client.get(f"{R}/issue/TPD-1", auth=READER)
    client.get(f"{R}/issue/TPD-1/comment?maxResults=1", auth=READER)
    client.post(f"{R}/issue/TPD-1/comment", json={"body": text_to_adf("x")}, auth=WRITER)
    client.get("/health")
    client.get("/sim/config")
    s = client.get("/sim/istekler").json()
    assert s["toplam"] == 3
    assert s["yontemler"] == {"GET": 2, "POST": 1}
    assert s["son"][1] == {"yontem": "GET", "yol": f"{R}/issue/TPD-1/comment"}  # sorgu yok


def test_sayac_hata_enjeksiyonuyla_reddedileni_de_sayar_ve_sifirlanir(client: TestClient) -> None:
    client.post(
        "/sim/faults",
        json={"path_prefix": f"{R}/issue", "status": 503, "count": 1},
        headers=AYNI_KOKEN,
    )
    assert client.get(f"{R}/issue/TPD-1", auth=READER).status_code == 503
    assert client.get("/sim/istekler").json()["yontemler"] == {"GET": 1}
    assert client.post("/sim/istekler/sifirla", headers=AYNI_KOKEN).status_code == 200
    assert client.get("/sim/istekler").json()["toplam"] == 0


def test_sifirlama_baska_kokenden_reddedilir(client: TestClient) -> None:
    r = client.post("/sim/istekler/sifirla", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_kisitli_yorumlar_aynen_doner(client: TestClient) -> None:
    govde = text_to_adf("iç not")
    r = client.post(
        f"{R}/issue/TPD-2/comment",
        json={"body": govde, "visibility": {"type": "role", "value": "Administrators"}},
        auth=WRITER,
    )
    assert r.status_code == 201
    assert r.json()["visibility"] == {"type": "role", "value": "Administrators"}
    r = client.post(
        f"{R}/issue/TPD-2/comment", json={"body": govde, "jsdPublic": False}, auth=WRITER
    )
    assert r.json()["jsdPublic"] is False
    yorumlar = client.get(f"{R}/issue/TPD-2/comment", auth=READER).json()["comments"]
    assert yorumlar[-1]["jsdPublic"] is False and "visibility" not in yorumlar[-1]
    assert yorumlar[-2]["visibility"]["type"] == "role"
    r = client.post(
        f"{R}/issue/TPD-2/comment",
        json={"body": govde, "visibility": {"type": "x", "value": 1}},
        auth=WRITER,
    )
    assert r.status_code == 400
