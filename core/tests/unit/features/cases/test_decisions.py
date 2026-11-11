"""Case kararları (Constitution I, X): hash bağı, şema, ölçüm, Taslağa al, review tamam."""

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from tp_core.audit import content_hash
from tp_core.gateway.testing import text_response
from tp_core.models import AuditEvent, Review, TestCase, session_scope
from tp_core.workflow.service import (
    SYSTEM,
    GateClosed,
    approved_hash_matches,
    latest_review,
    transition,
)

from .helpers import case_icerik, latest_cases, login, run_jobs, uretim_cikti


@pytest.fixture
def hazir(api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway):
    """3 draft case'li, PO onaylı gereksinim + oturum açmış analist."""
    cases = [
        case_icerik(),
        case_icerik(title="Hatalı parola mesajı", ref="AC2", type="negative"),
        case_icerik(title="Boş kullanıcı adı", ref="AC2", type="boundary"),
    ]
    fake_gateway([text_response(uretim_cikti(cases))])
    rid = make_requirement()
    analist = make_user("analyst")
    login(api, analist)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    return rid, analist


def _karar(api: TestClient, c: dict[str, Any], **govde: Any):
    return api.post(f"/cases/{c['id']}/decision", json={"icerik_hash": c["icerik_hash"], **govde})


def test_onay_hash_ister_ve_bayat_hash_409(api: TestClient, hazir) -> None:
    rid, _ = hazir
    c = latest_cases(api, rid)[0]
    r = api.post(f"/cases/{c['id']}/decision", json={"karar": "approve"})
    assert r.status_code == 422 and "icerik_hash" in r.json()["detail"]
    r = api.post(f"/cases/{c['id']}/decision", json={"karar": "approve", "icerik_hash": "eski"})
    assert r.status_code == 409
    assert latest_cases(api, rid)[0]["durum"] == "draft"


def test_onay_review_kaydi_ve_onaylanan_hash(api: TestClient, hazir) -> None:
    rid, analist = hazir
    c = latest_cases(api, rid)[0]
    assert api.post(f"/cases/{c['id']}/viewed").json()["yeni"] is True
    assert api.post(f"/cases/{c['id']}/viewed").json()["yeni"] is False  # ilk görüntüleme sabit
    time.sleep(0.05)
    r = _karar(api, c, karar="approve")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["durum"] == "approved" and out["karar"] == "approve"
    assert out["onaylanan_hash"] == c["icerik_hash"] and out["karar_veren"] == analist.kullanici_adi
    assert out["review_sure_ms"] is not None and out["review_sure_ms"] >= 40
    with session_scope() as s:
        rv = s.scalars(select(Review).where(Review.nesne_id == uuid.UUID(c["id"]))).one()
        assert rv.user_id == analist.id and rv.kanal == "portal"
        assert rv.onaylanan_hash == c["icerik_hash"]
        assert rv.duzeltme_olculeri["ilk_karar"] is True


def test_duzeltme_sema_dogrular_ve_olcer(api: TestClient, hazir) -> None:
    rid, _ = hazir
    c = latest_cases(api, rid)[0]
    bozuk = {**c["icerik"], "tags": ["manual"]}
    r = _karar(api, c, karar="edit", icerik=bozuk)
    assert r.status_code == 422 and "tags" in r.json()["detail"]
    hayali = {**c["icerik"], "acceptance_criteria_refs": ["AC9"]}
    assert _karar(api, c, karar="edit", icerik=hayali).status_code == 422
    assert _karar(api, c, karar="edit", icerik=c["icerik"]).status_code == 422  # değişiklik yok

    yeni = {**c["icerik"], "title": c["icerik"]["title"] + " yapılır"}
    r = _karar(api, c, karar="edit", icerik=yeni)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["durum"] == "approved" and out["surum"] == 2
    assert out["icerik"] == yeni and out["icerik_hash"] == content_hash(yeni)
    assert out["onaylanan_hash"] == out["icerik_hash"]
    assert 0 < out["duzeltme_olcusu"] <= 0.15 and out["kucuk_duzeltme"] is True
    with session_scope() as s:
        rv = s.scalars(select(Review).where(Review.nesne_id == uuid.UUID(c["id"]))).one()
        assert rv.once == {"icerik": c["icerik"]} and rv.sonra == {"icerik": yeni}
        assert rv.duzeltme_olculeri["degisen_alanlar"] == ["title"]


def test_ret_taksonomi_ister(api: TestClient, hazir) -> None:
    rid, _ = hazir
    c = latest_cases(api, rid)[1]
    assert _karar(api, c, karar="reject").status_code == 422
    assert _karar(api, c, karar="reject", ret_nedeni="uydurma").status_code == 422
    r = _karar(api, c, karar="reject", ret_nedeni="hallucinated_step")
    assert r.status_code == 200 and r.json()["durum"] == "rejected"
    assert r.json()["ret_nedeni"] == "hallucinated_step"


def test_karar_yalnizca_taslakta_ve_taslaga_al(api: TestClient, engine: Engine, hazir) -> None:
    rid, analist = hazir
    c = latest_cases(api, rid)[0]
    assert _karar(api, c, karar="approve").status_code == 200
    r = _karar(api, c, karar="reject", ret_nedeni="duplicate")
    assert r.status_code == 409 and "Taslağa al" in r.json()["detail"]
    assert _karar(api, c, karar="reopen", icerik_hash="eski").status_code == 409
    r = _karar(api, c, karar="reopen", gerekce="yeniden bakılacak")
    assert r.status_code == 200, r.text
    assert r.json()["durum"] == "draft" and r.json()["onaylanan_hash"] is None
    assert _karar(api, c, karar="reopen").status_code == 409  # taslak yeniden açılmaz
    with session_scope() as s:
        olaylar = s.scalars(
            select(AuditEvent).where(AuditEvent.nesne == f"test_case:{c['id']}")
        ).all()
        eylemler = [o.eylem for o in olaylar]
        assert "case.reopen" in eylemler
        geri = [o for o in olaylar if o.eylem == "test_case.transition" and o.ozet["to"] == "draft"]
        assert geri and geri[0].aktor == analist.kullanici_adi
        assert geri[0].ozet["sebep"].startswith("Taslağa al")
    # Taslağa alma kayıtlı, onaylamayan bir karardır: eski 'approve' kapıyı yeniden açamaz.
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(c["id"]))
        son = latest_review(s, "test_case", tc.id)
        assert son is not None and son.karar == "reopen" and son.gerekce == "yeniden bakılacak"
        assert not approved_hash_matches(s, tc)
        with pytest.raises(GateClosed):
            transition(s, tc, "approved", SYSTEM, "draft")
    # Portal, taslağa alınan case'te önceki içerik kararını göstermeye devam eder.
    goster = next(x for x in latest_cases(api, c["requirement_id"]) if x["id"] == c["id"])
    assert goster["karar"] == "approve" and goster["durum"] == "draft"
    # Yeniden karar verilebilir.
    assert _karar(api, c, karar="reject", ret_nedeni="duplicate").json()["durum"] == "rejected"


def test_goruntuleme_yalnizca_analist(api: TestClient, make_user, hazir) -> None:
    rid, _ = hazir
    c = latest_cases(api, rid)[0]
    for rol in ("po", "engineer", "tester"):
        api.post("/auth/logout")
        login(api, make_user(rol))
        r = api.post(f"/cases/{c['id']}/viewed")
        assert r.status_code == 403, (rol, r.text)
    from tp_core.models import CaseGoruntuleme

    with session_scope() as s:
        assert s.scalar(select(CaseGoruntuleme.id)) is None


def test_po_rolu_karar_veremez(api: TestClient, make_user, hazir) -> None:
    rid, _ = hazir
    c = latest_cases(api, rid)[0]
    api.post("/auth/logout")
    login(api, make_user("po"))
    assert _karar(api, c, karar="approve").status_code == 403


def test_kabul_orani_ilk_karara_gore_ve_review_tamam(api: TestClient, hazir) -> None:
    rid, _ = hazir
    a, b, c = latest_cases(api, rid)
    assert _karar(api, a, karar="approve").status_code == 200
    r = api.post(f"/requirements/{rid}/review-complete")
    assert r.status_code == 409 and "2 case" in r.json()["detail"]

    buyuk = {
        **b["icerik"],
        "expected_result": "Tamamen farklı bir beklenen sonuç metni",
        "title": "Yeniden yazılmış başlık",
    }
    assert _karar(api, b, karar="edit", icerik=buyuk).status_code == 200
    assert _karar(api, c, karar="reject", ret_nedeni="out_of_scope").status_code == 200
    # Reddedileni taslağa alıp onaylamak ilk karara dayalı oranı değiştirmez.
    c2 = latest_cases(api, rid)[2]
    assert _karar(api, c2, karar="reopen").status_code == 200
    assert _karar(api, latest_cases(api, rid)[2], karar="approve").status_code == 200

    m = api.get(f"/requirements/{rid}/case-metrics").json()
    assert m["uretilen"] == 3 and m["karar_verilen"] == 3 and m["bekleyen"] == 0
    assert m["ilk_kararlar"] == {"approve": 1, "edit": 1, "reject": 1}
    assert m["kabul"] == 1 and m["kabul_orani"] == pytest.approx(1 / 3, abs=1e-4)
    assert m["ret_nedenleri"] == {"out_of_scope": 1}
    assert m["kabul_hedefi"] == 0.7 and m["ai_cagri_modlari"] == {"live": 1}
    assert m["durumlar"] == {"approved": 3}

    r = api.post(f"/requirements/{rid}/review-complete")
    assert r.status_code == 200, r.text
    assert r.json()["olcum"]["kabul"] == 1
    with session_scope() as s:
        ev = s.scalars(
            select(AuditEvent).where(AuditEvent.eylem == "requirement.review_complete")
        ).one()
        assert ev.ozet["uretilen"] == 3
