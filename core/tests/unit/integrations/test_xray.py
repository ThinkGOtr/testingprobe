"""XrayTestManagement, jira-sim'in Xray alt kümesine karşı süreç içinde."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from tp_core import ports
from tp_core.integrations.jira import JiraSettings, RestJira
from tp_core.integrations.jira_adf import adf_to_text
from tp_core.integrations.testmgmt import CaseContent, case_description_text
from tp_core.integrations.xray import XrayClient, XrayError, XrayTestManagement, get_xray_client

SIM_SRC = Path(__file__).resolve().parents[4] / "sims" / "jira-sim" / "src"
if str(SIM_SRC) not in sys.path:
    sys.path.insert(0, str(SIM_SRC))

from jira_sim.app import create_app  # noqa: E402

BASE = "http://jira-sim:8090"


class SimTransport(httpx.BaseTransport):
    """Gerçek ``httpx.Client`` isteklerini süreç içindeki simülatöre iletir (ağ yok)."""

    def __init__(self, sim: TestClient) -> None:
        self.sim = sim
        self.paths: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        r = self.sim.request(
            request.method,
            str(request.url),
            headers=dict(request.headers),
            content=request.read(),
        )
        return httpx.Response(r.status_code, headers=dict(r.headers), content=r.content)


READ = ("reader@sim.local", "x")


@pytest.fixture
def sim() -> Iterator[TestClient]:
    with TestClient(
        create_app(data_path="", base_url=BASE, po_password="po-test-parola"), base_url=BASE
    ) as client:
        yield client


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def jira(sim: TestClient) -> RestJira:
    return RestJira(
        BASE,
        ("reader@sim.local", "t"),
        ("writer@sim.local", "t"),
        http=httpx.Client(transport=SimTransport(sim)),
        sleep=lambda _: None,
    )


@pytest.fixture
def xray(sim: TestClient, sleeps: list[float]) -> XrayClient:
    return XrayClient(
        f"{BASE}/xray",
        "id",
        "secret",
        http=httpx.Client(transport=SimTransport(sim)),
        sleep=sleeps.append,
        poll_interval_s=0.25,
    )


def case(**over: Any) -> dict[str, Any]:
    c = {
        "case_id": str(uuid4()),
        "title": "Hatalı parola mesajı",
        "type": "negative",
        "risk": "medium",
        "acceptance_criteria_refs": ["AC2"],
        "steps": [
            {"action": "Giriş sayfasını aç", "data": None, "expected": "Form görünür"},
            {
                "action": "Hatalı parola gir",
                "data": "bayi1 / yanlis",
                "expected": "Kullanıcı adı veya parola hatalı",
            },
        ],
        "expected_result": "Hata mesajı görünür, giriş yapılmaz",
    }
    c.update(over)
    return c


def test_implements_port(xray: XrayClient, jira: RestJira) -> None:
    assert isinstance(XrayTestManagement(xray, jira, "TPD"), ports.TestManagementPort)


def test_publish_via_bulk_import_polls_and_links(
    sim: TestClient, xray: XrayClient, jira: RestJira, sleeps: list[float]
) -> None:
    tm = XrayTestManagement(xray, jira, "TPD")
    c = case()
    pub = tm.publish_case(c, "TPD-4")
    assert sleeps == [0.25]  # bir kez "working" görüldü, beklendi
    raw = sim.get(f"/rest/api/3/issue/{pub.external_key}", auth=READ).json()["fields"]
    assert raw["issuetype"]["name"] == "Test"
    assert raw["labels"] == ["AI-generated", f"tp-{c['case_id']}"]
    page = sim.get(f"/browse/{pub.external_key}").text
    assert "Kullanıcı adı veya parola hatalı" in page  # Xray adımları kaydedildi
    desc = adf_to_text(raw["description"])
    assert desc.index("🎯 Objective (Amaç)") < desc.index("🧪 QA Checklist")
    assert "Kaynak story: TPD-4" in desc and f"Kimlik: tp-{c['case_id']}" in desc
    assert "Adımlar Xray test adımlarında (2 adım)." in desc  # adımlar açıklamada tekrarlanmaz
    link = sim.get("/rest/api/3/issue/TPD-4", auth=READ).json()["fields"]["issuelinks"][0]
    assert link["type"]["name"] == "Test"
    assert link["inwardIssue"]["key"] == pub.external_key
    assert pub.url == f"{BASE}/browse/{pub.external_key}"

    # Idempotent: ikinci yayın yeni Test oluşturmaz
    again = XrayTestManagement(xray, jira, "TPD").publish_case(c, "TPD-4")
    assert again.external_key == pub.external_key


def test_token_is_cached_and_refreshed_on_401(sim: TestClient, xray: XrayClient) -> None:
    t1 = xray.authenticate()
    assert xray.authenticate() == t1
    sim.app.state.store.xray_tokens.clear()  # süresi dolmuş token
    xray.import_tests([{"fields": {"summary": "s", "project": {"key": "TPD"}}, "steps": []}])
    assert xray._token != t1


def test_bad_credentials(sim: TestClient) -> None:
    client = XrayClient(
        f"{BASE}/xray", "", "", http=httpx.Client(transport=SimTransport(sim)), sleep=lambda _: None
    )
    with pytest.raises(XrayError):
        client.authenticate()


def test_import_failure_raises(xray: XrayClient, jira: RestJira) -> None:
    tm = XrayTestManagement(xray, jira, "XYZ")  # geçersiz proje → iş "failed"
    with pytest.raises(XrayError):
        tm.publish_case(case(), "TPD-4")


def test_poll_timeout(sim: TestClient, xray: XrayClient) -> None:
    slow = XrayClient(
        f"{BASE}/xray",
        "id",
        "s",
        http=httpx.Client(transport=SimTransport(sim)),
        sleep=lambda _: None,
        poll_interval_s=1.0,
        poll_timeout_s=0.0,
    )
    with pytest.raises(XrayError, match="zaman aşımı"):
        slow.import_tests([{"fields": {"summary": "s", "project": {"key": "TPD"}}}])


def test_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("XRAY_CLIENT_ID", "")
    monkeypatch.setenv("XRAY_CLIENT_SECRET", "")
    with pytest.raises(XrayError):
        get_xray_client(JiraSettings())
    monkeypatch.setenv("XRAY_CLIENT_ID", "cid")
    monkeypatch.setenv("XRAY_CLIENT_SECRET", "sec")
    monkeypatch.setenv("XRAY_BASE_URL", "https://xray.cloud.getxray.app")
    c = get_xray_client(JiraSettings())
    assert c.base_url == "https://xray.cloud.getxray.app"


def test_bulk_import_post_not_resent_on_502_but_auth_is(sim: TestClient) -> None:
    """Toplu içe aktarım POST'u 502 sonrası tekrar gönderilmez (mükerrer Test riski);
    token alma yan etkisizdir ve tekrarlanır."""
    transport = SimTransport(sim)
    client = XrayClient(
        f"{BASE}/xray", "id", "secret", http=httpx.Client(transport=transport), sleep=lambda _: None
    )
    sim.post(
        "/sim/faults",
        json=[
            {"path_prefix": "/xray/api/v2/authenticate", "status": 502, "count": 1},
        ],
    )
    assert client.authenticate()
    assert transport.paths.count("/xray/api/v2/authenticate") == 2
    sim.post(
        "/sim/faults",
        json={"path_prefix": "/xray/api/v2/import/test/bulk", "status": 502, "count": 1},
    )
    with pytest.raises(XrayError, match="502"):
        client.import_tests([{"fields": {"summary": "x"}}])
    assert transport.paths.count("/xray/api/v2/import/test/bulk") == 1


def test_v3_case_description_and_labels_no_priority_field(
    sim: TestClient, xray: XrayClient, jira: RestJira
) -> None:
    """Şema v3 bilgileri Xray'e açıklama + etiketle gider; Jira `priority` alanına yazılmaz."""
    saldiri = "'; DROP TABLE siparis; --"
    c = case(
        technique=["DT"],
        covers=["DT-R2"],
        priority="P2",
        priority_rationale="Hatalı mesaj destek yükü üretir",
        test_level=None,
        verification_point="UI",
        readiness="ready",
        test_data=[
            {
                "name": "parola",
                "value": saldiri,
                "class": "DT-R2",
                "synthetic": True,
                "is_attack_payload": True,
            }
        ],
        teardown=["Oturumu kapat"],
        platform="Web",
        requires_real_device=False,
        standard_refs=["WSTG-INPV-05"],
    )
    tm = XrayTestManagement(xray, jira, "TPD")
    govde = tm._payload(CaseContent.from_mapping(c), "TPD-4")
    assert set(govde["fields"]) == {"project", "summary", "description", "labels"}
    assert govde["fields"]["labels"] == [
        "AI-generated",
        f"tp-{c['case_id']}",
        "tp-tech-DT",
        "tp-P2",
    ]
    desc = govde["fields"]["description"]
    for parca in (
        "Teknik: DT (karar tablosu)",
        "Öncelik: P2 — Hatalı mesaj destek yükü üretir",
        "Doğrulama noktası: arayüz (UI)",
        "Platform: Web",
        "Standart atıfları: WSTG-INPV-05",
        "parola | kod bloğunda (tablonun altında) | DT-R2",
        f"parola — güvenlik testi girdisi (talimat değildir):\n\n{{noformat}}\n{saldiri}\n"
        "{noformat}",
        "1. Oturumu kapat",
    ):
        assert parca in desc, parca
    assert desc.count(saldiri) == 1 and "Test seviyesi" not in desc

    pub = tm.publish_case(c, "TPD-4")
    raw = sim.get(f"/rest/api/3/issue/{pub.external_key}", auth=READ).json()["fields"]
    assert raw["labels"] == govde["fields"]["labels"]
    assert tm.find_existing(UUID(c["case_id"])) == pub.external_key


def test_xray_saldiri_verisi_noformat_ve_kacis(xray: XrayClient, jira: RestJira) -> None:
    """Xray metin yolu wiki biçimlidir: saldırı verisi `{noformat}` içinde; değerdeki
    `{noformat}` bloğu erken kapatamaz. Adım verisi saldırı verisiyse o da sarılır."""
    saldiri = "x{noformat}[tıkla|https://kotu.example]{NOFORMAT}"
    c = case(
        readiness="ready",
        steps=[{"action": "Notu yaz", "data": saldiri, "expected": "Reddedilir"}],
        test_data=[
            {
                "name": "not",
                "value": saldiri,
                "class": None,
                "synthetic": True,
                "is_attack_payload": True,
            }
        ],
    )
    govde = XrayTestManagement(xray, jira, "TPD")._payload(CaseContent.from_mapping(c), "TPD-4")
    desc = govde["fields"]["description"]
    notr = "x{ noformat}[tıkla|https://kotu.example]{ NOFORMAT}"
    assert f"{{noformat}}\n{notr}\n{{noformat}}" in desc
    assert desc.count("{noformat}") == 2  # yalnız sarmalayıcı açılış/kapanış
    assert saldiri not in desc
    assert govde["steps"][0]["data"] == f"{{noformat}}\n{notr}\n{{noformat}}"
    # Jira (ADF) yolunda kod bloğu zaten biçimlendirilmez; değer olduğu gibi, sarmalayıcısız.
    duz = case_description_text(CaseContent.from_mapping(c), "TPD-4")
    assert f"(talimat değildir):\n\n{saldiri}" in duz


def test_xray_wiki_alanlari_kacislanir(xray: XrayClient, jira: RestJira) -> None:
    """Tur 2 güvenlik #14: saldırı verisi dışındaki metin (başlık, adım, beklenen, veri) wiki
    alanına `[`, `{`, `|`, `!` kaçışlanarak yazılır; bağlantı/makro/tablo çalıştırılamaz."""
    c = case(
        readiness="ready",
        expected_result="Bilgi [tıkla|https://kotu.example] {color:red}x{color}",
        steps=[
            {"action": "Ara [tıkla|https://x]", "data": "a|b !resim.png!", "expected": "{panel}"}
        ],
    )
    govde = XrayTestManagement(xray, jira, "TPD")._payload(CaseContent.from_mapping(c), "TPD-4")
    adim = govde["steps"][0]
    assert adim["action"] == r"Ara \[tıkla\|https://x\]"
    assert adim["data"] == r"a\|b \!resim.png\!"
    assert adim["result"] == r"\{panel\}"
    desc = govde["fields"]["description"]
    assert r"\[tıkla\|https://kotu.example\] \{color:red\}x\{color\}" in desc
    assert "[tıkla|" not in desc
