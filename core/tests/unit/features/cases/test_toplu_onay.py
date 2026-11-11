"""Toplu onay (013 §3.2, K3): görülme şartı, öğe başına SAVEPOINT, `goruldu` alanı."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from tp_core.gateway.testing import text_response
from tp_core.models import AuditEvent, Review, TestCase, session_scope

from .helpers import case_icerik, latest_cases, login, run_jobs


@pytest.fixture
def hazir(api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway):
    cases = [
        case_icerik(),
        case_icerik(title="Hatalı parola mesajı", ref="AC2", type="negative"),
        case_icerik(title="Boş kullanıcı adı", ref="AC2", type="boundary"),
    ]
    fake_gateway([text_response({"cases": cases})])
    rid = make_requirement()
    analist = make_user("analyst")
    login(api, analist)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    return rid, analist


def _toplu(api: TestClient, ogeler: list[tuple[str, str]], karar: str = "approve"):
    return api.post(
        "/cases/bulk-decision",
        json={"karar": karar, "ogeler": [{"case_id": c, "icerik_hash": h} for c, h in ogeler]},
    )


def _durum(cid: str) -> str:
    with session_scope() as s:
        return s.get(TestCase, uuid.UUID(cid)).durum


def test_gorulmeyen_atlanir_hash_uyusmazligi_tek_ogeyi_dusurur(api: TestClient, hazir) -> None:
    rid, analist = hazir
    a, b, c = latest_cases(api, rid)
    assert not any(x["goruldu"] for x in (a, b, c))
    for x in (a, b):
        assert api.post(f"/cases/{x['id']}/viewed").status_code == 200
    gor = {x["id"]: x["goruldu"] for x in latest_cases(api, rid)}
    assert gor == {a["id"]: True, b["id"]: True, c["id"]: False}

    r = _toplu(api, [(a["id"], a["icerik_hash"]), (b["id"], "eski"), (c["id"], c["icerik_hash"])])
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    sonuc = {s["case_id"]: s for s in out["sonuclar"]}
    assert [s["case_id"] for s in out["sonuclar"]] == [a["id"], b["id"], c["id"]]
    assert sonuc[a["id"]]["durum"] == "onaylandi" and sonuc[a["id"]]["neden"] is None
    assert sonuc[a["id"]]["otomatik_kod"]["durum"] == "kapali"  # fikstür ayarı kapalı
    assert sonuc[b["id"]]["durum"] == "hata" and sonuc[b["id"]]["otomatik_kod"] is None
    assert "değişmiş" in sonuc[b["id"]]["neden"] or "hash" in sonuc[b["id"]]["neden"]
    assert sonuc[c["id"]] == {
        "case_id": c["id"], "durum": "atlandi", "neden": "Bu case'i açıp görmediniz",
        "otomatik_kod": None,
    }  # fmt: skip
    assert out["ozet"] == {"onaylandi": 1, "atlandi": 1, "hata": 1}
    assert (_durum(a["id"]), _durum(b["id"]), _durum(c["id"])) == ("approved", "draft", "draft")

    with session_scope() as s:
        [rv] = s.scalars(select(Review).where(Review.nesne_id == uuid.UUID(a["id"]))).all()
        assert rv.user_id == analist.id and rv.onaylanan_hash == a["icerik_hash"]
        # Düşen öğenin SAVEPOINT'i kendi review/denetim kayıtlarını da geri aldı.
        assert s.scalars(select(Review).where(Review.nesne_id == uuid.UUID(b["id"]))).all() == []
        [d] = s.scalars(select(AuditEvent).where(AuditEvent.eylem == "cases.bulk_decision")).all()
        assert d.aktor == analist.kullanici_adi
        assert d.ozet == {"istenen": 3, "onaylandi": 1, "atlandi": 1, "hata": 1}

    # Onaydan sonra `goruldu` düşer (son karar görüntülemeden sonra); b hâlâ görülmüş.
    gor = {x["id"]: x["goruldu"] for x in latest_cases(api, rid)}
    assert gor == {a["id"]: False, b["id"]: True, c["id"]: False}
    assert api.get(f"/cases/{b['id']}").json()["goruldu"] is True


def test_taslaga_alinan_case_yeniden_gorulmeli(api: TestClient, hazir) -> None:
    rid, _ = hazir
    a = latest_cases(api, rid)[0]
    api.post(f"/cases/{a['id']}/viewed")
    assert _toplu(api, [(a["id"], a["icerik_hash"])]).json()["ozet"]["onaylandi"] == 1
    r = api.post(
        f"/cases/{a['id']}/decision", json={"karar": "reopen", "icerik_hash": a["icerik_hash"]}
    )
    assert r.status_code == 200, r.text
    r = _toplu(api, [(a["id"], a["icerik_hash"])])
    assert r.json()["sonuclar"][0]["durum"] == "atlandi"
    api.post(f"/cases/{a['id']}/viewed")
    assert _toplu(api, [(a["id"], a["icerik_hash"])]).json()["ozet"]["onaylandi"] == 1


def test_tekrarlanan_oge_bir_kez_islenir(api: TestClient, hazir) -> None:
    rid, _ = hazir
    a = latest_cases(api, rid)[0]
    api.post(f"/cases/{a['id']}/viewed")
    out = _toplu(api, [(a["id"], a["icerik_hash"])] * 2).json()
    assert [s["durum"] for s in out["sonuclar"]] == ["onaylandi", "atlandi"]


def test_girdi_dogrulama_ve_rol(api: TestClient, hazir, make_user) -> None:
    rid, _ = hazir
    a = latest_cases(api, rid)[0]
    assert _toplu(api, []).status_code == 422
    assert _toplu(api, [(a["id"], a["icerik_hash"])], karar="reject").status_code == 422
    fazla = [(str(uuid.uuid4()), "h")] * 201
    assert _toplu(api, fazla).status_code == 422
    login(api, make_user("engineer"))
    assert _toplu(api, [(a["id"], a["icerik_hash"])]).status_code == 403
    assert _durum(a["id"]) == "draft"
