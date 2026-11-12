"""Onay sonrası otomatik kod üretimi (013 §3.2, K4) ve otomasyon ayarları API'si (§3.1)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from tests.unit.features.cases.helpers import (
    case_icerik,
    latest_cases,
    login,
    otomatik_kod_ayari,
    run_jobs,
)
from tp_core.audit import audit_on_commit
from tp_core.features.codegen import service as codegen_service
from tp_core.features.codegen import views
from tp_core.features.otomasyon import otokod
from tp_core.gateway.testing import text_response
from tp_core.models import AuditEvent, Job, Script, TestCase, session_scope
from tp_core.models.codegen_feature import ScriptCodegen


@pytest.fixture
def hazir(api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway):
    """2 draft case'li PO onaylı gereksinim + oturum açmış analist; otomatik kod AÇIK."""
    fake_gateway(
        [text_response({"cases": [case_icerik(), case_icerik(title="Hatalı parola", ref="AC2")]})]
    )
    rid = make_requirement()
    analist = make_user("analyst")
    login(api, analist)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    otomatik_kod_ayari(True)
    return rid, analist


def _onayla(api: TestClient, c: dict[str, Any]):
    return api.post(
        f"/cases/{c['id']}/decision", json={"karar": "approve", "icerik_hash": c["icerik_hash"]}
    )


def _scriptler(cid: str) -> list[ScriptCodegen]:
    with session_scope() as s:
        return list(
            s.scalars(select(ScriptCodegen).where(ScriptCodegen.test_case_id == uuid.UUID(cid)))
        )


def _denetim(eylem: str) -> list[AuditEvent]:
    with session_scope() as s:
        return list(s.scalars(select(AuditEvent).where(AuditEvent.eylem == eylem)))


def test_ayar_acik_onay_otomatik_script_olusturur(api: TestClient, hazir) -> None:
    rid, analist = hazir
    c = latest_cases(api, rid)[0]
    r = _onayla(api, c)
    assert r.status_code == 200, r.text
    ok = r.json()["otomatik_kod"]
    assert ok["durum"] == "kuyrukta" and ok["script_id"] and ok["neden"] is None
    assert r.json()["durum"] == "approved"
    [cg] = _scriptler(c["id"])
    assert cg.tetik == "otomatik" and str(cg.script_id) == ok["script_id"]
    with session_scope() as s:
        sc = s.get(Script, cg.script_id)
        assert sc.platform == "web"
        assert views.serialize(s, sc, cg)["tetik"] == "otomatik"
        job = s.get(Job, cg.job_id)
        assert job.yuk["baslatan"]["kullanici_adi"] == "otomasyon"
        assert job.yuk["tetikleyen"] == analist.kullanici_adi and job.yuk["tetik"] == "otomatik"
    [d] = _denetim("codegen.requested")
    assert d.aktor == "otomasyon" and d.ozet["tetikleyen"] == analist.kullanici_adi

    # Aynı içerik için süren üretim varken ikinci çağrı yeni script açmaz.
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(c["id"]))
        assert otokod.kuyruga_al(s, tc, analist)["durum"] == "atlandi"
    assert len(_scriptler(c["id"])) == 1


def test_duzelt_karari_da_tetikler(api: TestClient, hazir) -> None:
    rid, _ = hazir
    c = latest_cases(api, rid)[0]
    yeni = {**c["icerik"], "title": c["icerik"]["title"] + " yapılır"}
    r = api.post(
        f"/cases/{c['id']}/decision",
        json={"karar": "edit", "icerik_hash": c["icerik_hash"], "icerik": yeni},
    )
    assert r.status_code == 200, r.text
    assert r.json()["otomatik_kod"]["durum"] == "kuyrukta"


def test_ret_karari_tetiklemez(api: TestClient, hazir) -> None:
    rid, _ = hazir
    c = latest_cases(api, rid)[0]
    r = api.post(
        f"/cases/{c['id']}/decision",
        json={"karar": "reject", "icerik_hash": c["icerik_hash"], "ret_nedeni": "duplicate"},
    )
    assert r.status_code == 200 and r.json()["otomatik_kod"] is None
    assert _scriptler(c["id"]) == []


def test_ayar_kapali_script_olusmaz(api: TestClient, hazir) -> None:
    rid, _ = hazir
    otomatik_kod_ayari(False)
    c = latest_cases(api, rid)[0]
    r = _onayla(api, c)
    assert r.status_code == 200, r.text
    assert r.json()["otomatik_kod"]["durum"] == "kapali"
    assert _scriptler(c["id"]) == []


def test_codegen_reddi_onayi_geri_almaz(
    api: TestClient, hazir, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid, _ = hazir
    monkeypatch.setattr(codegen_service, "replay_temel_durum_engeli", lambda: "REPLAY engeli")
    c = latest_cases(api, rid)[0]
    r = _onayla(api, c)
    assert r.status_code == 200, r.text
    ok = r.json()["otomatik_kod"]
    assert ok["durum"] == "reddedildi" and "REPLAY engeli" in ok["neden"]
    assert r.json()["durum"] == "approved"
    assert _scriptler(c["id"]) == []
    with session_scope() as s:
        assert s.get(TestCase, uuid.UUID(c["id"])).durum == "approved"


def test_beklenmeyen_hata_onayi_geri_almaz_ve_denetlenir(
    api: TestClient, hazir, monkeypatch: pytest.MonkeyPatch
) -> None:
    rid, _ = hazir

    def patlayan(session, case_ids, user, **_kw):
        # SAVEPOINT içinde yazılan satır ve denetim kaydı geri alınmalı.
        session.add(Script(tur="test", dosya_yolu="x.spec.ts", platform="web"))
        session.flush()
        audit_on_commit(session, "otomasyon", "codegen.requested", "script:x", {})
        raise RuntimeError("beklenmedik")

    monkeypatch.setattr(otokod, "start_generation", patlayan)
    c = latest_cases(api, rid)[0]
    r = _onayla(api, c)
    assert r.status_code == 200, r.text
    assert r.json()["otomatik_kod"]["durum"] == "hata"
    with session_scope() as s:
        assert s.get(TestCase, uuid.UUID(c["id"])).durum == "approved"
        assert s.scalars(select(Script).where(Script.dosya_yolu == "x.spec.ts")).first() is None
    assert _denetim("codegen.requested") == []
    [d] = _denetim("codegen.otomatik_hata")
    assert d.aktor == "otomasyon" and d.nesne == f"test_case:{c['id']}"


def test_toplu_onayda_otomatik_kod(api: TestClient, hazir) -> None:
    rid, _ = hazir
    cs = latest_cases(api, rid)
    for c in cs:
        assert api.post(f"/cases/{c['id']}/viewed").status_code == 200
    r = api.post(
        "/cases/bulk-decision",
        json={
            "karar": "approve",
            "ogeler": [{"case_id": c["id"], "icerik_hash": c["icerik_hash"]} for c in cs],
        },
    )
    assert r.status_code == 200, r.text
    assert [s["otomatik_kod"]["durum"] for s in r.json()["sonuclar"]] == ["kuyrukta"] * 2
    assert all(_scriptler(c["id"])[0].tetik == "otomatik" for c in cs)


# --------------------------------------------------------------------- ayar API'si


def test_ayar_api_rol_kapisi_ve_dogrulama(api: TestClient, make_user) -> None:
    login(api, make_user("po"))
    r = api.get("/automation-settings")
    assert r.status_code == 200, r.text
    assert r.json()["otomatik_kod_uretimi"]["acik"] is False  # fikstür kapalı başlatır
    assert r.json()["jira_tetik"]["durum"] == "QA To Do"
    r = api.put("/automation-settings/otomatik_kod_uretimi", json={"acik": True})
    assert r.status_code == 403

    muhendis = make_user("engineer")
    login(api, muhendis)
    r = api.put("/automation-settings/otomatik_kod_uretimi", json={"acik": True})
    assert r.status_code == 200, r.text
    assert r.json()["otomatik_kod_uretimi"]["acik"] is True
    assert r.json()["otomatik_kod_uretimi"]["guncelleyen"] == muhendis.kullanici_adi

    login(api, make_user("engineer"))  # durum alanı yalnız engineer (K14)
    r = api.put("/automation-settings/jira_tetik", json={"aralik_s": 120, "durum": "QA Hazır"})
    assert r.status_code == 200, r.text
    j = r.json()["jira_tetik"]
    assert j["aralik_s"] == 120 and j["durum"] == "QA Hazır" and j["acik"] is True

    r = api.put("/automation-settings/yok", json={"acik": True})
    assert r.status_code == 404 and "Bilinmeyen" in r.json()["detail"]
    for govde in ({"aralik_s": 5}, {"acik": "evet"}, {"bilinmeyen": 1}):
        r = api.put("/automation-settings/jira_tetik", json=govde)
        assert r.status_code == 422, (govde, r.text)
        assert "Geçersiz ayar" in r.json()["detail"]
    assert api.put("/automation-settings/jira_tetik", json=[1]).status_code == 422
    assert api.get("/automation-settings").json()["jira_tetik"]["aralik_s"] == 120
    assert len(_denetim("otomasyon.ayar")) == 2
