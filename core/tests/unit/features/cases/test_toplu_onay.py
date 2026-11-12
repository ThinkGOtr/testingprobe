"""Toplu onay (013 §3.2, K3/K13/K16): görülme şartı (≥ 3 sn), öğe başına SAVEPOINT, kilit sırası,
`goruldu`/`onay_engeli` alanları, denetim izi ve review `kanal: "toplu"`."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from tp_core.audit import content_hash
from tp_core.gateway.testing import text_response
from tp_core.models import AuditEvent, Requirement, Review, TestCase, session_scope

from .helpers import case_icerik, goruntule, latest_cases, login, run_jobs


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


def test_gorulmeyen_atlanir_hash_uyusmazligi_tek_ogeyi_dusurur(api: TestClient, hazir, db) -> None:
    rid, analist = hazir
    a, b, c = latest_cases(api, rid)
    assert not any(x["goruldu"] for x in (a, b, c))
    assert all(x["onay_engeli"] is None for x in (a, b, c))
    goruntule(api, db, a["id"], b["id"])
    gor = {x["id"]: x["goruldu"] for x in latest_cases(api, rid)}
    assert gor == {a["id"]: True, b["id"]: True, c["id"]: False}

    r = _toplu(api, [(a["id"], a["icerik_hash"]), (b["id"], "eski"), (c["id"], c["icerik_hash"])])
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    sonuc = {s["case_id"]: s for s in out["sonuclar"]}
    assert [s["case_id"] for s in out["sonuclar"]] == [a["id"], b["id"], c["id"]]
    assert sonuc[a["id"]]["durum"] == "onaylandi" and sonuc[a["id"]]["neden"] is None
    assert sonuc[a["id"]]["otomatik_kod"] is None  # K16: üst düzey alanda
    assert out["otomatik_kod"] == {"durum": "kapali", "job_id": None, "case_sayisi": 0}
    assert sonuc[b["id"]]["durum"] == "hata" and sonuc[b["id"]]["otomatik_kod"] is None
    assert "değişmiş" in sonuc[b["id"]]["neden"] or "hash" in sonuc[b["id"]]["neden"]
    assert sonuc[c["id"]] == {
        "case_id": c["id"], "durum": "atlandi", "neden": "Case en az 3 saniye ekranda kalmadı",
        "otomatik_kod": None,
    }  # fmt: skip
    assert out["ozet"] == {"onaylandi": 1, "atlandi": 1, "hata": 1}
    assert (_durum(a["id"]), _durum(b["id"]), _durum(c["id"])) == ("approved", "draft", "draft")

    with session_scope() as s:
        [rv] = s.scalars(select(Review).where(Review.nesne_id == uuid.UUID(a["id"]))).all()
        assert rv.user_id == analist.id and rv.onaylanan_hash == a["icerik_hash"]
        assert rv.duzeltme_olculeri["kanal"] == "toplu"
        # Düşen öğenin SAVEPOINT'i kendi review/denetim kayıtlarını da geri aldı.
        assert s.scalars(select(Review).where(Review.nesne_id == uuid.UUID(b["id"]))).all() == []
        [d] = s.scalars(select(AuditEvent).where(AuditEvent.eylem == "cases.bulk_decision")).all()
        assert d.aktor == analist.kullanici_adi
        assert {k: d.ozet[k] for k in ("istenen", "onaylandi", "atlandi", "hata")} == {
            "istenen": 3, "onaylandi": 1, "atlandi": 1, "hata": 1,
        }  # fmt: skip
        assert [(o["case_id"], o["durum"]) for o in d.ozet["ogeler"]] == [
            (a["id"], "onaylandi"), (b["id"], "hata"), (c["id"], "atlandi"),
        ]  # fmt: skip
        assert d.ozet["ogeler"][2]["neden"] == "Case en az 3 saniye ekranda kalmadı"

    # Onaydan sonra `goruldu` düşer (son karar görüntülemeden sonra); b hâlâ görülmüş.
    son = {x["id"]: x for x in latest_cases(api, rid)}
    assert {k: x["goruldu"] for k, x in son.items()} == {
        a["id"]: False, b["id"]: True, c["id"]: False,
    }  # fmt: skip
    # Onaylı case artık onaylanamaz: engel nedeni decide'ın reddiyle aynı.
    assert "taslak" in son[a["id"]]["onay_engeli"] and son[b["id"]]["onay_engeli"] is None
    assert api.get(f"/cases/{b['id']}").json()["goruldu"] is True


def test_taslaga_alinan_case_yeniden_gorulmeli(
    api: TestClient, hazir, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.features.cases import service

    # Süre şartı ayrı testte; burada eşik (son karar) sınanır: review geriye alınamaz.
    monkeypatch.setattr(service, "GORULME_MIN_S", 0)
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


def test_tekrarlanan_oge_bir_kez_islenir(api: TestClient, hazir, db) -> None:
    rid, _ = hazir
    a = latest_cases(api, rid)[0]
    goruntule(api, db, a["id"])
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


def test_uc_saniye_dolmadan_gorulmus_sayilmaz(api: TestClient, hazir) -> None:
    """K13: görüntüleme ile karar arasında en az 3 sn yoksa `goruldu` false, toplu onay atlar."""
    rid, _ = hazir
    a = latest_cases(api, rid)[0]
    assert api.post(f"/cases/{a['id']}/viewed").status_code == 200
    assert api.get(f"/cases/{a['id']}").json()["goruldu"] is False
    out = _toplu(api, [(a["id"], a["icerik_hash"])]).json()
    assert out["sonuclar"][0]["durum"] == "atlandi"
    assert out["sonuclar"][0]["neden"] == "Case en az 3 saniye ekranda kalmadı"
    assert out["otomatik_kod"] == {"durum": "yok", "job_id": None, "case_sayisi": 0}
    assert _durum(a["id"]) == "draft"


def test_kilit_sirasi_case_id_yanit_sirasi_istek(
    api: TestClient, hazir, db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.features.cases import service

    rid, _ = hazir
    cs = latest_cases(api, rid)
    goruntule(api, db, *[c["id"] for c in cs])
    sira: list[uuid.UUID] = []
    asil = service.decide

    def izle(session, cid, user, **kw):
        sira.append(cid)
        return asil(session, cid, user, **kw)

    monkeypatch.setattr(service, "decide", izle)
    istek = sorted(cs, key=lambda c: c["id"], reverse=True)
    out = _toplu(api, [(c["id"], c["icerik_hash"]) for c in istek]).json()
    assert [s["case_id"] for s in out["sonuclar"]] == [c["id"] for c in istek]
    assert sira == sorted(uuid.UUID(c["id"]) for c in cs)
    assert out["ozet"]["onaylandi"] == 3


def test_db_ve_beklenmeyen_hata_yalniz_ogeyi_dusurur(
    api: TestClient, hazir, db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import OperationalError

    from tp_core.features.cases import service

    rid, _ = hazir
    a, b, c = latest_cases(api, rid)
    goruntule(api, db, a["id"], b["id"], c["id"])
    asil = service.decide

    def patlayan(session, cid, user, **kw):
        tc = asil(session, cid, user, **kw)  # yazılanlar SAVEPOINT ile geri alınmalı
        if str(cid) == b["id"]:
            raise OperationalError("UPDATE", {}, Exception("deadlock detected"))
        if str(cid) == c["id"]:
            raise RuntimeError("beklenmedik")
        return tc

    monkeypatch.setattr(service, "decide", patlayan)
    r = _toplu(api, [(x["id"], x["icerik_hash"]) for x in (a, b, c)])
    assert r.status_code == 200, r.text
    sonuc = {s["case_id"]: s for s in r.json()["sonuclar"]}
    assert sonuc[a["id"]]["durum"] == "onaylandi"
    assert sonuc[b["id"]]["durum"] == "hata" and "Veritabanı" in sonuc[b["id"]]["neden"]
    assert sonuc[c["id"]]["durum"] == "hata" and "Beklenmeyen" in sonuc[c["id"]]["neden"]
    assert (_durum(a["id"]), _durum(b["id"]), _durum(c["id"])) == ("approved", "draft", "draft")
    with session_scope() as s:
        assert s.scalars(select(Review).where(Review.nesne_id == uuid.UUID(b["id"]))).all() == []


def test_onay_engeli_decide_ile_ayni(api: TestClient, hazir) -> None:
    """`onay_engeli` approve'un gerçek reddini söyler: bilinmeyen AC, gereksinim değişimi."""
    rid, _ = hazir
    a, b, _c = latest_cases(api, rid)
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(a["id"]))
        tc.icerik = {**tc.icerik, "acceptance_criteria_refs": ["AC9"]}
        tc.icerik_hash = content_hash(tc.icerik)
    a2 = api.get(f"/cases/{a['id']}").json()
    assert a2["onay_engeli"] and "AC9" in a2["onay_engeli"]
    r = api.post(
        f"/cases/{a['id']}/decision", json={"karar": "approve", "icerik_hash": a2["icerik_hash"]}
    )
    assert r.status_code == 422 and a2["onay_engeli"] in r.json()["detail"]

    with session_scope() as s:
        req = s.get(Requirement, uuid.UUID(str(rid)))
        req.aciklama = (req.aciklama or "") + " (değişti)"  # PO onayından sonra içerik değişti
    b2 = api.get(f"/cases/{b['id']}").json()
    assert b2["onay_engeli"] == (
        "Gereksinim içeriği PO onayından sonra değişmiş; case'ler eski metne ait"
    )
    r = api.post(
        f"/cases/{b['id']}/decision", json={"karar": "approve", "icerik_hash": b["icerik_hash"]}
    )
    assert r.status_code == 409 and b2["onay_engeli"] in r.json()["detail"]
