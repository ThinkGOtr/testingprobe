"""Ajan ürünü bağlama ve Agent Probe ajan testi talebi (011 F6, K10; §4.4 A satırları).

Gerçek Postgres + gerçek API; Agent Probe süreç içi simülatör (`PgDeposu`: kayıt `ajan_testi_talebi`
satırı), denetlenebilir saat. Durum geçişleri: queued → running → passed (gereksinim `done`) |
failed (bulgu, gereksinim `po_approved` kalır); case üretimi bağlı gereksinimde 409."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.unit.features.cases.helpers import login
from tp_core.audit import verify_chain
from tp_core.integrations.agent_probe import set_agent_probe_factory
from tp_core.integrations.agent_probe.sim import PgDeposu, SimAgentProbe, SimAjanTestleri
from tp_core.models import Requirement, session_scope


class Saat:
    def __init__(self) -> None:
        self.t = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.t


@pytest.fixture
def saat(db) -> Iterator[Saat]:
    s = Saat()
    set_agent_probe_factory(lambda: SimAgentProbe(SimAjanTestleri(PgDeposu(), saat=s)))
    yield s
    set_agent_probe_factory(None)


@pytest.fixture
def analist(api: TestClient, make_user) -> TestClient:
    login(api, make_user("analyst"))
    return api


def _ilerlet(saat: Saat, s: float) -> None:
    saat.t = saat.t + timedelta(seconds=s)


def test_urun_listesi_yalniz_hazir(analist: TestClient, saat: Saat) -> None:
    r = analist.get("/agent-probe/products")
    assert r.status_code == 200, r.text
    veri = r.json()
    assert veri["simulasyon"] is True and veri["kip"] == "sim"
    assert [u["kod"] for u in veri["urunler"]] == ["destek-asistani", "kredi-danismani"]


def test_gecen_ajan_testi_gereksinimi_tamamlar(
    analist: TestClient, saat: Saat, make_requirement, engine
) -> None:
    rid = make_requirement()
    r = analist.put(f"/requirements/{rid}/agent-product", json={"urun_kodu": "destek-asistani"})
    assert r.status_code == 200, r.text
    assert r.json()["urun_kodu"] == "destek-asistani" and r.json()["baslatilabilir"]

    # Bağlı gereksinimde case üretimi reddedilir.
    r = analist.post(f"/requirements/{rid}/generate-cases")
    assert r.status_code == 409 and r.json()["kod"] == "ajan_urunu", r.text

    r = analist.post(f"/requirements/{rid}/agent-test")
    assert r.status_code == 202, r.text
    talep = r.json()["talep"]
    assert talep["durum"] == "queued" and talep["talep_no"].startswith(f"APT-{saat.t.year}-")
    assert talep["simulasyon"] is True and not r.json()["baslatilabilir"]
    # Süren talep varken ikinci talep ve bağlantı değişikliği reddedilir.
    assert analist.post(f"/requirements/{rid}/agent-test").status_code == 409
    r = analist.put(f"/requirements/{rid}/agent-product", json={"urun_kodu": None})
    assert r.status_code == 409

    _ilerlet(saat, 10)
    assert analist.get(f"/requirements/{rid}/agent-test").json()["talep"]["durum"] == "running"
    _ilerlet(saat, 60)
    v = analist.get(f"/requirements/{rid}/agent-test").json()
    assert v["talep"]["durum"] == "passed" and v["talep"]["surec"] == "tamamlandi"
    assert v["talep"]["sonuc"]["gecen"] == 3
    with session_scope() as s:
        assert s.get(Requirement, rid).durum == "done"
    # Yeniden sorgu idempotent (bir kez işlenir).
    assert analist.get(f"/requirements/{rid}/agent-test").json()["talep"] == v["talep"]
    with engine.connect() as c:
        eylemler = [
            r[0]
            for r in c.execute(
                text("SELECT eylem FROM audit_event WHERE nesne = :n ORDER BY id"),
                {"n": f"requirement:{rid}"},
            )
        ]
    for e in (
        "agent_probe.urun_baglandi",
        "agent_probe.test_baslatildi",
        "agent_probe.test_durumu",
        "agent_probe.sonuc_islendi",
        "requirement.transition",
    ):
        assert e in eylemler, eylemler
    assert eylemler.count("agent_probe.sonuc_islendi") == 1
    with engine.connect() as c:
        assert verify_chain(c).ok


def test_kalan_ajan_testi_bulgu_ve_yeniden_test(
    analist: TestClient, saat: Saat, make_requirement
) -> None:
    rid = make_requirement()
    analist.put(f"/requirements/{rid}/agent-product", json={"urun_kodu": "kredi-danismani"})
    analist.post(f"/requirements/{rid}/agent-test")
    _ilerlet(saat, 200)
    v = analist.get(f"/requirements/{rid}/agent-test").json()
    assert v["talep"]["durum"] == "failed" and v["talep"]["surec"] == "bulgu"
    assert v["talep"]["sonuc"]["kalan"] == 2
    with session_scope() as s:
        assert s.get(Requirement, rid).durum == "po_approved"
    assert v["baslatilabilir"]
    r = analist.post(f"/requirements/{rid}/agent-test")
    assert r.status_code == 202
    v = r.json()
    assert v["talep"]["durum"] == "queued" and len(v["gecmis"]) == 1
    assert v["talep"]["talep_no"] != v["gecmis"][0]["talep_no"]


def test_yetki_ve_engeller(api: TestClient, saat: Saat, make_requirement, make_user) -> None:
    rid = make_requirement(po_onayli=False)
    login(api, make_user("tester"))
    r = api.put(f"/requirements/{rid}/agent-product", json={"urun_kodu": "destek-asistani"})
    assert r.status_code == 403
    login(api, make_user("analyst"))
    r = api.put(f"/requirements/{rid}/agent-product", json={"urun_kodu": "kampanya-onerici"})
    assert r.status_code == 409 and r.json()["kod"] == "ajan_urunu_baglanamaz"
    r = api.put(f"/requirements/{rid}/agent-product", json={"urun_kodu": "destek-asistani"})
    assert r.status_code == 200
    v = api.get(f"/requirements/{rid}/agent-test").json()
    assert not v["baslatilabilir"] and "PO onaylı" in v["engel"]
    r = api.post(f"/requirements/{rid}/agent-test")
    assert r.status_code == 409 and r.json()["kod"] == "ajan_testi_baslatilamaz"
    assert api.get(f"/requirements/{uuid.uuid4()}/agent-test").status_code == 404


def test_icerik_degisirse_gecen_test_gereksinimi_ilerletmez(
    analist: TestClient, saat: Saat, make_requirement
) -> None:
    rid = make_requirement()
    analist.put(f"/requirements/{rid}/agent-product", json={"urun_kodu": "destek-asistani"})
    analist.post(f"/requirements/{rid}/agent-test")
    with session_scope() as s:
        s.get(Requirement, rid).aciklama = "Değişti"
    _ilerlet(saat, 100)
    v = analist.get(f"/requirements/{rid}/agent-test").json()
    assert v["talep"]["durum"] == "passed" and v["talep"]["surec"] == "onay_gecersiz"
    with session_scope() as s:
        assert s.get(Requirement, rid).durum == "po_approved"


def test_case_varken_baglanamaz(analist: TestClient, saat: Saat, make_requirement, engine) -> None:
    rid = make_requirement()
    with session_scope() as s:
        s.execute(
            text(
                "INSERT INTO test_case (id, requirement_id, sira_no, icerik, icerik_hash) "
                "VALUES (gen_random_uuid(), :r, 1, '{}'::jsonb, 'h')"
            ),
            {"r": rid},
        )
    r = analist.put(f"/requirements/{rid}/agent-product", json={"urun_kodu": "destek-asistani"})
    assert r.status_code == 409, r.text
