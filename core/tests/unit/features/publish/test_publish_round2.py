"""Review 2. tur: yayında eşzamanlı PO etiketi denetimi ve yarım kalan zincir sabitlemesi."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from tests.unit.features.publish.test_publish import _ctx, _label_count
from tests.unit.features.publish.test_publish import hazir as hazir_fikstur
from tp_core.features.publish import service as publish
from tp_core.integrations.jira import RestJira
from tp_core.models import AuditEvent, Requirement, TestCase, session_scope

hazir = hazir_fikstur  # aynı fikstür (iki case'li TPD-4; ilki onaylı)


def _jira_etiketli(rid: uuid.UUID) -> None:
    with session_scope() as s:
        s.get(Requirement, rid).po_onay_kaynagi = "jira_label"


def _anchored() -> list[AuditEvent]:
    with session_scope() as s:
        return list(
            s.scalars(
                select(AuditEvent)
                .where(AuditEvent.eylem == "publish.anchored")
                .order_by(AuditEvent.id)
            )
        )


# ------------------------------------------- PO etiketi Jira'dan kalktı (poll öncesi pencere)


def test_po_etiketi_kalkinca_yayin_jiraya_yazmaz(
    engine: Engine, jira: RestJira, targets, hazir, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.features.requirements import flow

    rid, _, a, _ = hazir
    _jira_etiketli(rid)
    cagri: list[str] = []

    def etiket(req):
        cagri.append(req.jira_key)
        return False  # PO tp-po-approved'ı kaldırdı; poll henüz withdraw_po yapmadı

    monkeypatch.setattr(flow, "po_label_current", etiket)
    sonuc = publish.run_publish(_ctx([a["id"]]), engine)
    (kalem,) = sonuc["sonuclar"]
    assert kalem["durum"] == "failed" and "tp-po-approved" in kalem["hata"]
    assert cagri == ["TPD-4"]  # gereksinim başına bir kez
    assert _label_count(jira, a["id"]) == 0
    with session_scope() as s:
        assert s.get(TestCase, uuid.UUID(a["id"])).durum == "approved"


def test_po_etiketi_okunamazsa_fail_closed(
    engine: Engine, jira: RestJira, targets, hazir, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.features.requirements import flow

    rid, _, a, _ = hazir
    _jira_etiketli(rid)

    def bozuk(_req):
        raise ConnectionError("jira yok")

    monkeypatch.setattr(flow, "po_label_current", bozuk)
    (kalem,) = publish.run_publish(_ctx([a["id"]]), engine)["sonuclar"]
    assert kalem["durum"] == "failed" and "doğrulanamadı" in kalem["hata"]
    assert _label_count(jira, a["id"]) == 0


def test_po_etiketi_duruyorsa_yayin_ve_portal_onayinda_jiraya_bakilmaz(
    engine: Engine, jira: RestJira, targets, hazir, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tp_core.features.requirements import flow

    _, _, a, _ = hazir
    cagri: list[str] = []
    monkeypatch.setattr(flow, "po_label_current", lambda req: cagri.append(req.jira_key) or True)
    # Portal (serbest metin yolu) onayında Jira'ya bakılmaz.
    (kalem,) = publish.run_publish(_ctx([a["id"]]), engine)["sonuclar"]
    assert kalem["durum"] == "created" and cagri == []


# ------------------------------------------- yayın sonrası, sabitleme öncesi çöküş (§3/8)


def test_yayin_sonrasi_cokmede_yeniden_denemede_sabitlenir(
    engine: Engine, jira: RestJira, targets, hazir
) -> None:
    _, _, a, _ = hazir
    cid = uuid.UUID(a["id"])
    # İlk deneme case'i yayınladı (published commit edildi) ve _pin_chain'den önce çöktü.
    ilk = publish._publish_one(targets, cid, "analist")
    assert ilk["durum"] == "created"
    assert _anchored() == []

    sonuc = publish.run_publish(_ctx([a["id"]]), engine)
    assert sonuc["sonuclar"][0]["durum"] == "exists"
    (ev,) = _anchored()
    assert ev.ozet["case_ids"] == [a["id"]] and ev.ozet["kurtarma"] is True
    assert ev.ozet["external_keys"] == [ilk["external_key"]]
    yorumlar = [c for c in jira.get_comments("TPD-4") if c.body.startswith("Testing Probe:")]
    assert len(yorumlar) == 1 and ilk["external_key"] in yorumlar[0].body

    # Üçüncü deneme: zaten sabitlenmiş → yeni yorum ve kayıt yok.
    publish.run_publish(_ctx([a["id"]]), engine)
    assert len(_anchored()) == 1
    assert len([c for c in jira.get_comments("TPD-4") if c.body.startswith("Testing Probe:")]) == 1


def test_yorumdan_sonra_cokmede_yorum_tekrarlanmaz_kayit_tamamlanir(
    engine: Engine, jira: RestJira, targets, hazir
) -> None:
    _, _, a, _ = hazir
    ilk = publish._publish_one(targets, uuid.UUID(a["id"]), "analist")
    # Story yorumu yazıldı, publish.anchored kaydı yazılmadan çöküldü.
    govde = f"Testing Probe: 1 test case yayınlandı ({ilk['external_key']})."
    yorum_id = jira.add_comment("TPD-4", govde)
    publish.run_publish(_ctx([a["id"]]), engine)
    (ev,) = _anchored()
    assert ev.ozet["comment_id"] == yorum_id and ev.ozet["kurtarma"] is True
    assert len([c for c in jira.get_comments("TPD-4") if c.body.startswith("Testing Probe:")]) == 1


def test_normal_yayin_sabitleme_kaydi_case_kimliklerini_tasir(
    api: TestClient, engine: Engine, jira: RestJira, targets, hazir
) -> None:
    _, _, a, _ = hazir
    assert publish.run_publish(_ctx([a["id"]]), engine)["sonuclar"][0]["durum"] == "created"
    (ev,) = _anchored()
    assert ev.ozet["case_ids"] == [a["id"]] and ev.ozet["kurtarma"] is False
    assert ev.ozet["zincir_hash"]
    # Aynı case'i yeniden yayınlamak (exists) yeniden sabitlemez.
    publish.run_publish(_ctx([a["id"]]), engine)
    assert len(_anchored()) == 1
