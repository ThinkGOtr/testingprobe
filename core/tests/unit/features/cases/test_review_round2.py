"""Review 2. tur düzeltmeleri: önceki içerik dedup'ı, IDE taslağı korunur, fark, review süresi."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text

from tp_core.features.cases import metrics
from tp_core.gateway.testing import text_response
from tp_core.models import AuditEvent, Requirement, TestCase, session_scope

from .helpers import case_icerik, latest_cases, login, onayla, run_jobs


def _karar(api: TestClient, c: dict[str, Any], **govde: Any):
    return api.post(f"/cases/{c['id']}/decision", json={"icerik_hash": c["icerik_hash"], **govde})


def _story_degisti_ve_yeniden_onaylandi(rid: uuid.UUID, po) -> None:
    """Jira açıklaması değişti (gerçek `apply_content_change`) → yeni metin PO onaylı."""
    from tp_core.features.requirements import flow
    from tp_core.workflow.service import SYSTEM, content_hash_of, record_approval, transition

    with session_scope() as s:
        req = s.get(Requirement, rid, with_for_update=True)
        flow.apply_content_change(
            s,
            req,
            req.baslik,
            req.aciklama + " Hesap kilitliyse giriş yapılmaz.",
            list(req.kabul_kriterleri),
            "system",
            sebep="Jira içeriği değişti",
        )
    with session_scope() as s:
        req = s.get(Requirement, rid)
        assert req.durum == "new" and req.onaylanan_hash is None
        for once, sonra in (("new", "in_review"), ("in_review", "doc_final")):
            transition(s, req, sonra, SYSTEM, once)
        transition(s, req, "pending_po", SYSTEM, "doc_final")
        record_approval(s, req, po, "po_approve", beklenen_hash=content_hash_of(req))
        transition(s, req, "po_approved", po, "pending_po")


# ------------------------------- 1) önceki içerik için yayınlanmış case'ler tekrar sayılmaz


def test_story_degisince_yayinli_eski_caseler_tekrar_ve_kapsam_sayilmaz(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, targets
) -> None:
    from tests.unit.features.publish.test_publish import _ctx
    from tp_core.features.publish import service as publish

    ciktilar = [case_icerik(), case_icerik(title="Hatalı parola", ref="AC2")]
    fake_gateway([text_response({"cases": ciktilar}), text_response({"cases": ciktilar})])
    rid = make_requirement()
    testci, analist = make_user("tester"), make_user("analyst")
    po = make_user("po")
    login(api, testci)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    eskiler = latest_cases(api, rid)
    for c in eskiler:
        onayla(api, c, testci, analist)
    sonuc = publish.run_publish(_ctx([c["id"] for c in eskiler]), engine)
    assert [r["durum"] for r in sonuc["sonuclar"]] == ["created", "created"]

    _story_degisti_ve_yeniden_onaylandi(rid, po)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    (is_,) = run_jobs(engine)
    deger = is_.deger
    # Aynı model çıktısı (REPLAY'de her zaman) yeni metin için yeniden taslak olarak düşer.
    assert deger["case_sayisi"] == 2 and deger["tekrar"] == []
    assert sorted(deger["onceki_icerik_case_ids"]) == sorted(c["id"] for c in eskiler)
    assert any("Önceki içerik için yayınlanmış 2 case" in u for u in deger["uyarilar"])

    hepsi = {c["id"]: c for c in latest_cases(api, rid)}
    yeni = [c for c in hepsi.values() if c["durum"] == "draft"]
    assert len(yeni) == 2 and not any(c["onceki_icerik"] for c in yeni)
    for c in eskiler:
        assert hepsi[c["id"]]["durum"] == "published" and hepsi[c["id"]]["onceki_icerik"]
        assert any("önceki" in u for u in hepsi[c["id"]]["uyarilar"])

    m = api.get(f"/requirements/{rid}/case-metrics").json()
    assert sorted(m["onceki_icerik_case_ids"]) == sorted(c["id"] for c in eskiler)
    assert m["uyarilar"] and m["kapsanmayan_ac"] == []
    # Yeni taslaklar reddedilirse kapsam eski (yayınlı) case'lerden hesaplanmaz.
    with session_scope() as s:
        from tp_core.features.cases.service import coverage_gaps

        for c in yeni:
            s.execute(
                text("UPDATE test_case SET durum = 'superseded' WHERE id = :i"),
                {"i": uuid.UUID(c["id"])},
            )
        assert coverage_gaps(s, s.get(Requirement, rid)) == ["AC1", "AC2"]
        s.rollback()


# ------------------------------------------- 2) portal üretimi IDE taslaklarını silmez


def test_portal_uretimi_ide_taslaklarini_korur(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    from tp_core.features.cases.service import submit_drafts
    from tp_core.workflow.service import Principal

    rid = make_requirement()
    testci = make_user("tester")
    ide = Principal(testci.id, testci.kullanici_adi, "tester", kanal="ide", kapsam="submit")
    with session_scope() as s:
        sonuc = submit_drafts(s, "TPD-4", [case_icerik(title="IDE: kilitli hesap", ref="AC2")], ide)
    (ide_case,) = sonuc["eklenen"]

    fake_gateway([text_response({"cases": [case_icerik()]})])
    login(api, testci)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    (is_,) = run_jobs(engine)
    assert is_.deger["korunan_ide_taslak"] == 1 and is_.deger["superseded"] == 0
    assert any("IDE" in u for u in is_.deger["uyarilar"])
    durum = {c["id"]: (c["kanal"], c["durum"]) for c in latest_cases(api, rid)}
    assert durum[ide_case["case_id"]] == ("ide", "draft")
    m = api.get(f"/requirements/{rid}/case-metrics").json()
    assert m["kanallar"] == {"ide": 1, "portal": 1}


# ------------------------------------------- 3) AI özgün ↔ insan düzeltmesi farkı (§8.10)


def test_duzeltilen_case_ai_ozgunu_fark_ve_neden_doner(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    fake_gateway([text_response({"cases": [case_icerik(), case_icerik(title="B", ref="AC2")]})])
    rid = make_requirement()
    login(api, make_user("tester"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    a, b = latest_cases(api, rid)
    assert a["ai_icerik"] is None and a["fark"] == [] and a["duzeltme_nedeni"] is None

    ozgun = dict(a["icerik"])
    yeni = {**ozgun, "expected_result": ozgun["expected_result"] + " ve sepet boştur"}
    r = _karar(api, a, karar="edit", icerik=yeni)
    assert r.status_code == 200, r.text
    tek = api.get(f"/cases/{a['id']}").json()
    assert tek["ai_icerik"] == ozgun and tek["icerik"] == yeni
    assert tek["fark"] == [
        {
            "alan": "expected_result",
            "etiket": "Beklenen sonuç",
            "once": ozgun["expected_result"],
            "sonra": yeni["expected_result"],
        }
    ]
    assert tek["kucuk_duzeltme"] is False
    assert "Küçük düzeltme sayılmadı" in tek["duzeltme_nedeni"]
    assert "beklenen sonuç" in tek["duzeltme_nedeni"]

    # Testçi "beklenen sonuç anlamca değişmedi" derse küçük düzeltme sayılır ve nedeni yazılır.
    yeni_b = {**b["icerik"], "title": b["icerik"]["title"] + "!"}
    assert _karar(api, b, karar="edit", icerik=yeni_b, beklenen_anlam_degisti=False).status_code
    tek_b = api.get(f"/cases/{b['id']}").json()
    assert tek_b["kucuk_duzeltme"] is True
    assert tek_b["duzeltme_nedeni"].startswith("Küçük düzeltme sayıldı")
    assert [f["alan"] for f in tek_b["fark"]] == ["title"]


def test_alan_farki_adim_etiketleri_ve_normalize() -> None:
    a = case_icerik()
    b = {**a, "steps": [dict(a["steps"][0]), {**a["steps"][1], "expected": "Sepet açılır"}]}
    b["title"] = a["title"].upper()  # yalnızca büyük/küçük harf: fark sayılmaz
    (f,) = metrics.field_diff(a, b)
    assert f["alan"] == "steps[2].expected" and f["etiket"] == "Adım 2 — beklenen"
    assert (f["once"], f["sonra"]) == ("Katalog açılır", "Sepet açılır")


# --------------------------------------------- 4) review süresi = aralıkların birleşimi


def test_aralik_birlesimi() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    s = timedelta(seconds=1)
    assert metrics.union_ms([]) == 0
    # Üç kart aynı anda görünür, 60 sn arayla karar: duvar saati 180 sn (toplam 360 sn değil).
    assert metrics.union_ms([(t0, t0 + 60 * s), (t0, t0 + 120 * s), (t0, t0 + 180 * s)]) == 180000
    # Ayrık aralıklar toplanır.
    assert metrics.union_ms([(t0, t0 + 10 * s), (t0 + 20 * s, t0 + 25 * s)]) == 15000


def test_ortusen_goruntulemelerde_review_suresi_sisirilmez(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway
) -> None:
    cases = [case_icerik(title=f"Case {i}", ref="AC1") for i in range(3)]
    fake_gateway([text_response({"cases": cases})])
    rid = make_requirement()
    testci = make_user("tester")
    login(api, testci)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    kartlar = latest_cases(api, rid)
    # Portal: üç kart aynı anda yarı görünür → üçü de 60 sn önce "viewed" (IntersectionObserver).
    with engine.begin() as c:
        for k in kartlar:
            c.execute(
                text(
                    "INSERT INTO case_goruntuleme (id, test_case_id, user_id, zaman) "
                    "VALUES (:id, :c, :u, now() - interval '60 seconds')"
                ),
                {"id": uuid.uuid4(), "c": uuid.UUID(k["id"]), "u": testci.id},
            )
    for k in kartlar:
        assert _karar(api, k, karar="accept").status_code == 200
    m = api.get(f"/requirements/{rid}/case-metrics").json()
    assert m["review_sure_yontemi"] == "aralik_birlesimi"
    assert m["kart_sure_toplam_ms"] >= 3 * 60000  # kart başına süreler (bilgi amaçlı)
    assert 60000 <= m["review_sure_ms"] < 75000  # duvar saati: ~60 sn, 180 sn değil
    assert m["ort_review_sure_ms"] == pytest.approx(m["review_sure_ms"] / 3, abs=1)


def test_onceki_icerik_uyarisi_denetim_kaydinda(
    api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway, targets
) -> None:
    from tests.unit.features.publish.test_publish import _ctx
    from tp_core.features.publish import service as publish

    cikti = [case_icerik()]
    fake_gateway([text_response({"cases": cikti}), text_response({"cases": cikti})])
    rid = make_requirement()
    testci = make_user("tester")
    login(api, testci)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    (a,) = latest_cases(api, rid)
    onayla(api, a, testci, make_user("analyst"))
    publish.run_publish(_ctx([a["id"]]), engine)
    _story_degisti_ve_yeniden_onaylandi(rid, make_user("po"))
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    with session_scope() as s:
        ev = s.scalars(
            select(AuditEvent)
            .where(AuditEvent.eylem == "cases.generated")
            .order_by(AuditEvent.id.desc())
        ).first()
        assert ev.ozet["onceki_icerik_case_ids"] == [a["id"]]
        assert s.get(TestCase, uuid.UUID(a["id"])).durum == "published"
