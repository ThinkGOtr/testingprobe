"""Durum makinesi servisi: geçişler, insan kapıları, içerik hash'i, yazma koruması, olaylar."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from tp_core.audit import content_hash, verify_chain
from tp_core.events.bus import CHANNEL, parse_payload
from tp_core.models import (
    BugDraft,
    ConsistencyFinding,
    Requirement,
    Review,
    Script,
    StateWriteForbidden,
    TestCase,
    WorkflowInstance,
    case_id,
)
from tp_core.workflow.service import (
    SYSTEM,
    ApprovalNotAllowed,
    ConcurrentTransition,
    GateClosed,
    GuardFailed,
    InvalidDecision,
    InvalidTransition,
    Principal,
    approved_hash_matches,
    content_hash_of,
    transition,
)
from tp_core.workflow.service import record_approval as _record_approval

from .conftest import Db

MakeUser = Callable[..., Principal]


def record_approval(session: Session, entity: object, user: object, karar: str, **kw: object):
    """Portal kararı gibi: insanın gördüğü içerik = güncel içerik (`beklenen_hash`)."""
    kw.setdefault("beklenen_hash", content_hash_of(entity))
    return _record_approval(session, entity, user, karar, **kw)  # type: ignore[arg-type]


CASE = {
    "title": "Kampanyalı sepet",
    "type": "positive",
    "risk": "high",
    "acceptance_criteria_refs": ["AC2"],
    "preconditions": ["bayi1 giriş yapmış"],
    "steps": [{"id": "S1", "action": "7 adet ekle", "data": "P-001", "expected": "1 bedava"}],
    "expected_result": "1 adet bedava",
    "tags": ["AI-generated"],
}


def _req(session: Session, **kw: object) -> Requirement:
    alanlar: dict[str, object] = {
        "kaynak": "jira",
        "jira_key": f"TPD-{uuid.uuid4().hex[:6]}",
        "baslik": "Kampanyalı sepet",
        "aciklama": "Bayi ...",
        "kabul_kriterleri": ["AC1: ...", "AC2: ..."],
        "kaynak_hash": "h",
    }
    r = Requirement(**(alanlar | kw))
    session.add(r)
    session.flush()
    return r


def _case(session: Session, req: Requirement | None = None, sira_no: int = 1) -> TestCase:
    req = req or _req(session)
    c = TestCase(
        id=case_id(req, sira_no, 1),
        requirement_id=req.id,
        sira_no=sira_no,
        icerik=dict(CASE),
        icerik_hash=content_hash(CASE),
    )
    session.add(c)
    session.flush()
    return c


# ------------------------------------------------------------------ test_case


def _hazir(session: Session, c: TestCase, testci: Principal) -> None:
    """Testçi kabulü: draft → ready (`accept`)."""
    record_approval(session, c, testci, "accept")
    transition(session, c, "ready", testci, "draft")


def _onayla(session: Session, c: TestCase, testci: Principal, analist: Principal) -> None:
    """012 akışı: Testçi kabulü (draft → ready) + Analist son onayı (ready → approved)."""
    _hazir(session, c, testci)
    record_approval(session, c, analist, "approve")
    transition(session, c, "approved", analist, "ready")


def test_case_onay_ve_yayin_mutlu_yol(session: Session, make_user: MakeUser) -> None:
    testci, analist = make_user("tester"), make_user("analyst")
    c = _case(session)
    assert c.durum == "draft"
    assert content_hash_of(c) == c.icerik_hash
    rv = record_approval(session, c, testci, "accept")
    assert rv.onaylanan_hash == c.icerik_hash and rv.user_id == testci.id
    transition(session, c, "ready", testci, "draft")
    assert (c.durum, c.onaylanan_hash) == ("ready", None)
    assert not approved_hash_matches(session, c)  # Testçi kabulü yayını açmaz
    rv = record_approval(session, c, analist, "approve")
    assert rv.user_id == analist.id
    transition(session, c, "approved", analist, "ready")
    assert (c.durum, c.onaylanan_hash) == ("approved", c.icerik_hash)
    assert approved_hash_matches(session, c)
    transition(session, c, "published", SYSTEM, "approved")
    assert c.durum == "published"
    session.commit()
    conn = session.connection()
    eylemler = conn.execute(
        text("SELECT eylem FROM audit_event WHERE nesne = :n ORDER BY id"),
        {"n": f"test_case:{c.id}"},
    ).scalars()
    assert list(eylemler) == [
        "review.accept",
        "test_case.transition",
        "review.approve",
        "test_case.transition",
        "test_case.transition",
    ]
    assert verify_chain(conn).ok


def test_onaysiz_kapi_kapali(session: Session, make_user: MakeUser) -> None:
    c = _case(session)
    with pytest.raises(GateClosed):
        transition(session, c, "ready", make_user("tester"), "draft")
    assert c.durum == "draft"
    # Taslaktan doğrudan onaya geçiş yoktur (son onay Testçi kabulünden sonra).
    with pytest.raises(InvalidTransition):
        transition(session, c, "approved", make_user("analyst"), "draft")
    _hazir(session, c, make_user("tester"))
    with pytest.raises(GateClosed):
        transition(session, c, "approved", make_user("analyst"), "ready")
    assert c.durum == "ready"


def test_testci_kabulu_yayin_kapisini_acmaz(session: Session, make_user: MakeUser) -> None:
    """012: yayın kapısı yalnız Analistin `approve` kararını sayar (`edit` artık saymaz)."""
    c = _case(session)
    testci = make_user("tester")
    record_approval(session, c, testci, "edit", degisiklik={"icerik": {**CASE, "risk": "low"}})
    transition(session, c, "ready", testci, "draft")
    assert not approved_hash_matches(session, c)
    assert approved_hash_matches(session, c, frozenset({"accept", "edit"}))


def test_karar_rolleri_karara_gore(session: Session, make_user: MakeUser) -> None:
    """Testçi son onay veremez, Analist Testçi kararı veremez (derinlemesine savunma)."""
    c = _case(session)
    testci, analist = make_user("tester"), make_user("analyst")
    for karar in ("approve", "send_back"):
        with pytest.raises(ApprovalNotAllowed, match="rolü"):
            record_approval(session, c, testci, karar, gerekce="x")
    for karar, kw in (
        ("accept", {}),
        ("reject", {"ret_nedeni": "duplicate"}),
        ("reopen", {}),
        ("edit", {"degisiklik": {"icerik": {**CASE, "risk": "low"}}}),
    ):
        with pytest.raises(ApprovalNotAllowed, match="rolü"):
            record_approval(session, c, analist, karar, **kw)
    for rol in ("po", "engineer", "presenter"):
        with pytest.raises(ApprovalNotAllowed):
            record_approval(session, c, make_user(rol), "accept")
    assert _review_sayisi(session) == 0


def test_geri_gonderme_gerekce_ister_ve_taslaga_doner(
    session: Session, make_user: MakeUser
) -> None:
    c = _case(session)
    testci, analist = make_user("tester"), make_user("analyst")
    _hazir(session, c, testci)
    for bos in (None, "  "):
        with pytest.raises(InvalidDecision, match="gerekçe"):
            record_approval(session, c, analist, "send_back", gerekce=bos)
    rv = record_approval(session, c, analist, "send_back", gerekce="AC2 adımı eksik")
    assert rv.gerekce == "AC2 adımı eksik"
    with pytest.raises(GateClosed):  # son karar onaylamayan send_back
        transition(session, c, "approved", analist, "ready")
    transition(session, c, "draft", analist, "ready")
    assert (c.durum, c.onaylanan_hash) == ("draft", None)


def test_onaydan_sonra_icerik_degisirse_yayin_reddedilir(
    session: Session, make_user: MakeUser
) -> None:
    c = _case(session)
    _onayla(session, c, make_user("tester"), make_user("analyst"))
    c.icerik = {**CASE, "expected_result": "2 adet bedava"}  # onaydan sonra değişti
    assert not approved_hash_matches(session, c)
    with pytest.raises(GateClosed):
        transition(session, c, "published", SYSTEM, "approved")


def test_duzeltip_onay_yeni_hash(session: Session, make_user: MakeUser) -> None:
    """Portal 'edit': insan düzenlemeden ÖNCEKİ içeriği gördü (görülen hash), düzenlenmiş içerik
    kabul edilir. Router içeriği kendisi değiştirmez; `degisiklik` ile verir."""
    testci, analist = make_user("tester"), make_user("analyst")
    c = _case(session)
    gorulen = content_hash_of(c)  # ekrandaki (düzenleme öncesi) içerik
    yeni = {**CASE, "title": "Kampanyalı sepet (düzeltildi)"}
    rv = _record_approval(
        session, c, testci, "edit", beklenen_hash=gorulen, degisiklik={"icerik": yeni}
    )
    assert rv.onaylanan_hash == content_hash(yeni) != gorulen
    assert (c.icerik, c.icerik_hash) == (yeni, content_hash(yeni))
    assert rv.once == {"icerik": CASE} and rv.sonra == {"icerik": yeni}
    transition(session, c, "ready", testci, "draft")
    record_approval(session, c, analist, "approve")
    transition(session, c, "approved", analist, "ready")
    assert c.onaylanan_hash == content_hash(yeni)
    transition(session, c, "published", SYSTEM, "approved")
    session.commit()
    ozet = (
        session.connection()
        .execute(text("SELECT ozet FROM audit_event WHERE eylem = 'review.edit'"))
        .scalar_one()
    )
    assert (ozet["gorulen_hash"], ozet["hash"]) == (gorulen, content_hash(yeni))
    assert ozet["degisen_alanlar"] == ["icerik"]


def test_duzenleme_sonrasi_gorulen_hash_ile_karar_409_degil(
    session: Session, make_user: MakeUser
) -> None:
    """Regresyon: eskiden router düzenlemeyi önce uygulayınca görülen hash hiç eşleşmezdi (her
    zaman 409), sonra uygulayınca kapı açılmazdı. Artık iki sıra da tek çağrıdadır."""
    testci = make_user("tester")
    c = _case(session)
    gorulen = content_hash_of(c)
    yeni = {**CASE, "risk": "low"}
    _record_approval(session, c, testci, "edit", beklenen_hash=gorulen, degisiklik={"icerik": yeni})
    transition(session, c, "ready", testci, "draft")  # GateClosed fırlatmaz
    assert approved_hash_matches(session, c, frozenset({"edit"}))


def test_edit_karari_degisiklik_kurallari(session: Session, make_user: MakeUser) -> None:
    testci = make_user("tester")
    c = _case(session)
    h = content_hash_of(c)
    with pytest.raises(InvalidDecision, match="düzenlenmiş içerikle"):
        _record_approval(session, c, testci, "edit", beklenen_hash=h)
    with pytest.raises(InvalidDecision, match="değiştiremez"):
        _record_approval(session, c, testci, "accept", beklenen_hash=h, degisiklik={"icerik": {}})
    with pytest.raises(InvalidDecision, match="değiştiremez"):
        _record_approval(
            session, c, testci, "edit", beklenen_hash=h, degisiklik={"durum": "approved"}
        )
    # Görülen hash eski ise düzenleme de uygulanmaz.
    with pytest.raises(GateClosed):
        _record_approval(
            session, c, testci, "edit", beklenen_hash="0" * 64, degisiklik={"icerik": {}}
        )
    assert c.icerik == CASE
    assert _review_sayisi(session) == 0


def test_son_karar_gecerlidir(session: Session, make_user: MakeUser) -> None:
    testci = make_user("tester")
    c = _case(session)
    record_approval(session, c, testci, "accept")
    record_approval(session, c, testci, "reject", ret_nedeni="duplicate")
    with pytest.raises(GateClosed):
        transition(session, c, "ready", testci, "draft")
    transition(session, c, "rejected", testci, "draft")
    assert c.durum == "rejected"


def test_onaydan_taslaga_donus_onay_hashini_temizler(session: Session, make_user: MakeUser) -> None:
    testci = make_user("tester")
    c = _case(session)
    _onayla(session, c, testci, make_user("analyst"))
    assert c.onaylanan_hash == c.icerik_hash
    transition(session, c, "draft", testci, "approved")
    assert c.onaylanan_hash is None


@pytest.mark.parametrize(
    ("karar", "kw", "hata"),
    [
        ("reject", {}, InvalidDecision),
        ("reject", {"ret_nedeni": "uydurma"}, InvalidDecision),
        ("accept", {"ret_nedeni": "duplicate"}, InvalidDecision),
        ("approve", {}, ApprovalNotAllowed),
        ("merge", {}, InvalidDecision),
    ],
)
def test_gecersiz_kararlar(
    session: Session, make_user: MakeUser, karar: str, kw: dict, hata: type
) -> None:
    with pytest.raises(hata):
        record_approval(session, _case(session), make_user("tester"), karar, **kw)


def test_rol_ide_ve_sistem_onay_veremez(session: Session, make_user: MakeUser) -> None:
    c = _case(session)
    with pytest.raises(ApprovalNotAllowed, match="rolü"):
        record_approval(session, c, make_user("engineer"), "approve")
    analist = make_user("analyst")
    ide = Principal(analist.id, analist.kullanici_adi, "analyst", kanal="ide", kapsam="submit")
    with pytest.raises(ApprovalNotAllowed):
        record_approval(session, c, ide, "approve")
    with pytest.raises(ApprovalNotAllowed):
        record_approval(session, c, SYSTEM, "approve")
    with pytest.raises(ApprovalNotAllowed):
        record_approval(session, c, None, "approve", kanal="jira", harici_onaylayan="po@sim")


def test_gecersiz_ve_eszamanli_gecis(session: Session) -> None:
    c = _case(session)
    with pytest.raises(InvalidTransition):
        transition(session, c, "published", SYSTEM, "draft")
    with pytest.raises(ConcurrentTransition):
        transition(session, c, "superseded", SYSTEM, "approved")
    transition(session, c, "superseded", SYSTEM, "draft")
    with pytest.raises(InvalidTransition):
        transition(session, c, "draft", SYSTEM, "superseded")


def test_iki_oturum_ayni_gecisi_yaparsa_biri_kaybeder(engine: Engine) -> None:
    with Session(engine) as s:
        cid = _case(s).id
        s.commit()
    sonuclar: list[str] = []
    bariyer = threading.Barrier(2)

    def dene() -> None:
        with Session(engine) as s:
            c = s.get(TestCase, cid)
            bariyer.wait()
            try:
                transition(s, c, "superseded", SYSTEM, "draft")
                s.commit()
                sonuclar.append("ok")
            except ConcurrentTransition:
                s.rollback()
                sonuclar.append("cakisma")

    iplikler = [threading.Thread(target=dene) for _ in range(2)]
    for t in iplikler:
        t.start()
    for t in iplikler:
        t.join()
    assert sorted(sonuclar) == ["cakisma", "ok"]


# --------------------------------------------------------------- yazma koruması


def test_durum_dogrudan_yazilamaz(session: Session) -> None:
    c = _case(session)
    c.durum = "approved"
    with pytest.raises(StateWriteForbidden):
        session.flush()
    session.rollback()


def test_onaylanan_hash_dogrudan_yazilamaz(session: Session) -> None:
    c = _case(session)
    c.onaylanan_hash = c.icerik_hash
    with pytest.raises(StateWriteForbidden):
        session.flush()
    session.rollback()


def test_yeni_satir_baslangic_durumunda_olmali(session: Session) -> None:
    req = _req(session)
    session.add(TestCase(id=case_id(req, 1, 1), requirement_id=req.id, sira_no=1, icerik={},
                         icerik_hash="x", durum="approved"))  # fmt: skip
    with pytest.raises(StateWriteForbidden):
        session.flush()
    session.rollback()


# ---------------------------------------------------------------- requirement


def test_requirement_po_kapisi_jira_etiketiyle(session: Session) -> None:
    r = _req(session)
    for hedef, once in [
        ("in_review", "new"),
        ("doc_final", "in_review"),
        ("pending_po", "doc_final"),
    ]:
        transition(session, r, hedef, SYSTEM, once)
    with pytest.raises(GateClosed):
        transition(session, r, "po_approved", SYSTEM, "pending_po")
    rv = record_approval(
        session, r, None, "po_approve", kanal="jira", harici_onaylayan="po@sim.local",
        onay_zamani=_simdi(),
    )  # fmt: skip
    assert rv.user_id is None and rv.harici_onaylayan == "po@sim.local"
    transition(session, r, "po_approved", SYSTEM, "pending_po")
    transition(session, r, "generating", SYSTEM, "po_approved")


def test_requirement_po_onayindan_sonra_ac_degisirse_kapi_kapanir(
    session: Session, make_user: MakeUser
) -> None:
    r = _req(session, kaynak="free_text", jira_key=None)
    for hedef, once in [("in_review", "new"), ("doc_final", "in_review"),
                        ("pending_po", "doc_final")]:  # fmt: skip
        transition(session, r, hedef, SYSTEM, once)
    record_approval(session, r, make_user("po"), "po_approve")
    r.kabul_kriterleri = [*r.kabul_kriterleri, "AC3: yeni"]
    with pytest.raises(GateClosed):
        transition(session, r, "po_approved", SYSTEM, "pending_po")


def test_ac_eksik_gereksinim_uretime_gitmez(session: Session, make_user: MakeUser) -> None:
    r = _req(session, ac_missing=True, kabul_kriterleri=[])
    for hedef, once in [("in_review", "new"), ("doc_final", "in_review"),
                        ("pending_po", "doc_final")]:  # fmt: skip
        transition(session, r, hedef, SYSTEM, once)
    record_approval(session, r, make_user("po"), "po_approve")
    transition(session, r, "po_approved", SYSTEM, "pending_po")
    with pytest.raises(GuardFailed):
        transition(session, r, "generating", SYSTEM, "po_approved")


def _pending_po(session: Session) -> Requirement:
    r = _req(session)
    for hedef, once in [("in_review", "new"), ("doc_final", "in_review"),
                        ("pending_po", "doc_final")]:  # fmt: skip
        transition(session, r, hedef, SYSTEM, once)
    return r


def _simdi() -> datetime:
    return datetime.now(UTC)


def _review_sayisi(session: Session) -> int:
    session.flush()
    return len(session.scalars(select(Review)).all())


@pytest.mark.parametrize(
    "bot", ["writer@sim.local", "Reader@Sim.Local", " writer@sim.local ", "bot@firma.com", "abc123"]
)
def test_jira_po_onayi_bot_hesabindan_kabul_edilmez(
    session: Session, monkeypatch: pytest.MonkeyPatch, bot: str
) -> None:
    from tp_core.config import get_settings

    monkeypatch.setenv("JIRA_WRITE_EMAIL", "bot@firma.com")
    monkeypatch.setenv("TP_JIRA_BOT_ACCOUNT_IDS", "abc123, def456")
    get_settings.cache_clear()
    r = _pending_po(session)
    with pytest.raises(ApprovalNotAllowed, match="insan onayı değil"):
        _record_approval(
            session, r, None, "po_approve", kanal="jira", harici_onaylayan=bot,
            onay_zamani=_simdi(),
        )  # fmt: skip
    assert _review_sayisi(session) == 0
    with pytest.raises(GateClosed):
        transition(session, r, "po_approved", SYSTEM, "pending_po")


def test_jira_po_onayi_izin_listesi(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    from tp_core.config import get_settings

    monkeypatch.setenv("TP_PO_JIRA_USERS", "po@firma.com,acc-po-1")
    get_settings.cache_clear()
    r = _pending_po(session)
    for kim in ("", "   ", None, "baskasi@firma.com"):
        with pytest.raises(ApprovalNotAllowed):
            _record_approval(
                session, r, None, "po_approve", kanal="jira", harici_onaylayan=kim,
                onay_zamani=_simdi(),
            )  # fmt: skip
    rv = _record_approval(
        session, r, None, "po_approve", kanal="jira", harici_onaylayan=" PO@firma.com ",
        onay_zamani=_simdi(),
    )  # fmt: skip
    assert rv.harici_onaylayan == "PO@firma.com"
    transition(session, r, "po_approved", SYSTEM, "pending_po")


def test_jira_kanali_yalnizca_gereksinim(session: Session) -> None:
    with pytest.raises(ApprovalNotAllowed):
        _record_approval(
            session, _case(session), None, "approve", kanal="jira", harici_onaylayan="po@x"
        )


def test_portal_karari_gorulen_hashi_tasimali(session: Session, make_user: MakeUser) -> None:
    c = _case(session)
    analist = make_user("analyst")
    with pytest.raises(InvalidDecision, match="icerik_hash"):
        _record_approval(session, c, analist, "approve")
    assert _review_sayisi(session) == 0


def test_icerik_ekran_ile_tiklama_arasinda_degisirse_onay_reddedilir(
    session: Session, make_user: MakeUser
) -> None:
    """TOCTOU: insan A içeriğini gördü; tıklamadan önce içerik B oldu → onay B'ye yazılmaz."""
    c = _case(session)
    analist = make_user("analyst")
    gorulen = content_hash_of(c)
    c.icerik = {**CASE, "title": "Yeniden üretildi"}
    session.flush()
    with pytest.raises(GateClosed, match="değişmiş") as hata:
        _record_approval(session, c, analist, "approve", beklenen_hash=gorulen)
    assert hata.value.status_code == 409
    assert _review_sayisi(session) == 0
    assert not approved_hash_matches(session, c)
    rv = _record_approval(session, c, analist, "approve", beklenen_hash=content_hash_of(c))
    assert rv.onaylanan_hash == content_hash_of(c)


# ------------------------------------------------------- bulgu, bug, script, akış


def test_bulgu_kanit_ve_gerekce_kurallari(session: Session, make_user: MakeUser) -> None:
    analist = make_user("analyst")
    f = ConsistencyFinding(
        requirement_id=_req(session).id,
        tur="doc_vs_data",
        doc_ref="AC3",
        kanitlar=[{"kind": "data", "query": "SELECT ...", "result_digest": "750.00"}],
        severity="blocking",
        onerilen_metin="Minimum sipariş tutarı 750,00 TL'dir.",
    )
    session.add(f)
    session.flush()
    with pytest.raises(GuardFailed):
        transition(session, f, "open", SYSTEM, "unverified")
    f.kanit_dogrulandi = True
    transition(session, f, "open", SYSTEM, "unverified")
    with pytest.raises(GuardFailed, match="gerekçe"):  # karar yok
        transition(session, f, "decided", analist, "open")
    gorulen = content_hash_of(f)  # analistin ekranda gördüğü bulgu (karar öncesi)
    with pytest.raises(InvalidDecision, match="gerekçe"):
        record_approval(session, f, analist, "accept_difference")
    rv = _record_approval(
        session, f, analist, "accept_difference", gerekce="Ayar bilinçli olarak 750",
        beklenen_hash=gorulen,
    )  # fmt: skip
    assert (f.analist_karari, f.gerekce, f.karar_veren_id) == (
        "accept_difference", "Ayar bilinçli olarak 750", analist.id
    )  # fmt: skip
    assert rv.onaylanan_hash == content_hash_of(f) != gorulen
    transition(session, f, "decided", analist, "open")  # görülen hash ile verilen karar kapıyı açar


def test_bulgu_fix_doc_onerilen_metin_duzenlenebilir(session: Session, make_user: MakeUser) -> None:
    analist = make_user("analyst")
    f = ConsistencyFinding(
        requirement_id=_req(session).id, tur="doc_vs_data", doc_ref="AC3",
        kanitlar=[{"kind": "data"}], kanit_dogrulandi=True, severity="blocking",
        onerilen_metin="Minimum 750 TL",
    )  # fmt: skip
    session.add(f)
    session.flush()
    transition(session, f, "open", SYSTEM, "unverified")
    gorulen = content_hash_of(f)
    _record_approval(
        session, f, analist, "fix_doc", beklenen_hash=gorulen,
        degisiklik={"onerilen_metin": "Minimum sipariş tutarı 750,00 TL'dir."},
    )  # fmt: skip
    transition(session, f, "decided", analist, "open")
    assert f.onerilen_metin == "Minimum sipariş tutarı 750,00 TL'dir."
    # Karardan sonra metin değişirse "kararı verilmiş içerik" artık bu değildir.
    f.onerilen_metin = "Başka metin"
    assert not approved_hash_matches(session, f)


def test_bug_taslagi_testci_onayi(session: Session, make_user: MakeUser) -> None:
    b = BugDraft(icerik={"summary": "Kampanya indirimi uygulanmadı"}, icerik_hash="x")
    session.add(b)
    session.flush()
    with pytest.raises(ApprovalNotAllowed):
        record_approval(session, b, make_user("analyst"), "new")
    testci = make_user("tester")
    record_approval(session, b, testci, "new")
    transition(session, b, "approved", testci, "draft")
    transition(session, b, "published", SYSTEM, "approved")


def test_script_merge_head_sha_degisirse_reddedilir(session: Session, make_user: MakeUser) -> None:
    s = Script(dosya_yolu="tests/tp/case.spec.ts", icerik="test(...)", head_sha="aaa")
    session.add(s)
    session.flush()
    for hedef, once in [("verifying", "pending"), ("checking", "verifying"),
                        ("pr_open", "checking")]:  # fmt: skip
        transition(session, s, hedef, SYSTEM, once)
    record_approval(session, s, make_user("engineer"), "merge")
    s.head_sha = "bbb"  # onaydan sonra PR'a yeni commit
    with pytest.raises(GateClosed):
        transition(session, s, "merged", SYSTEM, "pr_open")


def test_workflow_instance_gecisleri(session: Session) -> None:
    wf = WorkflowInstance(tur="RequirementToCases", baslatan="analist")
    session.add(wf)
    session.flush()
    assert wf.durum == "running"
    transition(session, wf, "paused", SYSTEM, "running", sebep="bütçe")
    transition(session, wf, "running", SYSTEM, "paused")
    with pytest.raises(TypeError):
        content_hash_of(wf)


def test_review_kaydi_sira_ile_sirali(session: Session, make_user: MakeUser) -> None:
    analist = make_user("analyst")
    c = _case(session)
    for _ in range(3):
        record_approval(session, c, analist, "approve")
    siralar = session.scalars(select(Review.sira).where(Review.nesne_id == c.id)).all()
    assert len(set(siralar)) == 3


# --------------------------------------------------------------------- olaylar


def _dinle(db: Db) -> psycopg.Connection:
    c = psycopg.connect(db.app_url.replace("+psycopg", ""), autocommit=True)
    c.execute(f"LISTEN {CHANNEL}")
    return c


def _olaylar(c: psycopg.Connection) -> list[dict]:
    return [parse_payload(n.payload) for n in c.notifies(timeout=0.5, stop_after=10)]


def test_olay_yalnizca_commitle_yayilir(db: Db, engine: Engine) -> None:
    with _dinle(db) as dinleyici:
        with Session(engine) as s:
            c = _case(s)
            transition(s, c, "superseded", SYSTEM, "draft")
            s.rollback()
        assert _olaylar(dinleyici) == []
        with Session(engine) as s:
            c = _case(s)
            cid = c.id
            transition(s, c, "superseded", SYSTEM, "draft")
            s.commit()
        olaylar = _olaylar(dinleyici)
    assert [o["event"] for o in olaylar] == ["test_case.state"]
    assert olaylar[0]["data"] == {
        "id": str(cid), "from": "draft", "durum": "superseded", "aktor": "system"
    }  # fmt: skip


# ------------------------------------------------------ kilit sırası (deadlock yok)


def test_onay_ve_gecis_eszamanli_kilitlenmez(engine: Engine, make_user: MakeUser) -> None:
    """A satırı kilitler; B onay yazıp aynı satırı ister; sonra A geçiş yapar. Denetim kilidi
    işlem ortasında alınsaydı B denetim kilidini tutarak A'yı, A da denetim kilidi için B'yi
    beklerdi (deadlock). Denetim kaydı commit anında yazıldığı için kilit hep en son alınır."""
    import psycopg.errors

    analist = make_user("analyst")
    with Session(engine) as s:
        x, y = _case(s), _case(s)
        xid, yid = x.id, y.id
        s.commit()
    a_kilitledi = threading.Event()
    sonuc: dict[str, str] = {}

    def a() -> None:
        with Session(engine) as s:
            # Özellik kodu satırı kilitleyip işler (ör. içerik günceller), sonra geçiş yapar.
            x_a = s.get(TestCase, xid, with_for_update=True)
            a_kilitledi.set()
            time.sleep(0.5)  # B onayını yazsın ve X'i beklemeye başlasın
            transition(s, x_a, "superseded", SYSTEM, "draft")
            time.sleep(1.2)  # deadlock_timeout (1 sn) aşılsın
            s.commit()
            sonuc["a"] = "ok"

    def b() -> None:
        a_kilitledi.wait(5)
        with Session(engine) as s:
            try:
                record_approval(s, s.get(TestCase, yid), analist, "approve")
                transition(s, s.get(TestCase, xid), "superseded", SYSTEM, "draft")
                s.commit()
                sonuc["b"] = "ok"
            except ConcurrentTransition:
                s.rollback()
                sonuc["b"] = "cakisma"
            except psycopg.errors.DeadlockDetected:
                sonuc["b"] = "deadlock"
            except Exception as exc:  # sqlalchemy sarmalayıcısı
                sonuc["b"] = "deadlock" if "deadlock" in str(exc) else repr(exc)

    iplikler = [threading.Thread(target=a), threading.Thread(target=b)]
    for t in iplikler:
        t.start()
    for t in iplikler:
        t.join(15)
    assert sonuc == {"a": "ok", "b": "cakisma"}


def test_geri_alinan_islemin_denetim_kaydi_yazilmaz(engine: Engine) -> None:
    from tp_core.audit import pending_audit

    with Session(engine) as s:
        c = _case(s)
        transition(s, c, "superseded", SYSTEM, "draft")
        assert [k[1] for k in pending_audit(s)] == ["test_case.transition"]
        s.rollback()
        assert pending_audit(s) == []
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM audit_event")).scalar_one() == 0


# ------------------------------------------- PO onayı içeriğe bağlı (case üretimi, Jira)


def _po_onayli(session: Session, make_user: MakeUser) -> Requirement:
    r = _pending_po(session)
    record_approval(session, r, make_user("po"), "po_approve")
    transition(session, r, "po_approved", SYSTEM, "pending_po")
    return r


def test_po_onayi_requirement_onaylanan_hashini_yazar(
    session: Session, make_user: MakeUser
) -> None:
    r = _po_onayli(session, make_user)
    assert r.onaylanan_hash == content_hash_of(r)
    transition(session, r, "generating", SYSTEM, "po_approved")
    transition(session, r, "cases_ready", SYSTEM, "generating")
    transition(session, r, "generating", SYSTEM, "cases_ready")  # içerik aynı → yeniden üretim
    transition(session, r, "failed", SYSTEM, "generating")
    transition(session, r, "generating", SYSTEM, "failed")
    transition(session, r, "failed", SYSTEM, "generating")
    transition(session, r, "new", SYSTEM, "failed")
    assert r.onaylanan_hash is None


@pytest.mark.parametrize(
    "degistir",
    [
        lambda r: setattr(r, "kabul_kriterleri", ["AC1: tamamen farklı"]),
        lambda r: setattr(r, "aciklama", "Jira'dan yeniden senkron: yeni metin"),
        lambda r: setattr(r, "baslik", "Yeni başlık"),
    ],
)
def test_po_onayindan_sonra_icerik_degisirse_case_uretilmez(
    session: Session, make_user: MakeUser, degistir: Callable[[Requirement], None]
) -> None:
    """Regresyon: PO onayından sonra AC değişti; po_approved → generating eskiden açıktı."""
    r = _po_onayli(session, make_user)
    degistir(r)
    with pytest.raises(GateClosed):
        transition(session, r, "generating", SYSTEM, "po_approved")
    assert r.durum == "po_approved"
    transition(session, r, "new", SYSTEM, "po_approved")  # yeniden PO onayı yolu açık


@pytest.mark.parametrize("ara", ["cases_ready", "failed"])
def test_yeniden_uretim_de_onayli_icerigi_denetler(
    session: Session, make_user: MakeUser, ara: str
) -> None:
    r = _po_onayli(session, make_user)
    transition(session, r, "generating", SYSTEM, "po_approved")
    transition(session, r, ara, SYSTEM, "generating")
    r.kabul_kriterleri = [*r.kabul_kriterleri, "AC9: sonradan"]
    with pytest.raises(GateClosed):
        transition(session, r, "generating", SYSTEM, ara)


def test_po_onayi_olmadan_failed_den_uretime_gidilmez(session: Session) -> None:
    r = _req(session)
    transition(session, r, "failed", SYSTEM, "new")
    with pytest.raises(GateClosed):
        transition(session, r, "generating", SYSTEM, "failed")


def test_icerik_degisim_zamani_yalnizca_icerikle_guncellenir(session: Session) -> None:
    r = _req(session)
    ilk = r.icerik_degisim
    assert ilk is not None
    r.kontrol_turu = 3  # içerik dışı alan
    session.flush()
    assert r.icerik_degisim == ilk
    r.aciklama = "değişti"
    session.flush()
    assert r.icerik_degisim > ilk
    acik = datetime(2026, 1, 1, tzinfo=UTC)  # senkron kodu Jira'daki zamanı açıkça verebilir
    r.aciklama = "Jira'dan"
    r.icerik_degisim = acik
    session.flush()
    assert r.icerik_degisim == acik


def test_jira_po_onayi_etiket_zamanini_ister(session: Session) -> None:
    r = _pending_po(session)
    for zaman in (None, datetime(2026, 10, 30, 12, 0)):  # yok / saat dilimsiz
        with pytest.raises(InvalidDecision, match="zaman"):
            _record_approval(
                session, r, None, "po_approve", kanal="jira", harici_onaylayan="po@sim.local",
                onay_zamani=zaman,
            )  # fmt: skip
    assert _review_sayisi(session) == 0


def test_jira_etiketinden_sonra_icerik_degistiyse_onay_reddedilir(session: Session) -> None:
    """PO etiketi T1'de (içerik C1) kondu; analist T2'de doküman düzeltmesi uyguladı (C2). Sonraki
    senkron etiketi okuduğunda C2'nin onaylandığını yazmamalı."""
    r = _pending_po(session)
    etiket = _simdi()
    r.aciklama = "Doküman düzeltmesi uygulandı (750,00 TL)"  # T2 > T1
    session.flush()
    assert r.icerik_degisim > etiket
    with pytest.raises(GateClosed, match="yeniden onay"):
        _record_approval(
            session, r, None, "po_approve", kanal="jira", harici_onaylayan="po@sim.local",
            onay_zamani=etiket,
        )  # fmt: skip
    assert _review_sayisi(session) == 0
    with pytest.raises(GateClosed):
        transition(session, r, "po_approved", SYSTEM, "pending_po")
    # PO güncel metni gördükten sonra etiketi yeniden koyar → kabul edilir.
    rv = _record_approval(
        session, r, None, "po_approve", kanal="jira", harici_onaylayan="po@sim.local",
        onay_zamani=r.icerik_degisim + timedelta(seconds=5),
    )  # fmt: skip
    assert rv.onaylanan_hash == content_hash_of(r)
    transition(session, r, "po_approved", SYSTEM, "pending_po")


def test_jira_onayi_etiket_anindaki_hash_verilirse_eslesmeli(session: Session) -> None:
    r = _pending_po(session)
    with pytest.raises(GateClosed, match="onayladığı içerik"):
        _record_approval(
            session, r, None, "po_approve", kanal="jira", harici_onaylayan="po@sim.local",
            onay_zamani=_simdi(), beklenen_hash="f" * 64,
        )  # fmt: skip
    rv = _record_approval(
        session, r, None, "po_approve", kanal="jira", harici_onaylayan="po@sim.local",
        onay_zamani=_simdi(), beklenen_hash=content_hash_of(r),
    )  # fmt: skip
    assert rv.kanal == "jira"


# ------------------------------------------------------- deterministik case kimliği


def test_case_id_deterministik(session: Session) -> None:
    r = _req(session, jira_key="TPD-42")
    a = case_id(r, 1, 1)
    assert a == case_id(r, 1, 1)
    assert len({a, case_id(r, 2, 1), case_id(r, 1, 2)}) == 3
    assert a.version == 5
    serbest = _req(session, kaynak="free_text", jira_key=None)
    assert case_id(serbest, 1, 1) == case_id(serbest, 1, 1) != a
    with pytest.raises(ValueError):
        case_id(r, 0, 1)


def test_ayni_case_iki_kez_eklenemez(engine: Engine) -> None:
    """Yeniden denenen üretim işi aynı kimliği üretir; ikinci ekleme reddedilir."""
    from sqlalchemy.exc import IntegrityError

    with Session(engine) as s:
        r = _req(s)
        rid = r.id
        _case(s, r)
        s.commit()
    with Session(engine) as s:
        r = s.get(Requirement, rid)
        assert r is not None
        with pytest.raises(IntegrityError):
            _case(s, r)  # aynı (requirement, sira, uretim) → aynı uuid5 → PK çakışması
        s.rollback()
    with Session(engine) as s, pytest.raises(IntegrityError, match="test_case_sira_uq"):
        # Kimlik başka verilse bile (requirement_id, sira_no, uretim_no) UNIQUE.
        s.add(TestCase(id=uuid.uuid4(), requirement_id=rid, sira_no=1, icerik={},
                       icerik_hash="x"))  # fmt: skip
        s.flush()


@pytest.mark.filterwarnings("ignore:Column 'test_case.id'")
def test_case_kimliksiz_eklenemez(session: Session) -> None:
    """Rastgele varsayılan yok: özellik kodu `case_id()` vermek zorunda."""
    from sqlalchemy.exc import IntegrityError

    r = _req(session)
    session.add(TestCase(requirement_id=r.id, sira_no=1, icerik={}, icerik_hash="x"))
    with pytest.raises(IntegrityError, match='"id"'):
        session.flush()
    session.rollback()


@pytest.mark.parametrize("yol", [["in_review", "failed"], ["failed"]])
def test_po_onayi_geri_cekilince_eski_onay_failed_den_uretimi_acmaz(
    session: Session, make_user: MakeUser, yol: list[str]
) -> None:
    """Regresyon: PO etiketi geri çekildi (→ new) → inceleme başarısız (→ failed). Son review
    hâlâ aynı içerikte `po_approve` olsa da failed → generating kapısı açılmamalı."""
    r = _po_onayli(session, make_user)
    transition(session, r, "new", SYSTEM, "po_approved")  # geri çekme
    assert r.onaylanan_hash is None
    once = "new"
    for hedef in yol:
        transition(session, r, hedef, SYSTEM, once)
        once = hedef
    assert approved_hash_matches(session, r)  # eski onay kaydı içerikle hâlâ eşleşiyor
    with pytest.raises(GateClosed, match="onay geri çekilmiş"):
        transition(session, r, "generating", SYSTEM, "failed")
    assert r.durum == "failed"
