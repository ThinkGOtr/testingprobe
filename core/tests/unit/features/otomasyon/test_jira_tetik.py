"""Jira durum tetiği (specs/013-sprint-otomasyonu §3.4): "QA To Do"ya gelen story çekilir ve ön
incelemeye girer; çift tetik yok; ayar kapalıyken Jira'ya gidilmez; tek issue hatası turu
durdurmaz; tetikle akışa alınmış gereksinim PO etiketiyle onaylanınca case üretimi kendiliğinden
başlar (elle çekilmişte başlamaz). Gerçek Postgres, süreç içi jira-sim, REPLAY geçidi."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tp_core.features.cases import jobs as _case_jobs  # noqa: F401 — cases.generate işleyicisi
from tp_core.features.otomasyon import ayarlar, jira_tetik
from tp_core.features.requirements import flow
from tp_core.integrations.jira import JiraUnavailable, RestJira
from tp_core.models import Requirement, new_session, session_scope
from tp_core.ports import JiraIssue

from ..requirements.conftest import PoActions, login, run_jobs

pytestmark = pytest.mark.usefixtures("wired")

QA = "QA To Do"


def _tasi(jira: RestJira, key: str, durum: str = QA) -> None:
    gecis = next(t for t in jira.transitions(key) if t["to"]["name"] == durum)
    jira.transition(key, gecis["id"])


def _req(key: str) -> Requirement | None:
    with new_session() as s:
        return s.scalars(select(Requirement).where(Requirement.jira_key == key)).first()


def _ayar(**deger: Any) -> None:
    with session_scope() as s:
        ayarlar.yaz(s, ayarlar.JIRA_TETIK, deger, "test")


def _isler(engine: Engine, tur: str) -> list[Any]:
    with engine.connect() as c:
        return list(
            c.execute(
                text(
                    "SELECT id, durum, yuk, sonuc, run_after FROM job WHERE tur = :t "
                    "ORDER BY olusturma"
                ),
                {"t": tur},
            )
        )


def _denetim(engine: Engine, eylem: str) -> list[Any]:
    with engine.connect() as c:
        return list(
            c.execute(
                text("SELECT aktor, nesne, ozet FROM audit_event WHERE eylem = :e ORDER BY id"),
                {"e": eylem},
            )
        )


# ------------------------------------------------------------------------------ JQL


def test_durum_adi_tirnak_kacisi() -> None:
    assert jira_tetik.jql_dizesi("QA To Do") == '"QA To Do"'
    assert jira_tetik.jql_dizesi('QA "Hazır" \\ x') == r'"QA \"Hazır\" \\ x"'
    assert jira_tetik.jql_dizesi("a\nb") == '"a b"'
    assert (
        jira_tetik.tetik_jql("TPD", 'QA" OR project = X')
        == r'project = TPD AND issuetype = Story AND status = "QA\" OR project = X" '
        "ORDER BY key ASC"
    )
    with pytest.raises(flow.FlowInputError):
        jira_tetik.tetik_jql("TPD OR 1=1", QA)


class _SahteJira:
    def __init__(self, issues: list[JiraIssue] | None = None, hata: Exception | None = None):
        self.issues = issues or []
        self.hata = hata
        self.jql: list[str] = []

    def search(self, jql: str, max_results: int = 50) -> list[JiraIssue]:
        self.jql.append(jql)
        if self.hata:
            raise self.hata
        return list(self.issues)


def test_ayarlanan_durum_adi_kacisli_sorguya_girer(engine: Engine) -> None:
    _ayar(durum='QA "Hazır"')
    sahte = _SahteJira()
    ozet = jira_tetik.tur(engine, sahte)
    assert sahte.jql == [
        r'project = TPD AND issuetype = Story AND status = "QA \"Hazır\"" ORDER BY key ASC'
    ]
    assert ozet["bulunan"] == 0 and ozet["hata"] is None


# ------------------------------------------------------------------------- tetik turu


def test_yeni_issue_on_incelemeye_girer_ikinci_turda_cift_tetik_yok(
    engine: Engine, jira: RestJira
) -> None:
    _tasi(jira, "TPD-4")
    ozet = jira_tetik.tur(engine)
    assert ozet["acik"] is True and ozet["durum"] == QA
    assert ozet["bulunan"] == 1 and ozet["tetiklenen"] == 1 and ozet["hata"] is None
    assert ozet["tetiklenenler"] == ["TPD-4"]
    req = _req("TPD-4")
    assert req is not None and req.durum == "in_review"
    assert req.jira_durumu == QA and req.qa_tetik_zamani is not None
    assert _req("TPD-1") is None  # yalnız durumdaki story çekilir
    [d] = _denetim(engine, "requirements.jira_tetik")
    assert d.aktor == "jira-tetik" and d.ozet["jira_key"] == "TPD-4" and d.ozet["durum"] == QA
    [olusturma] = _denetim(engine, "requirement.created")
    assert olusturma.aktor == "jira-tetik"
    with engine.connect() as c:
        wf = c.execute(
            text("SELECT baslatan FROM workflow_instance WHERE nesne_id = :r"), {"r": req.id}
        ).scalar_one()
    assert wf == "otomasyon"
    ilk_zaman = req.qa_tetik_zamani

    # İkinci tur: çift tetik yok (in_review). İnceleme bitip pending_po'ya geçince de yok.
    ozet2 = jira_tetik.tur(engine)
    assert ozet2["tetiklenen"] == 0 and ozet2["sonuc"]["TPD-4"].startswith("dokunulmadi")
    run_jobs(engine)
    assert _req("TPD-4").durum == "pending_po"
    assert jira_tetik.tur(engine)["tetiklenen"] == 0
    assert len(_denetim(engine, "requirements.jira_tetik")) == 1
    assert _req("TPD-4").qa_tetik_zamani == ilk_zaman


def test_elle_cekilip_new_kalan_story_bir_kez_tetiklenir(
    api: TestClient, make_user: Any, engine: Engine, jira: RestJira
) -> None:
    login(api, make_user("analyst"))
    assert api.post("/requirements/sync").status_code == 200
    assert _req("TPD-3").durum == "new"
    _tasi(jira, "TPD-3")
    assert jira_tetik.tur(engine)["tetiklenenler"] == ["TPD-3"]
    assert _req("TPD-3").durum == "in_review"


def test_ayar_kapali_jiraya_gidilmez(engine: Engine, jira: RestJira) -> None:
    _tasi(jira, "TPD-4")
    _ayar(acik=False)
    sahte = _SahteJira()
    ozet = jira_tetik.tur(engine, sahte)
    assert ozet["acik"] is False and ozet["tetiklenen"] == 0 and sahte.jql == []
    assert jira_tetik.tur(engine)["bulunan"] == 0
    assert _req("TPD-4") is None


def test_jira_erisilemezse_tur_bos_gecer(engine: Engine) -> None:
    ozet = jira_tetik.tur(engine, _SahteJira(hata=JiraUnavailable("bağlantı yok")))
    assert ozet["bulunan"] == 0 and "Jira'ya erişilemedi" in ozet["hata"]


def test_bir_issue_hatasi_digerini_durdurmaz(
    engine: Engine, jira: RestJira, monkeypatch: pytest.MonkeyPatch
) -> None:
    _tasi(jira, "TPD-3")
    _tasi(jira, "TPD-4")
    asil = flow.upsert_issue

    def bozuk(session: Any, issue: Any, actor: Any) -> str:
        if issue.key == "TPD-3":
            raise RuntimeError("bozuk kayıt")
        return asil(session, issue, actor)

    monkeypatch.setattr(flow, "upsert_issue", bozuk)
    ozet = jira_tetik.tur(engine)
    assert ozet["bulunan"] == 2 and ozet["tetiklenenler"] == ["TPD-4"]
    assert ozet["hatalar"] == [{"jira_key": "TPD-3", "hata": "bozuk kayıt"}]
    assert "TPD-3" in ozet["hata"]
    assert _req("TPD-3") is None and _req("TPD-4").durum == "in_review"


def test_durumu_tutmayan_issue_atlanir(engine: Engine) -> None:
    issue = JiraIssue(key="TPD-9", issue_type="Story", summary="x", status="Done")
    ozet = jira_tetik.tur(engine, _SahteJira([issue]))
    assert ozet["bulunan"] == 0 and _req("TPD-9") is None


# ------------------------------------------------------------------ worker işi + API


def test_is_kendini_yeniden_planlar_ve_api_son_turu_gosterir(
    api: TestClient, make_user: Any, engine: Engine, jira: RestJira
) -> None:
    from tp_core.features.requirements import jobs

    with engine.begin() as c:
        jobs.on_worker_start(c)
        assert jira_tetik.ensure(c) is None  # tek bekleyen iş
    _tasi(jira, "TPD-4")
    sonuclar = run_jobs(engine, limit=1)  # po_poll ya da tetik; tetik koşana kadar işle
    for _ in range(3):
        if any(i.durum == "done" for i in _isler(engine, jira_tetik.JOB_JIRA_TETIK)):
            break
        sonuclar += run_jobs(engine, limit=1)
    isler = _isler(engine, jira_tetik.JOB_JIRA_TETIK)
    bitti = [i for i in isler if i.durum == "done"]
    assert len(bitti) == 1, sonuclar
    assert bitti[0].sonuc["tetiklenen"] == 1
    bekleyen = [i for i in isler if i.durum == "queued"]
    assert len(bekleyen) == 1
    assert bekleyen[0].run_after > flow.now() + timedelta(seconds=50)  # aralik_s = 60

    login(api, make_user("tester"))
    r = api.get("/automation/jira-trigger")
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["acik"] is True and g["durum"] == QA and g["aralik_s"] == 60
    assert g["son_tur"]["bulunan"] == 1 and g["son_tur"]["tetiklenen"] == 1
    assert g["son_tur"]["hata"] is None and g["son_tur"]["zaman"]
    assert [t["jira_key"] for t in g["son_tetiklenenler"]] == ["TPD-4"]
    assert g["son_tetiklenenler"][0]["zaman"]


def test_api_oturumsuz_401(api: TestClient) -> None:
    assert api.get("/automation/jira-trigger").status_code == 401


def test_ayar_kapaliyken_is_yalniz_yeniden_planlar(engine: Engine) -> None:
    from tp_core.features.requirements import jobs
    from tp_core.workflow.jobs import JobContext

    _ayar(acik=False, aralik_s=300)
    sonuc = jobs.jira_tetik_turu(JobContext(job_id=None, tur="x", yuk={}, deneme=1, max_deneme=1))
    assert sonuc["acik"] is False and sonuc["bulunan"] == 0
    [bekleyen] = _isler(engine, jira_tetik.JOB_JIRA_TETIK)
    assert bekleyen.durum == "queued"
    assert bekleyen.run_after > flow.now() + timedelta(seconds=290)


# ------------------------------------------------------------------ otomatik case üretimi


def _tetikle_ve_po_onayla(engine: Engine, jira: RestJira, po: PoActions) -> str:
    _tasi(jira, "TPD-4")
    assert jira_tetik.tur(engine)["tetiklenenler"] == ["TPD-4"]
    run_jobs(engine)
    req = _req("TPD-4")
    assert req.durum == "pending_po"
    time.sleep(0.01)
    po.add_label("TPD-4")
    assert flow.run_po_poll(engine)["kontrol"][str(req.id)] == "onaylandi"
    return str(req.id)


def test_po_onayi_tetikli_gereksinimde_case_uretimini_baslatir(
    engine: Engine, jira: RestJira, po: PoActions
) -> None:
    rid = _tetikle_ve_po_onayla(engine, jira, po)
    [is_] = _isler(engine, jira_tetik.JOB_OTOMATIK_CASE)
    assert is_.yuk["requirement_id"] == rid and is_.durum == "queued"
    run_jobs(engine)
    [is_] = _isler(engine, jira_tetik.JOB_OTOMATIK_CASE)
    assert is_.durum == "done" and is_.sonuc["durum"] == "baslatildi", is_.sonuc
    assert _req("TPD-4").durum == "cases_ready"
    [d] = _denetim(engine, "requirements.otomatik_case")
    assert d.ozet["sonuc"] == "baslatildi" and d.aktor == "jira-tetik"
    from tp_core.features.cases.service import WORKFLOW_TUR

    with engine.connect() as c:
        baslatan = c.execute(
            text("SELECT baslatan FROM workflow_instance WHERE nesne_id = :r AND tur = :t"),
            {"r": rid, "t": WORKFLOW_TUR},
        ).scalar_one()
    assert baslatan == "otomasyon"


def test_otomatik_case_kapaliyken_kuyruga_girmez(
    engine: Engine, jira: RestJira, po: PoActions
) -> None:
    _ayar(otomatik_case=False)
    _tetikle_ve_po_onayla(engine, jira, po)
    assert _isler(engine, jira_tetik.JOB_OTOMATIK_CASE) == []
    assert _req("TPD-4").durum == "po_approved"


def test_elle_cekilmis_gereksinimde_otomatik_case_yok(
    api: TestClient, make_user: Any, engine: Engine, po: PoActions
) -> None:
    login(api, make_user("analyst"))
    api.post("/requirements/sync")
    req = _req("TPD-4")
    assert api.post(f"/requirements/{req.id}/review").status_code == 202
    run_jobs(engine)
    assert _req("TPD-4").durum == "pending_po"
    time.sleep(0.01)
    po.add_label("TPD-4")
    assert flow.run_po_poll(engine)["kontrol"][str(req.id)] == "onaylandi"
    assert _req("TPD-4").qa_tetik_zamani is None
    assert _isler(engine, jira_tetik.JOB_OTOMATIK_CASE) == []
    run_jobs(engine)
    assert _req("TPD-4").durum == "po_approved"  # analist elle başlatır


def test_kapi_reddederse_denetim_ve_gereksinim_oldugu_gibi(
    engine: Engine, jira: RestJira, po: PoActions
) -> None:
    _tetikle_ve_po_onayla(engine, jira, po)
    # Onay işten önce Jira'da geri çekildi (poll henüz görmedi): kapı fail-closed reddeder.
    po.remove_label("TPD-4")
    run_jobs(engine)
    [is_] = _isler(engine, jira_tetik.JOB_OTOMATIK_CASE)
    assert is_.durum == "done" and is_.sonuc["durum"] == "reddedildi"
    [d] = _denetim(engine, "requirements.otomatik_case")
    assert d.ozet["sonuc"] == "reddedildi" and d.ozet["neden"]
    assert _req("TPD-4").durum == "po_approved"


# ------------------------------------------------------------------------ demo kontrolü


def test_demo_jira_status(
    api: TestClient, make_user: Any, engine: Engine, jira: RestJira, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.features.demo import service as demo_service

    login(api, make_user("analyst"))
    assert api.post("/demo/jira-status", json={"jira_key": "TPD-2", "durum": QA}).status_code == 403
    login(api, make_user("presenter"))
    r = api.post("/demo/jira-status", json={"jira_key": "TPD-2", "durum": QA})
    assert r.status_code == 200, r.text
    assert r.json() == {"jira_key": "TPD-2", "onceki": "To Do", "durum": QA, "degisti": True}
    assert jira.get_issue("TPD-2").status == QA
    again = api.post("/demo/jira-status", json={"jira_key": "TPD-2", "durum": "qa to do"})
    assert again.status_code == 200 and again.json()["degisti"] is False
    assert (
        api.post("/demo/jira-status", json={"jira_key": "TPD-2", "durum": "Yok"}).status_code == 409
    )
    assert (
        api.post("/demo/jira-status", json={"jira_key": "TPD-999", "durum": QA}).status_code == 404
    )
    assert api.post("/demo/jira-status", json={"jira_key": "x y", "durum": QA}).status_code == 404
    [d] = _denetim(engine, "demo.jira_status")
    assert d.nesne == "jira:TPD-2" and d.ozet == {"onceki": "To Do", "durum": QA}
    # Tetik onu çeker.
    assert jira_tetik.tur(engine)["tetiklenenler"] == ["TPD-2"]

    # Gerçek Jira: istek gönderilmeden 409.
    monkeypatch.setattr(demo_service, "_jira_sim_mi", lambda: False)
    r = api.post("/demo/jira-status", json={"jira_key": "TPD-1", "durum": QA})
    assert r.status_code == 409 and "jira-sim" in r.json()["detail"]
    assert jira.get_issue("TPD-1").status == "To Do"
