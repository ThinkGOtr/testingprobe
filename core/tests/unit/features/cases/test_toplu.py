"""Toplu onay ve "Varsayım doğrulandı" (specs/011 K20; `features/cases/toplu.py`)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from tp_core.features.cases import service
from tp_core.gateway.testing import text_response
from tp_core.models import AuditEvent, Requirement, Review, session_scope

from .helpers import case_icerik, eski_case_icerik, latest_cases, login, run_jobs, uretim_cikti

OZET = {
    "open_questions": [{"id": "Q1", "question": "Kaç hatalı denemede kilitlenir?", "owner": "PO"}],
    "assumptions": [
        {"id": "A1", "statement": "Parola büyük/küçük harf duyarlıdır", "owner": ""},
        {"id": "A2", "statement": "Oturum 30 dakikada düşer", "owner": ""},
    ],
}


def _cases() -> list[dict[str, Any]]:
    """0-1 hazır; 2 tek varsayım (A1); 3 iki varsayım (A1, A2); 4 varsayım + soru;
    5 tek varsayım ama beklenen sonuç boş."""
    varsayimli = {"readiness": "assumption_dependent"}
    return [
        case_icerik(),
        case_icerik(title="Beni hatırla ile giriş", covers=["UC-AF1"]),
        case_icerik(
            title="Büyük harfli parola", covers=["UC-AF2"], assumption_refs=["A1"], **varsayimli
        ),
        case_icerik(
            title="Oturum süresi", covers=["UC-AF3"], assumption_refs=["A1", "A2"], **varsayimli
        ),
        case_icerik(
            title="Kilit ve harf",
            covers=["UC-AF4"],
            assumption_refs=["A1"],
            open_question_refs=["Q1"],
            **varsayimli,
        ),
        case_icerik(
            title="Boş beklenen",
            covers=["UC-AF5"],
            assumption_refs=["A1"],
            expected_result="",
            **varsayimli,
        ),
    ]


@pytest.fixture
def cs(api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway):
    """v3 üretimi tamamlanmış gereksinim + oturum açmış analist; güncel case'ler."""
    fake_gateway([text_response(uretim_cikti(_cases(), **OZET))])
    rid = make_requirement()
    login(api, make_user("analyst"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    (is_,) = run_jobs(engine)
    assert is_.durum == "done", is_
    cases = latest_cases(api, rid)
    assert len(cases) == 6
    return rid, cases


def _kalem(c: dict[str, Any], icerik_hash: str | None = None) -> dict[str, str]:
    return {"case_id": c["id"], "icerik_hash": icerik_hash or c["icerik_hash"]}


def _reviews(cid: str) -> list[Review]:
    with session_scope() as s:
        rows = s.scalars(
            select(Review).where(
                Review.nesne_turu == "test_case", Review.nesne_id == uuid.UUID(cid)
            )
        ).all()
        s.expunge_all()
        return list(rows)


def _denetim(cid: str, eylem: str) -> int:
    with session_scope() as s:
        return len(
            s.scalars(
                select(AuditEvent).where(
                    AuditEvent.eylem == eylem, AuditEvent.nesne == f"test_case:{cid}"
                )
            ).all()
        )


# --------------------------------------------------------------------------- toplu onay


def test_toplu_onay_kalem_bazli_karisik_sonuc(api: TestClient, cs) -> None:
    rid, (a, b, varsayim, *_) = cs
    yok = str(uuid.uuid4())
    r = api.post(
        "/cases/bulk-decision",
        json={
            "karar": "approve",
            "kalemler": [
                _kalem(a),
                _kalem(varsayim),
                _kalem(b, icerik_hash="bayat"),
                {"case_id": yok, "icerik_hash": "x"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    g = r.json()
    assert (g["karar"], g["onaylanan"], g["basarisiz"]) == ("approve", 1, 3)
    s0, s1, s2, s3 = g["sonuclar"]
    assert [s["case_id"] for s in g["sonuclar"]] == [a["id"], varsayim["id"], b["id"], yok]
    assert s0["basarili"] is True and s0["hata"] is None and s0["kod"] is None
    assert s0["case"]["durum"] == "approved" and s0["case"]["id"] == a["id"]
    assert (s1["basarili"], s1["kod"], s1["case"]) == (False, 422, None)
    assert "varsayıma bağlı" in s1["hata"]
    assert (s2["basarili"], s2["kod"]) == (False, 409) and "görüntüledikten sonra" in s2["hata"]
    assert (s3["basarili"], s3["kod"]) == (False, 404)
    assert [c["durum"] for c in latest_cases(api, rid)][:3] == ["approved", "draft", "draft"]
    # Başarılıya bir review (görülen hash ile), başarısızlara hiç.
    (rev,) = _reviews(a["id"])
    assert rev.karar == "approve" and rev.onaylanan_hash == a["icerik_hash"]
    assert _reviews(varsayim["id"]) == [] and _reviews(b["id"]) == []


def test_toplu_onay_her_casee_ayri_review(api: TestClient, cs) -> None:
    _, (a, b, *_) = cs
    r = api.post(
        "/cases/bulk-decision", json={"karar": "approve", "kalemler": [_kalem(b), _kalem(a)]}
    )
    assert r.status_code == 200, r.text
    g = r.json()
    assert (g["onaylanan"], g["basarisiz"]) == (2, 0)
    assert [s["case"]["id"] for s in g["sonuclar"]] == [b["id"], a["id"]]
    for c in (a, b):
        (rev,) = _reviews(c["id"])
        assert rev.karar == "approve" and rev.onaylanan_hash == c["icerik_hash"]
        assert rev.duzeltme_olculeri["mesafe"] == 0.0
        assert _denetim(c["id"], "review.approve") == 1
    # Hepsi başarısız olsa bile 200 + sonuçlar (onaylı case yeniden onaylanamaz: 409).
    r = api.post("/cases/bulk-decision", json={"karar": "approve", "kalemler": [_kalem(a)]})
    assert r.status_code == 200
    assert (r.json()["onaylanan"], r.json()["sonuclar"][0]["kod"]) == (0, 409)


def test_toplu_onay_savepoint_kalemi_geri_alir(
    api: TestClient, cs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Karar yazıldıktan sonra kalem hata verirse review, durum ve bekleyen denetim geri alınır."""
    _, (a, b, *_) = cs
    gercek = service.decide

    def bozuk(session, cid, user, **kw):
        tc = gercek(session, cid, user, **kw)
        if str(cid) == b["id"]:
            raise service.RequirementChanged("yapay hata")
        return tc

    monkeypatch.setattr(service, "decide", bozuk)
    r = api.post(
        "/cases/bulk-decision", json={"karar": "approve", "kalemler": [_kalem(b), _kalem(a)]}
    )
    g = r.json()
    assert [(s["basarili"], s["kod"]) for s in g["sonuclar"]] == [(False, 409), (True, None)]
    assert g["sonuclar"][0]["hata"] == "yapay hata"
    assert _reviews(b["id"]) == [] and _denetim(b["id"], "review.approve") == 0
    assert len(_reviews(a["id"])) == 1 and _denetim(a["id"], "review.approve") == 1
    assert api.get(f"/cases/{b['id']}").json()["durum"] == "draft"


@pytest.mark.parametrize(
    "govde",
    [
        {"karar": "reject", "kalemler": [{"case_id": str(uuid.uuid4()), "icerik_hash": "h"}]},
        {"karar": "approve", "kalemler": []},
        {"karar": "approve", "kalemler": [{"case_id": "x", "icerik_hash": "h"}]},
        {
            "karar": "approve",
            "kalemler": [{"case_id": str(uuid.uuid4()), "icerik_hash": "h"}],
            "x": 1,
        },
        {
            "karar": "approve",
            "kalemler": [{"case_id": str(uuid.uuid4()), "icerik_hash": "h"} for _ in range(51)],
        },
    ],
)
def test_toplu_onay_gecersiz_govde_422(api: TestClient, cs, govde: dict[str, Any]) -> None:
    assert api.post("/cases/bulk-decision", json=govde).status_code == 422


def test_toplu_onay_tekrar_eden_case_422(api: TestClient, cs) -> None:
    _, (a, *_) = cs
    r = api.post(
        "/cases/bulk-decision", json={"karar": "approve", "kalemler": [_kalem(a), _kalem(a)]}
    )
    assert r.status_code == 422 and "tekrarlanıyor" in r.json()["detail"]


def test_toplu_onay_analist_rolu_ister(api: TestClient, cs, make_user) -> None:
    _, (a, *_) = cs
    login(api, make_user("po"))
    r = api.post("/cases/bulk-decision", json={"karar": "approve", "kalemler": [_kalem(a)]})
    assert r.status_code == 403


# ------------------------------------------------------------------ varsayım doğrulandı


def _dogrula(api: TestClient, c: dict[str, Any], **govde: Any):
    return api.post(
        f"/cases/{c['id']}/assumption-verified",
        json={"icerik_hash": c["icerik_hash"], **govde},
    )


def test_varsayim_dogrulandi_case_i_onaylar(api: TestClient, cs) -> None:
    _, cases = cs
    c = cases[2]
    r = _dogrula(api, c, varsayim_id="A1")
    assert r.status_code == 200, r.text
    g = r.json()
    assert (g["durum"], g["readiness"], g["varsayimlar"]) == ("approved", "ready", [])
    assert g["icerik"]["assumption_refs"] == []
    assert g["icerik"]["expected_result"] == c["icerik"]["expected_result"]
    (rev,) = _reviews(c["id"])
    assert rev.karar == "edit"
    assert rev.gerekce == "Varsayım doğrulandı: A1 — Parola büyük/küçük harf duyarlıdır"
    assert rev.duzeltme_olculeri["varsayim_dogrulandi"] == ["A1"]
    olcu = rev.duzeltme_olculeri
    assert (olcu["beklenen_sonuc_degisti"], olcu["beklenen_sonuc_kaynagi"]) == (False, "insan")
    assert set(olcu["degisen_alanlar"]) == {"assumption_refs", "readiness"}
    assert rev.onaylanan_hash == g["icerik_hash"] != c["icerik_hash"]
    assert _denetim(c["id"], "review.edit") == 1


def test_varsayim_dogrulandi_coklu_kimlik_ve_gerekce(api: TestClient, cs) -> None:
    _, cases = cs
    c = cases[3]
    r = _dogrula(api, c, varsayim_id=["A2", "A1"], gerekce="PO ile teyit edildi")
    assert r.status_code == 200, r.text
    (rev,) = _reviews(c["id"])
    assert rev.gerekce == "PO ile teyit edildi"
    assert rev.duzeltme_olculeri["varsayim_dogrulandi"] == ["A2", "A1"]


def test_varsayim_dogrulandi_hatalari(api: TestClient, cs) -> None:
    _, (hazir, _, tek, iki, soru, bos) = cs
    r = _dogrula(api, tek, varsayim_id="A3")
    assert r.status_code == 422
    assert r.json()["detail"] == "A3 bu case'in varsayımları arasında yok"
    r = _dogrula(api, iki, varsayim_id="A1")
    assert r.status_code == 422 and "başka varsayımı/sorusu var (A2)" in r.json()["detail"]
    r = _dogrula(api, soru, varsayim_id="A1")
    assert r.status_code == 422 and "(Q1)" in r.json()["detail"] and "Düzelt" in r.json()["detail"]
    r = _dogrula(api, bos, varsayim_id="A1")
    assert r.status_code == 422 and r.json()["detail"] == "Beklenen sonuç boş; 'Düzelt' ile yazın"
    r = _dogrula(api, hazir, varsayim_id="A1")
    assert r.status_code == 422 and "arasında yok" in r.json()["detail"]
    # Bayat hash: decide'ın bayat hash hatasıyla aynı sınıf (409 onay_hash_uyusmuyor).
    r = api.post(
        f"/cases/{tek['id']}/assumption-verified",
        json={"icerik_hash": "bayat", "varsayim_id": "A1"},
    )
    assert r.status_code == 409 and r.json()["kod"] == "onay_hash_uyusmuyor"
    # Fazla alan / uzun gerekçe gövde hatasıdır.
    assert _dogrula(api, tek, varsayim_id="A1", x=1).status_code == 422
    assert _dogrula(api, tek, varsayim_id="A1", gerekce="x" * 2001).status_code == 422
    for c in (tek, iki, soru, bos):
        assert _reviews(c["id"]) == []
    # Onaylanmış case artık taslak değil: 409.
    assert _dogrula(api, tek, varsayim_id="A1").status_code == 200
    taze = api.get(f"/cases/{tek['id']}").json()
    r = _dogrula(api, taze, varsayim_id="A1")
    assert r.status_code == 409 and "taslak" in r.json()["detail"]


def test_varsayim_dogrulandi_eski_case_422(api: TestClient, cs) -> None:
    rid, _ = cs
    with session_scope() as s:
        service.store_cases(
            s,
            s.get(Requirement, rid),
            [eski_case_icerik(title="Eski biçimli case", ref="AC2")],
            uretim_no=7,
            kanal="portal",
            ai_call_id=None,
            uretim_modu="replay",
        )
    eski = next(c for c in latest_cases(api, rid) if c["uretim_no"] == 7)
    r = _dogrula(api, eski, varsayim_id="A1")
    assert r.status_code == 422 and r.json()["detail"] == "Eski biçimli case'te varsayım yok"
