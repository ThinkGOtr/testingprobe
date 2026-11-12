"""Case kararları (Constitution I, X; specs/012-rol-yetki §5): Testçi kararı + Analist son onayı,
hash bağı, şema, ölçüm, Taslağa al, geri gönderme, review tamam, developer süzgeci."""

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

from .helpers import case_icerik, karar_ver, latest_cases, login, onayla, rol_ol, run_jobs


@pytest.fixture
def hazir(api: TestClient, engine: Engine, make_user, make_requirement, fake_gateway):
    """3 draft case'li, PO onaylı gereksinim + oturum açmış Testçi (ve bir Analist hesabı)."""
    cases = [
        case_icerik(),
        case_icerik(title="Hatalı parola mesajı", ref="AC2", type="negative"),
        case_icerik(title="Boş kullanıcı adı", ref="AC2", type="boundary"),
    ]
    fake_gateway([text_response({"cases": cases})])
    rid = make_requirement()
    testci = make_user("tester")
    analist = make_user("analyst")
    login(api, testci)
    assert api.post(f"/requirements/{rid}/generate-cases").status_code == 202
    run_jobs(engine)
    return rid, testci, analist


_karar = karar_ver


def _authz_red(izin: str) -> list[dict[str, Any]]:
    with session_scope() as s:
        return [
            e.ozet
            for e in s.scalars(select(AuditEvent).where(AuditEvent.eylem == "authz.denied"))
            if e.ozet.get("izin") == izin
        ]


def test_karar_hash_ister_ve_bayat_hash_409(api: TestClient, hazir) -> None:
    rid, _, _ = hazir
    c = latest_cases(api, rid)[0]
    r = api.post(f"/cases/{c['id']}/decision", json={"karar": "accept"})
    assert r.status_code == 422 and "icerik_hash" in r.json()["detail"]
    r = api.post(f"/cases/{c['id']}/decision", json={"karar": "accept", "icerik_hash": "eski"})
    assert r.status_code == 409
    assert latest_cases(api, rid)[0]["durum"] == "draft"


def test_testci_kabulu_ready_ve_review_kaydi(api: TestClient, hazir) -> None:
    rid, testci, _ = hazir
    c = latest_cases(api, rid)[0]
    assert api.post(f"/cases/{c['id']}/viewed").json()["yeni"] is True
    assert api.post(f"/cases/{c['id']}/viewed").json()["yeni"] is False  # ilk görüntüleme sabit
    time.sleep(0.05)
    r = _karar(api, c, karar="accept")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["durum"] == "ready" and out["karar"] == "accept"
    assert out["testci_karari"] == "accept" and out["testci"] == testci.kullanici_adi
    assert out["son_onay"] is None
    # Testçi kabulü onay hash'i yazmaz ve yayını açmaz (son onay Analistindir).
    assert out["onaylanan_hash"] is None and out["karar_veren"] == testci.kullanici_adi
    assert out["review_sure_ms"] is not None and out["review_sure_ms"] >= 40
    with session_scope() as s:
        rv = s.scalars(select(Review).where(Review.nesne_id == uuid.UUID(c["id"]))).one()
        assert rv.user_id == testci.id and rv.kanal == "portal" and rv.karar == "accept"
        assert rv.onaylanan_hash == c["icerik_hash"]
        assert rv.duzeltme_olculeri["ilk_karar"] is True
        assert not approved_hash_matches(s, s.get(TestCase, uuid.UUID(c["id"])))


def test_analist_son_onayi_ready_den_approved(api: TestClient, hazir) -> None:
    rid, testci, analist = hazir
    c = latest_cases(api, rid)[0]
    out = onayla(api, c, testci, analist)
    assert out["durum"] == "approved" and out["karar"] == "approve"
    assert out["testci_karari"] == "accept" and out["testci"] == testci.kullanici_adi
    assert out["son_onay"]["karar"] == "approve"
    assert out["son_onay"]["veren"] == analist.kullanici_adi
    assert out["onaylanan_hash"] == c["icerik_hash"]
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(c["id"]))
        assert approved_hash_matches(s, tc)
        kararlar = s.scalars(
            select(Review.karar).where(Review.nesne_id == tc.id).order_by(Review.sira)
        ).all()
        assert kararlar == ["accept", "approve"]


def test_son_onay_yalnizca_ready_case(api: TestClient, hazir) -> None:
    rid, _, analist = hazir
    c = latest_cases(api, rid)[0]
    rol_ol(api, analist)
    r = _karar(api, c, karar="approve")
    assert r.status_code == 409 and "ready" in r.json()["detail"]
    assert latest_cases(api, rid)[0]["durum"] == "draft"


def test_analist_testci_karari_veremez(api: TestClient, hazir) -> None:
    rid, _, analist = hazir
    c = latest_cases(api, rid)[0]
    rol_ol(api, analist)
    for govde in (
        {"karar": "accept"},
        {"karar": "reject", "ret_nedeni": "duplicate"},
        {"karar": "edit", "icerik": {**c["icerik"], "title": "x"}},
        {"karar": "reopen"},
    ):
        r = _karar(api, c, **govde)
        assert r.status_code == 403 and r.json()["kod"] == "yetki_yok", (govde, r.text)
    red = _authz_red("case.decide")
    assert len(red) == 4 and {e["rol"] for e in red} == {"analyst"}
    assert latest_cases(api, rid)[0]["durum"] == "draft"


def test_testci_son_onay_veremez(api: TestClient, hazir) -> None:
    rid, _, _ = hazir
    c = latest_cases(api, rid)[0]
    r = _karar(api, c, karar="accept")
    hazir_c = r.json()
    for govde in ({"karar": "approve"}, {"karar": "send_back", "gerekce": "x"}):
        r = _karar(api, hazir_c, **govde)
        assert r.status_code == 403 and r.json()["kod"] == "yetki_yok", r.text
    red = _authz_red("case.approve")
    assert len(red) == 2 and red[0]["rol"] == "tester"
    assert red[0]["neden"] == "rol"
    assert latest_cases(api, rid)[0]["durum"] == "ready"
    # Review-complete de son onay iznidir.
    assert api.post(f"/requirements/{rid}/review-complete").status_code == 403


def test_geri_gonderme_gerekce_ister_ve_taslaga_doner(api: TestClient, hazir) -> None:
    rid, testci, analist = hazir
    c = latest_cases(api, rid)[0]
    hazir_c = _karar(api, c, karar="accept").json()
    rol_ol(api, analist)
    for gerekce in (None, "   "):
        r = _karar(api, hazir_c, karar="send_back", gerekce=gerekce)
        assert r.status_code == 422 and "gerekçe" in r.json()["detail"], r.text
    r = _karar(api, hazir_c, karar="send_back", gerekce="AC1 ön koşulu eksik")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["durum"] == "draft" and out["karar"] == "send_back"
    assert out["son_onay"] == {
        "karar": "send_back",
        "veren": analist.kullanici_adi,
        "zaman": out["son_onay"]["zaman"],
        "gerekce": "AC1 ön koşulu eksik",
    }
    # Testçinin önceki kararı ölçüm alanlarında korunur.
    assert out["testci_karari"] == "accept"
    # Geri gönderilen case yeniden kabul edilmeden onaylanamaz.
    assert _karar(api, out, karar="approve").status_code == 409
    rol_ol(api, testci)
    assert _karar(api, out, karar="accept").json()["durum"] == "ready"
    m = api.get(f"/requirements/{rid}/case-metrics").json()
    assert m["son_onay"]["geri_gonderilen"] == 1 and m["son_onay"]["bekleyen"] == 1
    assert m["ilk_kararlar"] == {"accept": 1}  # geri gönderme Testçi kabul ölçümüne girmez


def test_bayat_testci_karariyla_onay_reddedilir(api: TestClient, engine: Engine, hazir) -> None:
    """Testçi kararından sonra içerik değiştiyse (ör. yarış) son onay 409 olur."""
    rid, _, analist = hazir
    c = latest_cases(api, rid)[0]
    _karar(api, c, karar="accept")
    yeni = {**c["icerik"], "title": "Arka planda değişti"}
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(c["id"]))
        tc.icerik = yeni
        tc.icerik_hash = content_hash(yeni)
    rol_ol(api, analist)
    guncel = latest_cases(api, rid)[0]
    r = _karar(api, guncel, karar="approve")
    assert r.status_code == 409 and "Testçi kararından sonra" in r.json()["detail"], r.text
    assert latest_cases(api, rid)[0]["durum"] == "ready"


def test_kabul_eden_hesap_son_onayi_veremez(api: TestClient, hazir) -> None:
    """Görevler ayrılığı: kabul eden hesap ile onaylayan hesap aynı olamaz (servis savunması)."""
    from tp_core.features.cases import service
    from tp_core.workflow.service import ApprovalNotAllowed, Principal

    rid, testci, _ = hazir
    c = latest_cases(api, rid)[0]
    _karar(api, c, karar="accept")
    # Aynı hesap kimliğiyle analist rolü (rol değişse de hesap aynı): reddedilir.
    ayni = Principal(testci.id, testci.kullanici_adi, "analyst")
    with session_scope() as s, pytest.raises(ApprovalNotAllowed, match="görevler ayrılığı"):
        service.decide(s, uuid.UUID(c["id"]), ayni, karar="approve", icerik_hash=c["icerik_hash"])


def test_duzeltme_sema_dogrular_ve_olcer(api: TestClient, hazir) -> None:
    rid, _, _ = hazir
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
    assert out["durum"] == "ready" and out["surum"] == 2
    assert out["icerik"] == yeni and out["icerik_hash"] == content_hash(yeni)
    assert out["onaylanan_hash"] is None
    assert 0 < out["duzeltme_olcusu"] <= 0.15 and out["kucuk_duzeltme"] is True
    with session_scope() as s:
        rv = s.scalars(select(Review).where(Review.nesne_id == uuid.UUID(c["id"]))).one()
        assert rv.once == {"icerik": c["icerik"]} and rv.sonra == {"icerik": yeni}
        assert rv.duzeltme_olculeri["degisen_alanlar"] == ["title"]


def test_ret_taksonomi_ister(api: TestClient, hazir) -> None:
    rid, _, _ = hazir
    c = latest_cases(api, rid)[1]
    assert _karar(api, c, karar="reject").status_code == 422
    assert _karar(api, c, karar="reject", ret_nedeni="uydurma").status_code == 422
    r = _karar(api, c, karar="reject", ret_nedeni="hallucinated_step")
    assert r.status_code == 200 and r.json()["durum"] == "rejected"
    assert r.json()["ret_nedeni"] == "hallucinated_step"


def test_karar_yalnizca_taslakta_ve_taslaga_al(api: TestClient, engine: Engine, hazir) -> None:
    rid, testci, analist = hazir
    c = latest_cases(api, rid)[0]
    onayla(api, c, testci, analist)
    r = _karar(api, c, karar="reject", ret_nedeni="duplicate")
    assert r.status_code == 409 and "Taslağa al" in r.json()["detail"]
    assert _karar(api, c, karar="edit", icerik={**c["icerik"], "title": "x"}).status_code == 409
    assert _karar(api, c, karar="reopen", icerik_hash="eski").status_code == 409
    # Onaylı case'i Testçi taslağa alır: onay düşer.
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
        assert geri and geri[0].aktor == testci.kullanici_adi
        assert geri[0].ozet["sebep"].startswith("Taslağa al")
    # Taslağa alma kayıtlı, onaylamayan bir karardır: eski 'approve' kapıyı yeniden açamaz.
    with session_scope() as s:
        tc = s.get(TestCase, uuid.UUID(c["id"]))
        son = latest_review(s, "test_case", tc.id)
        assert son is not None and son.karar == "reopen" and son.gerekce == "yeniden bakılacak"
        assert not approved_hash_matches(s, tc)
        with pytest.raises(GateClosed):
            transition(s, tc, "ready", SYSTEM, "draft")
    # Portal, taslağa alınan case'te önceki kararı göstermeye devam eder.
    goster = next(x for x in latest_cases(api, c["requirement_id"]) if x["id"] == c["id"])
    assert goster["karar"] == "approve" and goster["durum"] == "draft"
    assert goster["testci_karari"] == "accept"
    # Yeniden karar verilebilir.
    assert _karar(api, c, karar="reject", ret_nedeni="duplicate").json()["durum"] == "rejected"


def test_onay_sonrasi_duzeltme_onayi_dusurur(api: TestClient, hazir) -> None:
    """Onaylı case düzenlenirse (Taslağa al + edit) yayın yeni son onay olmadan açılmaz."""
    rid, testci, analist = hazir
    c = latest_cases(api, rid)[0]
    onayla(api, c, testci, analist)
    assert _karar(api, c, karar="reopen").status_code == 200
    yeni = {**c["icerik"], "title": c["icerik"]["title"] + " (düzeltildi)"}
    out = _karar(api, c, karar="edit", icerik=yeni).json()
    assert out["durum"] == "ready" and out["onaylanan_hash"] is None
    with session_scope() as s:
        assert not approved_hash_matches(s, s.get(TestCase, uuid.UUID(c["id"])))
    rol_ol(api, analist)
    assert _karar(api, out, karar="approve").json()["durum"] == "approved"


def test_hazir_case_testci_taslaga_alabilir(api: TestClient, hazir) -> None:
    rid, _, _ = hazir
    c = latest_cases(api, rid)[0]
    _karar(api, c, karar="accept")
    r = _karar(api, c, karar="reopen")
    assert r.status_code == 200 and r.json()["durum"] == "draft"


def test_goruntuleme_testci_ve_analist(api: TestClient, make_user, hazir) -> None:
    """`viewed`: Testçi (karar) ve Analist (son onay) kaydeder; diğer roller 403 + denetim."""
    from tp_core.models import CaseGoruntuleme

    rid, testci, analist = hazir
    c = latest_cases(api, rid)[0]
    for rol in ("po", "engineer"):
        rol_ol(api, make_user(rol))
        r = api.post(f"/cases/{c['id']}/viewed")
        assert r.status_code == 403 and r.json()["kod"] == "yetki_yok", (rol, r.text)
    assert {e["rol"] for e in _authz_red("case.decide")} == {"po", "engineer"}
    with session_scope() as s:
        assert s.scalar(select(CaseGoruntuleme.id)) is None

    # Analistin son onay review süresi kaydedilir.
    rol_ol(api, testci)
    hazir_c = _karar(api, c, karar="accept").json()
    rol_ol(api, analist)
    r = api.post(f"/cases/{c['id']}/viewed")
    assert r.status_code == 200 and r.json()["yeni"] is True
    time.sleep(0.05)
    out = _karar(api, hazir_c, karar="approve").json()
    assert out["durum"] == "approved"
    with session_scope() as s:
        rv = s.scalars(
            select(Review).where(Review.nesne_id == uuid.UUID(c["id"]), Review.karar == "approve")
        ).one()
        assert rv.duzeltme_olculeri["review_sure_ms"] >= 40


def test_po_rolu_karar_veremez(api: TestClient, make_user, hazir) -> None:
    rid, _, _ = hazir
    c = latest_cases(api, rid)[0]
    rol_ol(api, make_user("po"))
    for karar in ("accept", "approve"):
        assert _karar(api, c, karar=karar).status_code == 403
    assert _karar(api, c, karar="eski_karar").status_code == 422


def test_okuma_izni_ve_uretim_izni(api: TestClient, make_user, hazir) -> None:
    rid, _, _ = hazir
    for rol in ("po", "engineer", "analyst", "admin"):
        rol_ol(api, make_user(rol))
        assert api.get("/cases", params={"requirement_id": str(rid)}).status_code == 200, rol
        assert api.get(f"/requirements/{rid}/case-metrics").status_code == 200, rol
        assert api.post(f"/requirements/{rid}/generate-cases").status_code == 403, rol


@pytest.mark.skip(reason="S1 birleşince: 'developer' rolü app_user.rol kısıtında yok")
def test_developer_yalniz_onayli_caseleri_gecmissiz_gorur(  # pragma: no cover
    api: TestClient, make_user, hazir
) -> None:
    # TODO(012 S1+S2 birleşimi): S1 rol kısıtına 'developer' ekleyince skip kaldırılır.
    rid, testci, analist = hazir
    a, b, _ = latest_cases(api, rid)
    onayla(api, a, testci, analist)
    _karar(api, b, karar="accept")
    rol_ol(api, make_user("developer"))
    liste = latest_cases(api, rid)
    assert [x["id"] for x in liste] == [a["id"]]
    gorunen = liste[0]
    assert gorunen["kisitli"] is True and gorunen["durum"] == "approved"
    for alan in ("karar", "karar_veren", "testci_karari", "son_onay", "ai_icerik", "fark"):
        assert alan not in gorunen, alan
    assert api.get(f"/cases/{b['id']}").status_code == 404
    assert api.get(f"/cases/{a['id']}").json()["kisitli"] is True
    m = api.get(f"/requirements/{rid}/case-metrics").json()
    assert m == {
        "requirement_id": str(rid),
        "jira_key": m["jira_key"],
        "durumlar": {"approved": 1},
        "kisitli": True,
    }
    assert _karar(api, a, karar="accept").status_code == 403
    assert api.post(f"/cases/{a['id']}/viewed").status_code == 403


def test_developer_kisitli_gorunum_servis_duzeyi(api: TestClient, hazir) -> None:
    """Rol kısıtı olmadan da çalışan servis süzgeci (S1 öncesi): developer Principal'ı."""
    from tp_core.features.cases import service
    from tp_core.workflow.service import Principal

    rid, testci, analist = hazir
    a, b, _ = latest_cases(api, rid)
    onayla(api, a, testci, analist)
    _karar(api, b, karar="accept")
    dev = Principal(uuid.uuid4(), "dev", "developer")
    with session_scope() as s:
        liste = service.list_cases(s, rid, dev)
        assert [x["id"] for x in liste] == [a["id"]]
        assert liste[0]["kisitli"] is True
        assert not {"karar", "testci_karari", "son_onay", "ai_icerik", "fark"} & set(liste[0])
        with pytest.raises(service.CaseNotFound):
            service.get_case_view(s, uuid.UUID(b["id"]), dev)
        assert service.requirement_metrics_kisitli(s, rid)["durumlar"] == {"approved": 1}
        # Diğer okuyucular tam görünümü alır.
        tam = service.list_cases(s, rid, analist)
        assert len(tam) == 3 and "kisitli" not in tam[0]


def test_kabul_orani_ilk_karara_gore_ve_review_tamam(api: TestClient, hazir) -> None:
    rid, testci, analist = hazir
    a, b, c = latest_cases(api, rid)
    assert _karar(api, a, karar="accept").status_code == 200
    rol_ol(api, analist)
    r = api.post(f"/requirements/{rid}/review-complete")
    assert r.status_code == 409 and "Testçi kararı bekleyen 2 case" in r.json()["detail"]

    rol_ol(api, testci)
    buyuk = {
        **b["icerik"],
        "expected_result": "Tamamen farklı bir beklenen sonuç metni",
        "title": "Yeniden yazılmış başlık",
    }
    assert _karar(api, b, karar="edit", icerik=buyuk).status_code == 200
    assert _karar(api, c, karar="reject", ret_nedeni="out_of_scope").status_code == 200
    # Reddedileni taslağa alıp kabul etmek ilk karara dayalı oranı değiştirmez.
    c2 = latest_cases(api, rid)[2]
    assert _karar(api, c2, karar="reopen").status_code == 200
    assert _karar(api, latest_cases(api, rid)[2], karar="accept").status_code == 200

    # Testçi kararları bitti, son onay bekleniyor: review tamamlanamaz.
    rol_ol(api, analist)
    r = api.post(f"/requirements/{rid}/review-complete")
    assert r.status_code == 409 and "Son onay bekleyen 3 case" in r.json()["detail"]
    for x in latest_cases(api, rid):
        assert _karar(api, x, karar="approve").status_code == 200

    m = api.get(f"/requirements/{rid}/case-metrics").json()
    assert m["uretilen"] == 3 and m["karar_verilen"] == 3 and m["bekleyen"] == 0
    assert m["ilk_kararlar"] == {"accept": 1, "edit": 1, "reject": 1}
    assert m["kabul"] == 1 and m["kabul_orani"] == pytest.approx(1 / 3, abs=1e-4)
    assert m["ret_nedenleri"] == {"out_of_scope": 1}
    assert m["kabul_hedefi"] == 0.7 and m["ai_cagri_modlari"] == {"live": 1}
    assert m["durumlar"] == {"approved": 3}
    assert m["son_onay"] == {
        "bekleyen": 0,
        "onaylanan": 3,
        "geri_gonderilen": 0,
        "geri_gonderilen_case": 0,
        "geri_gonderme_orani": 0.0,
    }

    r = api.post(f"/requirements/{rid}/review-complete")
    assert r.status_code == 200, r.text
    assert r.json()["olcum"]["kabul"] == 1
    with session_scope() as s:
        ev = s.scalars(
            select(AuditEvent).where(AuditEvent.eylem == "requirement.review_complete")
        ).one()
        assert ev.ozet["uretilen"] == 3 and ev.ozet["son_onay"]["onaylanan"] == 3


def test_eski_akis_kayitlari_olcumde_testci_karari_sayilir(api: TestClient, hazir) -> None:
    """012 öncesi: analistin doğrudan `approve`'u (önünde kabul yok) Testçi kabulü sayılır."""
    from tp_core.features.cases.service import son_onay_kararlari, testci_kararlari

    class R:
        def __init__(self, karar: str) -> None:
            self.karar, self.id = karar, uuid.uuid4()

    eski = [R("approve")]
    assert [r.karar for r in testci_kararlari(eski)] == ["approve"]
    assert son_onay_kararlari(eski) == []
    yeni = [R("accept"), R("send_back"), R("edit"), R("approve")]
    assert [r.karar for r in testci_kararlari(yeni)] == ["accept", "edit"]
    assert [r.karar for r in son_onay_kararlari(yeni)] == ["send_back", "approve"]
    # Eski ret sonrası taslağa al + eski approve: ikisi de Testçi kararı sayılır.
    karma = [R("reject"), R("reopen"), R("approve")]
    assert [r.karar for r in testci_kararlari(karma)] == ["reject", "approve"]
