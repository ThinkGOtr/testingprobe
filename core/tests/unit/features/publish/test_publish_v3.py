"""Yayın kapısı, şema v3 (ANALIZ §4.7): hazır olmayan case yayınlanmaz; denetim kapısı kancası."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.unit.features.cases.helpers import READ
from tests.unit.features.publish.test_publish import (  # noqa: F401
    _ctx,
    _label_count,
    hazir,
    yayin_analist,
    yayin_testci,
)
from tp_core.audit.canonical import content_hash
from tp_core.features.publish import service as publish
from tp_core.integrations.jira import RestJira
from tp_core.models import TestCase, session_scope

V3 = {
    "technique": ["BVA"],
    "covers": ["BV-1"],
    "priority": "P1",
    "priority_rationale": "Giriş tüm akışların ön koşuludur",
    "test_level": None,
    "verification_point": "UI",
    "readiness": "ready",
    "assumption_refs": [],
    "open_question_refs": [],
    "test_data": [],
    "teardown": ["Oturumu kapat"],
    "platform": None,
    "requires_real_device": False,
    "standard_refs": [],
}


def _onayli_icerik(engine: Engine, cid: str, **alanlar: Any) -> None:
    """Onaylı case'i eski (v2) alan kümesine indirir, verilen alanları ekler ve onay hash'lerini
    yeni içeriğe taşır (alan verilmezse case eski case olur).

    Onay ucu (K6) hazır olmayan case'i reddeder; yayın kapısı bundan bağımsız, ikinci savunma
    hattıdır. Bu yüzden "onaylı ama hazır değil" durumu doğrudan veritabanında kurulur.
    """
    with session_scope() as s:
        eski = {k: v for k, v in s.get(TestCase, uuid.UUID(cid)).icerik.items() if k not in V3}
        icerik = {**eski, **alanlar}
    h = content_hash(icerik)
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE test_case SET icerik = CAST(:i AS jsonb), icerik_hash = :h, "
                "onaylanan_hash = :h WHERE id = :id"
            ),
            {"i": json.dumps(icerik), "h": h, "id": cid},
        )
        c.execute(
            text(
                # review yalnız eklenir (güncellenemez): son onay kararı yeni hash'le yinelenir.
                "INSERT INTO review (nesne_turu, nesne_id, user_id, kanal, karar, onaylanan_hash) "
                "SELECT nesne_turu, nesne_id, user_id, kanal, karar, :h FROM review "
                "WHERE nesne_turu = 'test_case' AND nesne_id = :id ORDER BY sira DESC LIMIT 1"
            ),
            {"h": h, "id": cid},
        )


def _kalem(api: TestClient, rid: Any, cid: str) -> dict[str, Any]:
    on = api.get("/publish/preview", params={"requirement_id": str(rid)}).json()
    return next(k for k in on["kalemler"] if k["case_id"] == cid)


def test_hazir_olmayan_case_yayinlanmaz_ve_onizlemede_nedeniyle_gorunur(
    api: TestClient,
    engine: Engine,
    jira: RestJira,
    targets,
    hazir,  # noqa: F811
) -> None:
    rid, _, a, b = hazir
    # Eski (v2) case: `readiness` yok → hazır sayılır (K9); önizleme bugünkü gibi.
    _onayli_icerik(engine, a["id"])
    eski = _kalem(api, rid, a["id"])
    assert (eski["islem"], eski["neden"], eski["readiness"]) == ("create", None, "ready")
    assert eski["labels"] == ["AI-generated", f"tp-{a['id']}", "tp-mod-live"]
    assert _kalem(api, rid, b["id"])["neden"] == "Yayınlanamaz: Onaylı değil (durum: draft)"

    for hazirlik, parca in (
        ("assumption_dependent", "varsayıma bağlı"),
        ("blocked", "soru bekliyor (açık soru PO yanıtını bekliyor"),
    ):
        _onayli_icerik(engine, a["id"], **{**V3, "readiness": hazirlik})
        k = _kalem(api, rid, a["id"])
        assert k["islem"] == "blocked_not_ready" and k["readiness"] == hazirlik
        assert k["neden"].startswith("Yayınlanamaz: ") and parca in k["neden"]
        sonuc = publish.run_publish(_ctx([a["id"]]), engine)["sonuclar"][0]
        assert sonuc["durum"] == "failed" and sonuc["hata"] == k["neden"]
        assert _label_count(jira, a["id"]) == 0  # Jira'ya hiçbir şey yazılmadı
    with session_scope() as s:
        assert s.get(TestCase, uuid.UUID(a["id"])).durum == "approved"


def test_hazir_v3_case_teknik_ve_oncelik_etiketleriyle_yayinlanir(
    api: TestClient,
    engine: Engine,
    sim: TestClient,
    jira: RestJira,
    targets,
    hazir,  # noqa: F811
) -> None:
    rid, _, a, _ = hazir
    _onayli_icerik(engine, a["id"], **V3)
    k = _kalem(api, rid, a["id"])
    assert k["islem"] == "create" and k["neden"] is None
    etiketler = ["AI-generated", f"tp-{a['id']}", "tp-tech-BVA", "tp-P1"]
    assert k["labels"] == [*etiketler, "tp-mod-live"]
    assert k["payload"]["jira_issue"]["fields"]["labels"] == etiketler

    sonuc = publish.run_publish(_ctx([a["id"]]), engine)["sonuclar"][0]
    assert sonuc["durum"] == "created", sonuc
    f = sim.get(f"/rest/api/3/issue/{sonuc['external_key']}", auth=READ).json()["fields"]
    assert f["labels"] == k["labels"]
    assert f["description"] == k["payload"]["jira_issue"]["fields"]["description"]
    # Yeniden yayın: `tp-<uuid>` araması ek etiketlerle de tek issue bulur.
    assert publish.run_publish(_ctx([a["id"]]), engine)["sonuclar"][0]["durum"] == "exists"
    assert _label_count(jira, a["id"]) == 1


def test_denetim_kapisi_kancasi_yalniz_v3_casee_uygulanir(
    api: TestClient,
    engine: Engine,
    jira: RestJira,
    targets,
    hazir,  # noqa: F811
) -> None:
    rid, _, a, _ = hazir
    cagrilar: list[uuid.UUID] = []

    def kapi(_session: Any, tc: TestCase) -> str | None:
        cagrilar.append(tc.id)
        return "Denetim kararı yok: set için KABUL gerekli"

    publish.set_gate_check(kapi)
    try:
        # Eski case için kapı aranmaz (K9).
        _onayli_icerik(engine, a["id"])
        assert _kalem(api, rid, a["id"])["islem"] == "create" and cagrilar == []
        # Hazır olmayan v3 case: neden hazır olmamasıdır, kapıya gelinmez.
        _onayli_icerik(engine, a["id"], **{**V3, "readiness": "blocked"})
        assert _kalem(api, rid, a["id"])["islem"] == "blocked_not_ready" and cagrilar == []
        # Hazır v3 case: kapı engeller (önizleme ve yayın aynı nedenle).
        _onayli_icerik(engine, a["id"], **V3)
        k = _kalem(api, rid, a["id"])
        assert (k["islem"], k["neden"]) == (
            "blocked_gate",
            "Yayınlanamaz: Denetim kararı yok: set için KABUL gerekli",
        )
        sonuc = publish.run_publish(_ctx([a["id"]]), engine)["sonuclar"][0]
        assert sonuc["durum"] == "failed" and sonuc["hata"] == k["neden"]
        assert _label_count(jira, a["id"]) == 0 and cagrilar
    finally:
        publish.set_gate_check(None)
    # Kapı kaldırılınca (varsayılan) engel yok.
    assert publish.run_publish(_ctx([a["id"]]), engine)["sonuclar"][0]["durum"] == "created"
