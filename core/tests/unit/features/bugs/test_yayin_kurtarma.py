"""Kalıcı başarısız yayından kurtulma ve testçi kararının triage öneri durumuna yansıması.

- Test issue bağlantısı 404 verirse (her denemede) son denemeden sonra taslak `approved → draft`
  döner; Jira'ya kısmen yazılan kayıt `yayin.key`'de kalır, aynı içerikle yeniden `new` kararı
  aynı Bug'ı yeniden kullanır (ikinci Bug yok), `link` yorumu ikinci kez yazılmaz.
- Eski sürümde takılmış (approved + yayın başarısız, bekleyen iş yok) taslak `reopen` alır.
- Yayın/ret/yeniden açma `failure.oneri_durumu`'nu ilerletir; görünüm `sonuc_metni` taşır.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.unit.features.bugs.helpers import seed_failure
from tests.unit.features.bugs.test_flow import (
    _ai_sira,
    _ai_taslak,
    _api_taslak,
    _bugs,
    _draft,
    _hazirla,
    _yeni_taslak,
)
from tests.unit.features.cases.helpers import run_jobs
from tp_core.features.bugs import serialize, service, services
from tp_core.gateway.testing import text_response
from tp_core.integrations.jira import JiraNotFound, RestJira
from tp_core.models import BugDraft, Failure, session_scope
from tp_core.workflow.service import WorkflowError

pytestmark = pytest.mark.usefixtures("db")


def _test_baglantisi_404(
    monkeypatch: pytest.MonkeyPatch, jira: RestJira, test_key: str
) -> dict[str, int]:
    gercek = jira.link_issues
    sayac = {"n": 0}

    def link_issues(inward: str, outward: str, tur: str) -> Any:
        if test_key in (inward, outward):
            sayac["n"] += 1
            raise JiraNotFound(f"Issue does not exist: {test_key}", status=404)
        return gercek(inward, outward, tur)

    monkeypatch.setattr(jira, "link_issues", link_issues)
    return sayac


def _tum_denemeler(engine: Engine) -> list[str]:
    """Yayın işini yeniden deneme beklemesini atlayarak sonuna kadar koşturur."""
    durumlar: list[str] = []
    for _ in range(6):
        sonuc = run_jobs(engine)
        if not sonuc:
            break
        durumlar += [r.durum for r in sonuc]
        with engine.begin() as c:
            c.exec_driver_sql("UPDATE job SET run_after = now() WHERE durum = 'retry'")
    return durumlar


def _oneri(fid: uuid.UUID) -> str:
    with session_scope() as s:
        f = s.get(Failure, fid)
        assert f is not None
        return f.oneri_durumu


def _oneri_bug_taslagi(fid: uuid.UUID) -> None:
    with session_scope() as s:
        f = s.get(Failure, fid)
        assert f is not None
        f.oneri_turu, f.oneri_durumu = "bug_draft", "proposed"


def test_test_baglantisi_404_yeni_kayit_taslaga_doner_ve_ayni_bug_kullanilir(
    engine: Engine, bug_fake_gateway: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    bug_fake_gateway([text_response(_ai_taslak()), text_response(_ai_sira(link=False))])
    did, ids = _yeni_taslak()
    _hazirla(engine)
    jira: RestJira = services.jira()
    testci = make_user("tester")
    b, _ = _draft(did)
    with session_scope() as s:
        service.decide(s, did, testci, "new", b.icerik_hash)
    sayac = _test_baglantisi_404(monkeypatch, jira, ids["test_key"])

    assert _tum_denemeler(engine) == ["retry", "retry", "failed"]
    assert sayac["n"] >= 3
    b, ek = _draft(did)
    # Takılı onay yok: testçi yeniden karar verebilir.
    assert b.durum == "draft" and b.karar is None and b.onaylanan_hash is None
    etiketli = jira.search(f'project = "TPD" AND labels = "tp-{did}"', max_results=10)
    assert len(etiketli) == 1  # Bug kısmen yazıldı (açıldı, Test bağlantısı kurulamadı)
    kismi = etiketli[0].key
    assert ek.yayin["durum"] == "basarisiz" and ek.yayin["key"] == kismi
    assert ek.yayin["onceki_karar"] == "new"
    assert "taslağa alındı" in ek.yayin["hata"] and f"kısmen yazıldı: {kismi}" in ek.yayin["hata"]

    # Test issue geri geldi; aynı içerikle yeniden "Yeni kayıt": aynı Bug kullanılır.
    monkeypatch.undo()
    with session_scope() as s:
        service.decide(s, did, testci, "new", b.icerik_hash)
    assert [r.durum for r in run_jobs(engine)] == ["done"]
    b, ek = _draft(did)
    assert b.durum == "published" and b.jira_key == kismi
    assert len(jira.search(f'project = "TPD" AND labels = "tp-{did}"', max_results=10)) == 1
    assert {x["rol"] for x in ek.yayin["baglantilar"]} == {"story", "test"}


def test_test_baglantisi_404_bagla_taslaga_doner_yorum_bir_kez(
    engine: Engine, bug_fake_gateway: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    bug_fake_gateway([text_response(_ai_taslak()), text_response(_ai_sira())])
    did, ids = _yeni_taslak()
    _hazirla(engine)
    jira: RestJira = services.jira()
    once = _bugs(jira)
    testci = make_user("tester")
    b, _ = _draft(did)
    with session_scope() as s:
        service.decide(s, did, testci, "link", b.icerik_hash, link_key="TPD-5")
    _test_baglantisi_404(monkeypatch, jira, ids["test_key"])
    assert _tum_denemeler(engine)[-1] == "failed"
    b, ek = _draft(did)
    assert b.durum == "draft" and b.link_key is None
    assert ek.yayin["key"] == "TPD-5" and ek.yayin["onceki_link_key"] == "TPD-5"
    assert len(jira.get_comments("TPD-5")) == 1  # kanıt yorumu bir kez yazıldı
    monkeypatch.undo()
    with session_scope() as s:
        service.decide(s, did, testci, "link", b.icerik_hash, link_key="TPD-5")
    assert [r.durum for r in run_jobs(engine)] == ["done"]
    b, _ = _draft(did)
    assert b.durum == "published" and b.jira_key == "TPD-5"
    assert len(jira.get_comments("TPD-5")) == 1 and _bugs(jira) == once


def test_takili_onayli_taslak_reopen_alir(
    engine: Engine, bug_fake_gateway: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eski sürümde takılmış taslak (approved + yayın başarısız + bekleyen iş yok) taslağa alınır;
    yeniden denenecek iş varken alınamaz."""
    bug_fake_gateway([text_response(_ai_taslak()), text_response(_ai_sira(link=False))])
    did, ids = _yeni_taslak()
    _hazirla(engine)
    jira: RestJira = services.jira()
    testci = make_user("tester")
    b, _ = _draft(did)
    with session_scope() as s:
        service.decide(s, did, testci, "new", b.icerik_hash)
    _test_baglantisi_404(monkeypatch, jira, ids["test_key"])
    assert [r.durum for r in run_jobs(engine)] == ["retry"]
    b, ek = _draft(did)
    assert b.durum == "approved" and ek.yayin["durum"] == "basarisiz"
    with session_scope() as s, pytest.raises(WorkflowError) as hata:  # iş hâlâ yeniden denenecek
        service.decide(s, did, testci, "reopen", b.icerik_hash)
    assert hata.value.status_code == 409
    with engine.begin() as c:  # eski sürümün kalıcı hatası: iş bitti, taslak approved kaldı
        c.execute(
            text("UPDATE job SET durum = 'failed' WHERE yuk ->> 'draft_id' = :d"), {"d": str(did)}
        )
    with session_scope() as s:
        gorunum = serialize.bug_draft_view(s, s.get(BugDraft, did))
    assert gorunum["yeniden_acilabilir"] is True
    with session_scope() as s:
        service.decide(s, did, testci, "reopen", b.icerik_hash, gerekce="Test issue düzeltildi")
    b, _ = _draft(did)
    assert b.durum == "draft" and b.karar is None
    monkeypatch.undo()
    with session_scope() as s:
        service.decide(s, did, testci, "new", b.icerik_hash)
    assert [r.durum for r in run_jobs(engine)] == ["done"]
    assert _draft(did)[0].durum == "published"


def test_karar_triage_oneri_durumuna_yansir(
    api: TestClient,
    engine: Engine,
    bug_fake_gateway: Any,
    make_user: Any,
    request: pytest.FixtureRequest,
) -> None:
    did, ids, gorunum = _api_taslak(api, engine, bug_fake_gateway, make_user)
    fid = ids["failure_id"]
    _oneri_bug_taslagi(fid)
    assert gorunum["sonuc_metni"] == "Bug taslağı testçi kararı bekliyor"
    request.getfixturevalue("worker")
    r = api.post(
        f"/bug-drafts/{did}/decision",
        json={"karar": "link", "link_key": "TPD-5", "icerik_hash": gorunum["icerik_hash"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "published"
    assert r.json()["sonuc_metni"] == "Mevcut kayda bağlandı: TPD-5"
    assert _oneri(fid) == "merged"
    # Jira yorumu ADF: kanıt bağlantıları tıklanabilir (link işareti), düz metin değil.
    ham = services.jira()._call("GET", "/issue/TPD-5/comment")["comments"][-1]["body"]
    hrefler = [m["attrs"]["href"] for m in _isaretler(ham) if m.get("type") == "link"]
    assert hrefler and all(h.startswith("http") for h in hrefler), ham
    liste = api.get("/bug-drafts", params={"failure_id": str(fid)}).json()
    assert [d["id"] for d in liste] == [str(did)]


def test_ret_ve_yeniden_acma_oneri_durumu_ve_ekli_basarisizlik(
    engine: Engine, bug_fake_gateway: Any, make_user: Any
) -> None:
    bug_fake_gateway([text_response(_ai_taslak()), text_response(_ai_sira())])
    did, ids = _yeni_taslak()
    _hazirla(engine)
    # Aynı imzayla ikinci başarısızlık mevcut taslağa eklenir; o da güncellenir.
    ikinci = seed_failure(services.jira(), req_id=ids["requirement_id"], test_issue=False)[
        "failure_id"
    ]
    with session_scope() as s:
        assert service.create_draft_from_failure(s, ikinci) == did
    for fid in (ids["failure_id"], ikinci):
        _oneri_bug_taslagi(fid)
    testci = make_user("tester")
    b, _ = _draft(did)
    with session_scope() as s:
        service.decide(s, did, testci, "dismiss", b.icerik_hash, gerekce="ürün davranışı doğru")
    assert _oneri(ids["failure_id"]) == "rejected" and _oneri(ikinci) == "rejected"
    with session_scope() as s:
        assert serialize.bug_draft_view(s, s.get(BugDraft, did))["sonuc_metni"].startswith(
            "Testçi taslağı reddetti"
        )
        ekli = serialize.bug_draft_list(s, failure_id=ikinci)
    assert [d["id"] for d in ekli] == [str(did)]
    with session_scope() as s:
        service.decide(s, did, testci, "reopen", b.icerik_hash)
    assert _oneri(ids["failure_id"]) == "proposed" and _oneri(ikinci) == "proposed"


def _isaretler(n: Any) -> list[dict[str, Any]]:
    if not isinstance(n, dict):
        return []
    out = list(n.get("marks") or [])
    for c in n.get("content") or []:
        out += _isaretler(c)
    return out


def test_test_issue_jirada_yoksa_hicbir_sey_yazilmaz(
    engine: Engine, bug_fake_gateway: Any, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """jira-sim elle sıfırlanıp Test issue kaybolduysa yetim Bug açılmaz; taslak karara döner."""
    bug_fake_gateway([text_response(_ai_taslak()), text_response(_ai_sira(link=False))])
    did, ids = _yeni_taslak()
    _hazirla(engine)
    jira: RestJira = services.jira()
    once = _bugs(jira)
    testci = make_user("tester")
    b, _ = _draft(did)
    with session_scope() as s:
        service.decide(s, did, testci, "new", b.icerik_hash)
    gercek = jira.get_issue

    def get_issue(key: str) -> Any:
        if key == ids["test_key"]:
            raise JiraNotFound(f"Issue does not exist: {key}", status=404)
        return gercek(key)

    monkeypatch.setattr(jira, "get_issue", get_issue)
    assert _tum_denemeler(engine)[-1] == "failed"
    b, ek = _draft(did)
    assert b.durum == "draft" and b.karar is None
    assert f"Test issue {ids['test_key']} Jira'da yok" in ek.yayin["hata"]
    assert _bugs(jira) == once  # hiçbir Bug açılmadı
    assert jira.search(f'project = "TPD" AND labels = "tp-{did}"', max_results=10) == []
