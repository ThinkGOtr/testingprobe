"""Home "Sıfırla" Jira adımı (`jira_demo_sifirla`): jira-sim'e karşı, ağsız.

Prova izleri: TPD-8+ koşu kayıtları (etiketli, etiketi kaldırılmış, yabancı), TPD-5 ↔ TPD-1
bağlantısı, yanlış durumlar, ürün etiketleri, yorumlar. Sıfırlama hepsini B0 başlangıcına
döndürür; TPD-1..7 asla silinmez; silme izni yoksa kapatır.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from tp_core.integrations import jira_demo_sifirla as jds
from tp_core.integrations.jira import RestJira
from tp_core.integrations.jira_adf import text_to_adf

REPO = Path(__file__).resolve().parents[4]
SIM_SRC = REPO / "sims" / "jira-sim" / "src"
if str(SIM_SRC) not in sys.path:
    sys.path.insert(0, str(SIM_SRC))

from jira_sim.app import create_app  # noqa: E402

BASE = "http://jira-sim:8090"
WRITER = ("writer@sim.local", "t")


class SimTransport(httpx.BaseTransport):
    def __init__(self, sim: TestClient, *, izin_yok: bool = False) -> None:
        self.sim = sim
        self.izin_yok = izin_yok
        self.yazmalar: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if (
            self.izin_yok
            and request.method == "DELETE"
            and "/issue/" in request.url.path
            and ("/comment/" not in request.url.path)
        ):
            return httpx.Response(403, json={"errorMessages": ["You do not have permission"]})
        if self.izin_yok and request.url.path.endswith("/mypermissions"):
            return httpx.Response(
                200, json={"permissions": {"DELETE_ISSUES": {"havePermission": False}}}
            )
        if request.method != "GET" and not request.url.path.endswith("/search/jql"):
            self.yazmalar.append(f"{request.method} {request.url.path}")
        r = self.sim.request(
            request.method, str(request.url), headers=dict(request.headers), content=request.read()
        )
        return httpx.Response(r.status_code, headers=dict(r.headers), content=r.content)


@pytest.fixture
def sim() -> Iterator[TestClient]:
    with TestClient(create_app(data_path="", base_url=BASE, po_password="p"), base_url=BASE) as c:
        yield c


def _jira(sim: TestClient, **kw: bool) -> tuple[RestJira, SimTransport]:
    t = SimTransport(sim, **kw)
    return RestJira(BASE, ("reader@sim.local", "t"), WRITER, http=httpx.Client(transport=t)), t


@pytest.fixture(autouse=True)
def _sim_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", BASE)
    monkeypatch.setenv("JIRA_PROJECT", "TPD")


def _olustur(sim: TestClient, tur: str, etiketler: list[str]) -> str:
    r = sim.post(
        "/rest/api/3/issue",
        json={"fields": {"project": {"key": "TPD"}, "issuetype": {"name": tur},
                         "summary": f"prova {tur}", "labels": etiketler}},
        auth=WRITER,
    )  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()["key"]


def _gecis(sim: TestClient, key: str, durum: str) -> None:
    ts = sim.get(f"/rest/api/3/issue/{key}/transitions", auth=WRITER).json()["transitions"]
    t = next(x for x in ts if x["to"]["name"] == durum)
    r = sim.post(f"/rest/api/3/issue/{key}/transitions", json={"transition": {"id": t["id"]}},
                 auth=WRITER)  # fmt: skip
    assert r.status_code == 204, r.text


def _prova(sim: TestClient) -> list[str]:
    fazla = [
        _olustur(sim, "Test", ["AI-generated", "tp-0a1b2c3d-0000-4000-8000-000000000001"]),
        _olustur(sim, "Bug", ["AI-generated", "tp-mod-replay"]),  # uuid etiketi yok (Ö7)
        _olustur(sim, "Task", []),  # etiketsiz kalıntı
    ]
    _gecis(sim, fazla[1], "Done")
    r = sim.post(
        "/rest/api/3/issueLink",
        json={"type": {"name": "Relates"}, "inwardIssue": {"key": "TPD-5"},
              "outwardIssue": {"key": "TPD-1"}},
        auth=WRITER,
    )  # fmt: skip
    assert r.status_code == 201, r.text
    for key, durum in (("TPD-1", "To Do"), ("TPD-2", "In Progress"), ("TPD-7", "In Progress"),
                       ("TPD-5", "Done")):  # fmt: skip
        ts = sim.get(f"/rest/api/3/issue/{key}", auth=WRITER).json()["fields"]["status"]["name"]
        if ts != durum:
            _gecis(sim, key, durum)
    r = sim.put("/rest/api/3/issue/TPD-3", json={"update": {"labels": [
        {"add": "tp-mod-sablon"}, {"add": "tp-po-pending"}, {"add": "AI-generated"}]}},
        auth=WRITER)  # fmt: skip
    assert r.status_code == 204, r.text
    r = sim.post("/rest/api/3/issue/TPD-1/comment", json={"body": text_to_adf("prova")},
                 auth=WRITER)  # fmt: skip
    assert r.status_code == 201
    return fazla


def _durum(sim: TestClient, key: str) -> str:
    return sim.get(f"/rest/api/3/issue/{key}", auth=WRITER).json()["fields"]["status"]["name"]


def test_sifirla_b0_baslangicina_dondurur_ve_idempotent(sim: TestClient) -> None:
    fazla = _prova(sim)
    jira, t = _jira(sim)
    once = jds.dogrula(jira, "TPD")
    assert {k["kod"]: k["durum"] for k in once} == {
        "jira_durumlar": "hata", "jira_icerik": "hata", "jira_fazla": "hata"}  # fmt: skip

    s = jds.sifirla(jira, "TPD")
    assert s.hatalar == []
    assert s.silme_izni is True
    assert sorted(s.silinen) == sorted(fazla)  # etiketten bağımsız TPD-8+
    assert s.baglanti_kaldirilan == 1
    for key in fazla:
        assert sim.get(f"/rest/api/3/issue/{key}", auth=WRITER).status_code == 404
    for n, hedef in jds.HEDEF_DURUMLAR.items():
        assert _durum(sim, f"TPD-{n}") == hedef
    for n in range(1, 8):  # tohum kayıtları silinmez
        assert sim.get(f"/rest/api/3/issue/TPD-{n}", auth=WRITER).status_code == 200
    etiket = sim.get("/rest/api/3/issue/TPD-3", auth=WRITER).json()["fields"]["labels"]
    assert etiket == ["tp-demo"]
    sonra = jds.dogrula(jira, "TPD")
    assert all(k["durum"] == "tamam" for k in sonra), sonra

    t.yazmalar.clear()
    ikinci = jds.sifirla(jira, "TPD")
    assert ikinci.hatalar == [] and not ikinci.silinen and not ikinci.durum_tasinan
    assert t.yazmalar == []  # zaten başlangıçta: hiç yazma yok


def test_silme_izni_yoksa_kapatir_ve_etiketleri_kaldirir(sim: TestClient) -> None:
    fazla = _prova(sim)
    jira, _ = _jira(sim, izin_yok=True)
    s = jds.sifirla(jira, "TPD")
    assert s.silme_izni is False
    assert s.silinen == [] and sorted(s.kapatilan) == sorted(fazla)
    for key in fazla:
        f = sim.get(f"/rest/api/3/issue/{key}", auth=WRITER).json()["fields"]
        assert f["status"]["name"] == "Done"
        assert not [e for e in f["labels"] if e.startswith("tp-") or e == "AI-generated"]
    fazla_k = next(k for k in jds.dogrula(jira, "TPD") if k["kod"] == "jira_fazla")
    assert fazla_k["durum"] == "uyari"


def test_tek_kayitta_403_kapatmaya_duser(sim: TestClient) -> None:
    """İzin okunamaz/var görünür ama silme 403 verirse kayıt kapatılır."""
    fazla = _prova(sim)

    class Kismi(SimTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            if request.method == "DELETE" and request.url.path.endswith(f"/issue/{fazla[0]}"):
                return httpx.Response(403, json={"errorMessages": ["no"]})
            return super().handle_request(request)

    t = Kismi(sim)
    jira = RestJira(BASE, ("reader@sim.local", "t"), WRITER, http=httpx.Client(transport=t))
    s = jds.sifirla(jira, "TPD")
    assert s.kapatilan == [fazla[0]]
    assert sorted(s.silinen) == sorted(fazla[1:])
    assert s.hatalar == []


def test_cok_adimli_gecis_yolu() -> None:
    """Doğrudan geçiş yoksa ara durum üzerinden hedefe gider; yol yoksa hata."""

    class Akis:
        def __init__(self) -> None:
            self.durum = "Done"
            self.yol = {"Done": ["To Do"], "To Do": ["In Progress", "Done"],
                        "In Progress": ["Done", "To Do"]}  # fmt: skip

        def get_issue(self, key: str):
            return type("I", (), {"status": self.durum})()

        def transitions(self, key: str) -> list[dict]:
            return [{"id": d, "to": {"name": d}} for d in self.yol[self.durum]]

        def transition(self, key: str, tid: str) -> None:
            self.durum = tid

    a = Akis()
    assert jds.durum_tasi(a, "TPD-1", "In Progress") == "Done"  # type: ignore[arg-type]
    assert a.durum == "In Progress"
    b = Akis()
    b.yol = {"Done": []}
    with pytest.raises(Exception, match="geçiş yolu bulunamadı"):
        jds.durum_tasi(b, "TPD-1", "In Progress")  # type: ignore[arg-type]


def test_yasak_etiket_siniflandirmasi() -> None:
    assert not jds.yasak_etiket("tp-demo")
    assert jds.yasak_etiket("tp-mod-replay")
    assert jds.yasak_etiket("tp-po-approved")
    assert jds.yasak_etiket("AI-generated")
    assert not jds.yasak_etiket("musteri-isi")
