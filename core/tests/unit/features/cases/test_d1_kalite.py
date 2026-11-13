"""011 D1 şeridi — review/denetim satırlarının ve yayın kapısının sağlamlığı.

Takılı satır (#1), set değişince yeniden hedefleme (#6), aynı setin yeniden denetimi (#7),
maliyet sınırı (#8), kapının fail-closed ve set üyeliği (#9), önbellek (#10).
Gerçek Postgres, REPLAY golden'ları (TPD-4), gerçek iş kuyruğu.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tests.unit.features.cases.helpers import latest_cases, login, run_jobs
from tp_core.features.cases import denetim_akisi, review
from tp_core.features.cases.jobs import on_worker_start
from tp_core.features.publish import service as publish
from tp_core.integrations.agent_probe import denetim
from tp_core.models import (
    AiCall,
    AuditEvent,
    CaseSetAudit,
    CaseSetReview,
    Requirement,
    session_scope,
)
from tp_core.ports import CaseSetAuditResult


@pytest.fixture
def gecit(replay_gateway: Any) -> Iterator[Any]:
    denetim.set_gateway_factory(lambda: replay_gateway)
    denetim_akisi.bind_gate()
    yield replay_gateway
    denetim.set_gateway_factory(None)
    review.set_gateway_factory(None)
    denetim_akisi.bind_gate()


def _uret(api: TestClient, engine: Engine, make_user, make_requirement) -> uuid.UUID:
    rid = make_requirement()
    login(api, make_user("analyst"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    return rid


def _onayla(api: TestClient, rid: uuid.UUID) -> list[dict[str, Any]]:
    cases = latest_cases(api, rid)
    for c in cases:
        r = api.post(
            f"/cases/{c['id']}/decision", json={"karar": "approve", "icerik_hash": c["icerik_hash"]}
        )
        assert r.status_code == 200, r.text
    return cases


def _set_degistir(api: TestClient, rid: uuid.UUID) -> None:
    """İkinci case'i taslağa alıp reddeder (set hash'i değişir)."""
    c = latest_cases(api, rid)[1]
    api.post(
        f"/cases/{c['id']}/decision", json={"karar": "reopen", "icerik_hash": c["icerik_hash"]}
    )
    r = api.post(
        f"/cases/{c['id']}/decision",
        json={"karar": "reject", "icerik_hash": c["icerik_hash"], "ret_nedeni": "duplicate"},
    )
    assert r.status_code == 200, r.text


def _isi_oldur(engine: Engine, job_id: uuid.UUID) -> None:
    """İş dışı ölüm: `reap_stale`/`release_orphans` işi `failed` yazar, işleyici hiç koşmaz."""
    with engine.begin() as c:
        c.execute(
            text("UPDATE job SET durum = 'failed', son_hata = 'zaman aşımı' WHERE id = :i"),
            {"i": job_id},
        )


def _kalemler(api: TestClient, rid: uuid.UUID) -> list[dict[str, Any]]:
    return api.get("/publish/preview", params={"requirement_id": str(rid)}).json()["kalemler"]


# ----------------------------------------------------------------------- #1 takılı satır


def test_isi_olen_review_kilit_olmaz_ve_supurulur(
    api: TestClient, engine: Engine, make_user, make_requirement, gecit
) -> None:
    rid = _uret(api, engine, make_user, make_requirement)
    r = api.post(f"/requirements/{rid}/case-review")
    assert r.status_code == 202 and r.json()["calisiyor"] is True
    with session_scope() as s:
        takili = s.scalars(select(CaseSetReview).where(CaseSetReview.durum == "bekliyor")).one()
        takili_id, job_id = takili.id, takili.job_id
    _isi_oldur(engine, job_id)
    # İşi ölmüş satır "sürüyor" görünmez ve yeni review'u engellemez.
    assert api.get(f"/requirements/{rid}/case-review").json()["calisiyor"] is False
    r = api.post(f"/requirements/{rid}/case-review")
    assert r.status_code == 202 and r.json()["review"]["id"] != str(takili_id)
    with session_scope() as s:
        eski = s.get(CaseSetReview, takili_id)
        assert eski.durum == "hata" and eski.hata.startswith(review.YARIDA_KALDI)
    run_jobs(engine)
    assert api.get(f"/requirements/{rid}/case-review").json()["review"]["durum"] == "tamamlandi"


def test_isi_olen_denetim_kapida_hata_gorunur_ve_worker_supurur(
    api: TestClient, engine: Engine, make_user, make_requirement, gecit
) -> None:
    rid = _uret(api, engine, make_user, make_requirement)
    _onayla(api, rid)
    assert api.post(f"/requirements/{rid}/case-audit").status_code == 202
    with session_scope() as s:
        satir = s.scalars(select(CaseSetAudit)).one()
        aid, job_id = satir.id, satir.job_id
    _isi_oldur(engine, job_id)
    v = api.get(f"/requirements/{rid}/case-audit").json()
    assert v["calisiyor"] is False and v["gonder_engeli"] is None
    assert v["yayin_engeli"].startswith("Denetim yapılamadı: iş yarıda kaldı")
    with engine.begin() as conn:
        on_worker_start(conn)  # açılış/periyodik süpürme
    with session_scope() as s:
        satir = s.get(CaseSetAudit, aid)
        assert satir.durum == "hata" and "zaman aşımı" in satir.hata
        eylemler = list(s.scalars(select(AuditEvent.eylem)))
    assert "cases.audit_failed" in eylemler
    # Yeniden gönderilebilir (kalıcı kilit yok).
    assert api.post(f"/requirements/{rid}/case-audit").status_code == 202
    run_jobs(engine)
    assert api.get(f"/requirements/{rid}/case-audit").json()["guncel_karar"]["karar"] == "KABUL"


def test_girdi_hatasi_ve_gecersiz_karar_satiri_kapatir(
    api: TestClient, engine: Engine, make_user, make_requirement, gecit, monkeypatch
) -> None:
    rid = _uret(api, engine, make_user, make_requirement)
    _onayla(api, rid)
    monkeypatch.setattr(denetim_akisi, "build_request", lambda *a: 1 / 0)
    api.post(f"/requirements/{rid}/case-audit")
    run_jobs(engine)
    d = api.get(f"/requirements/{rid}/case-audit").json()["denetim"]
    assert d["durum"] == "hata" and "girdisi kurulamadı" in d["hata"]
    monkeypatch.undo()

    class Sahte:
        def audit_case_set(self, istek: Any) -> CaseSetAuditResult:
            # Sözleşme dışı karar (port doğrulamasını atlayan bir uygulama): kod yine reddeder.
            return CaseSetAuditResult.model_construct(
                decision="ONAYLA",
                decision_rationale="x",
                findings=[],
                missing_scenarios=[],
                talep_no="AP-1",
                kaynak="tp-gecit",
            )

    import tp_core.integrations.agent_probe as ap

    monkeypatch.setattr(ap, "get_agent_probe", lambda: Sahte())
    assert api.post(f"/requirements/{rid}/case-audit").status_code == 202
    run_jobs(engine)
    v = api.get(f"/requirements/{rid}/case-audit").json()
    assert v["denetim"]["durum"] == "hata" and "geçersiz yanıt" in v["denetim"]["hata"]
    assert v["guncel_karar"] is None and v["yayin_engeli"].startswith("Denetim yapılamadı")


# --------------------------------------------------------------- #6 set değişince


def test_denetim_istegi_set_degisince_model_cagrilmaz(
    api: TestClient, engine: Engine, make_user, make_requirement, gecit
) -> None:
    rid = _uret(api, engine, make_user, make_requirement)
    _onayla(api, rid)
    assert api.post(f"/requirements/{rid}/case-audit").status_code == 202
    _set_degistir(api, rid)
    run_jobs(engine)
    with session_scope() as s:
        satir = s.scalars(select(CaseSetAudit)).one()
        assert satir.durum == "hata" and satir.hata == review.SET_DEGISTI_HATA
        assert s.scalars(select(AiCall).where(AiCall.amac == "case_audit")).all() == []


def test_review_set_degisince_yeni_sete_planlanir(
    api: TestClient, engine: Engine, make_user, make_requirement, gecit
) -> None:
    rid = _uret(api, engine, make_user, make_requirement)
    _onayla(api, rid)
    api.post(f"/requirements/{rid}/case-review")
    _set_degistir(api, rid)
    run_jobs(engine)
    with session_scope() as s:
        req = s.get(Requirement, rid)
        guncel = review.set_hash(s, req)
        satirlar = s.scalars(select(CaseSetReview).order_by(CaseSetReview.olusturma)).all()
        hedeflenen = [x for x in satirlar if x.hata == review.SET_DEGISTI_HATA]
        assert len(hedeflenen) == 1
        yeni = [x for x in satirlar if x.set_hash == guncel]
        assert len(yeni) == 1 and yeni[0].durum != "bekliyor"  # iş koştu (REPLAY-MISS ya da tamam)


# ------------------------------------------------------------- #7 yeniden denetim yok


def test_ayni_set_yeniden_denetlenemez_ve_kapi_en_sert_karari_okur(
    api: TestClient, engine: Engine, make_user, make_requirement, gecit
) -> None:
    rid = _uret(api, engine, make_user, make_requirement)
    _onayla(api, rid)
    api.post(f"/requirements/{rid}/case-audit")
    run_jobs(engine)
    v = api.get(f"/requirements/{rid}/case-audit").json()
    assert v["guncel_karar"]["karar"] == "KABUL" and v["yayin_engeli"] is None
    assert v["gonder_engeli"].startswith("Bu set zaten denetlendi (karar: KABUL)")
    # UX4 Bulgu 9: KABUL sonrası gerekçe "düzeltip yeniden gönderin" demez.
    assert "düzeltip" not in v["gonder_engeli"] and "yeniden denetim gerekmez" in v["gonder_engeli"]
    r = api.post(f"/requirements/{rid}/case-audit")
    assert r.status_code == 409 and "zaten denetlendi" in r.json()["detail"]
    # Ek savunma: aynı hash için daha sert bir karar varsa (eski satır) kapı onu okur.
    with session_scope() as s:
        req = s.get(Requirement, rid)
        h = review.set_hash(s, req)
        s.add(
            CaseSetAudit(
                requirement_id=rid,
                set_hash=h,
                durum="tamamlandi",
                karar="ENGELLE",
                model_karari="ENGELLE",
                icerik={"decision_rationale": "politika ihlali"},
            )
        )
    v = api.get(f"/requirements/{rid}/case-audit").json()
    assert v["guncel_karar"]["karar"] == "ENGELLE"
    assert v["yayin_engeli"] == "ENGELLE: politika ihlali"
    assert {k["islem"] for k in _kalemler(api, rid)} == {"blocked_gate"}


# ------------------------------------------------------------------ #8 maliyet sınırı


def test_review_ve_denetim_gunluk_siniri(
    api: TestClient, engine: Engine, make_user, make_requirement, gecit, monkeypatch
) -> None:
    rid = _uret(api, engine, make_user, make_requirement)  # otomatik review: 1
    monkeypatch.setenv(review.REVIEW_SINIRI_ORTAMI, "1")
    r = api.post(f"/requirements/{rid}/case-review")
    assert r.status_code == 429 and r.json()["kod"] == "hiz_siniri"
    _onayla(api, rid)
    monkeypatch.setenv(denetim_akisi.DENETIM_SINIRI_ORTAMI, "1")
    with session_scope() as s:
        s.add(CaseSetAudit(requirement_id=rid, set_hash="baska", durum="hata"))
    v = api.get(f"/requirements/{rid}/case-audit").json()
    assert "son 24 saatte en çok 1 denetim" in v["gonder_engeli"]
    r = api.post(f"/requirements/{rid}/case-audit")
    assert r.status_code == 429 and r.json()["kod"] == "hiz_siniri"
    monkeypatch.setenv(denetim_akisi.DENETIM_SINIRI_ORTAMI, "0")  # 0 = sınırsız
    assert api.post(f"/requirements/{rid}/case-audit").status_code == 202


def test_otomatik_review_sinirda_atlanir(
    api: TestClient, engine: Engine, make_user, make_requirement, gecit, monkeypatch
) -> None:
    rid = _uret(api, engine, make_user, make_requirement)
    _set_degistir(api, rid)
    monkeypatch.setenv(review.REVIEW_SINIRI_ORTAMI, "1")
    with session_scope() as s:
        assert review.schedule_review(s, s.get(Requirement, rid)) is None
    with session_scope() as s:
        olay = s.scalars(select(AuditEvent).where(AuditEvent.eylem == "cases.review_skipped")).one()
        assert "son 24 saatte" in olay.ozet["neden"]


# ------------------------------------------------------------- #9/#10 yayın kapısı


def test_kapi_bagli_degilken_fail_closed(
    api: TestClient, engine: Engine, make_user, make_requirement, gecit, monkeypatch
) -> None:
    rid = _uret(api, engine, make_user, make_requirement)
    _onayla(api, rid)
    publish.set_gate_check(None)
    k = _kalemler(api, rid)
    assert {x["islem"] for x in k} == {"blocked_gate"}
    assert k[0]["neden"] == publish.yayinlanamaz(publish.KAPI_BAGLI_DEGIL)
    monkeypatch.setenv("TP_DENETIM_KAPISI", "off")
    assert {x["islem"] for x in _kalemler(api, rid)} == {"create"}


def test_kapi_set_disi_casei_engeller_ve_onizlemede_bir_kez_hesaplanir(
    api: TestClient, engine: Engine, make_user, make_requirement, gecit, monkeypatch
) -> None:
    rid = _uret(api, engine, make_user, make_requirement)
    cases = _onayla(api, rid)
    api.post(f"/requirements/{rid}/case-audit")
    run_jobs(engine)
    sayac = {"n": 0}
    asil = denetim_akisi.gate_state

    def sayan(session: Any, req: Any) -> Any:
        sayac["n"] += 1
        return asil(session, req)

    monkeypatch.setattr(denetim_akisi, "gate_state", sayan)
    assert {x["islem"] for x in _kalemler(api, rid)} == {"create"}
    assert sayac["n"] == 1  # iki case, tek kapı hesabı
    # Denetlenen sette olmayan case (ör. eski içerik) KABUL'e rağmen yayınlanamaz.
    asil_set = review.current_cases
    monkeypatch.setattr(
        review,
        "current_cases",
        lambda s, req: [tc for tc in asil_set(s, req) if str(tc.id) != cases[0]["id"]],
    )
    with session_scope() as s:
        from tp_core.models import TestCase

        tc = s.get(TestCase, uuid.UUID(cases[0]["id"]))
        assert denetim_akisi.gate_check(s, tc) == denetim_akisi.SET_DISI
