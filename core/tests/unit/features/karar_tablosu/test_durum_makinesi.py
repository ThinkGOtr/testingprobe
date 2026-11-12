"""012 Ş0: `karar_tablosu` ve `metamorfik_iliski` durum makineleri (ANALIZ §4.1), yazma koruması,
0022 tablolarının yetkileri ve geri alma. Gerçek Postgres (platform fikstürü)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import psycopg
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from tests.unit.conftest import Db, run_alembic
from tp_core.audit import content_hash
from tp_core.features.karar_tablosu import hatalar
from tp_core.models import (
    STATEFUL,
    KararTablosu,
    MetamorfikIliski,
    Requirement,
    Review,
    StateWriteForbidden,
    enums,
)
from tp_core.workflow.service import (
    SYSTEM,
    ApprovalNotAllowed,
    ConcurrentTransition,
    GateClosed,
    InvalidDecision,
    InvalidTransition,
    OnayHashUyusmuyor,
    Principal,
    WorkflowError,
    approved_hash_matches,
    content_hash_of,
    record_approval,
    transition,
)
from tp_core.workflow.states import (
    APPROVER_ROLES,
    APPROVING,
    CONTENT_FIELDS,
    DECISION_EDITS,
    KARARLAR,
    MACHINES,
)

MakeUser = Callable[..., Principal]
TURLER = ("karar_tablosu", "metamorfik_iliski")
TABLO = {
    "ad": "Kampanya",
    "ac_refs": ["AC2"],
    "girdiler": [{"ad": "adet", "tur": "sayi"}],
    "ciktilar": [{"ad": "bedava_adet", "tur": "sayi"}],
    "satirlar": [{"id": "R1", "kosul": "dogru", "cikti": {"bedava_adet": "adet // 7"}}],
}
ILISKI = {
    "ad": "Adet iki katı",
    "ac_refs": ["AC2"],
    "on_kosul": "adet >= 1",
    "donusum": {"adet": "adet * 2"},
    "iliski": {"bedava_adet": "bedava_adet * 2"},
}
ICERIK: dict[str, dict[str, Any]] = {"karar_tablosu": TABLO, "metamorfik_iliski": ILISKI}


def _req(session: Session) -> Requirement:
    r = Requirement(
        kaynak="jira",
        jira_key=f"TPD-{uuid.uuid4().hex[:6]}",
        baslik="Kampanyalı sepet",
        kabul_kriterleri=["AC1: ...", "AC2: ..."],
        kaynak_hash="h",
    )
    session.add(r)
    session.flush()
    return r


def _nesne(session: Session, tur: str, sira_no: int = 1, req: Requirement | None = None) -> Any:
    req = req or _req(session)
    icerik = dict(ICERIK[tur])
    n = STATEFUL[tur](
        requirement_id=req.id, sira_no=sira_no, icerik=icerik, icerik_hash=content_hash(icerik)
    )
    session.add(n)
    session.flush()
    return n


def _onayla(session: Session, n: Any, po: Principal) -> Review:
    return record_approval(session, n, po, "approve", beklenen_hash=content_hash_of(n))


# ---------------------------------------------------------------------- tablolar (DB'siz)


@pytest.mark.parametrize("tur", TURLER)
def test_makine_tanimi(tur: str) -> None:
    m = MACHINES[tur]
    assert (m.entity, m.initial) == (tur, "draft")
    assert m.states == {"draft", "pending_po", "approved", "superseded"}
    assert {k: set(v) for k, v in m.transitions.items()} == {
        "draft": {"pending_po", "superseded"},
        "pending_po": {"approved", "draft", "superseded"},
        "approved": {"draft", "superseded"},
        "superseded": set(),
    }
    # Tek insan kapısı PO onayıdır; analistin geçişleri (gönder / geri çek / yeniden aç) kapısız.
    assert set(m.gates) == {("pending_po", "approved")}
    assert m.gates[("pending_po", "approved")].kararlar == {"approve"}
    assert m.guards == {} and m.approval_targets == {"approved"}
    assert not m.allowed("draft", "approved")  # PO'ya gönderilmeden onaylanamaz
    assert KARARLAR[tur] == {"approve", "request_changes"}
    assert APPROVING[tur] == {"approve"}
    assert APPROVER_ROLES[tur] == {"po"}
    assert CONTENT_FIELDS[tur] == ("icerik",)
    assert tur not in DECISION_EDITS  # karar içerik değiştiremez
    assert STATEFUL[tur].__tablename__ == tur
    assert tur in enums.REVIEW_NESNE and KARARLAR[tur] <= enums.REVIEW_KARAR


def test_hata_siniflari() -> None:
    beklenen = {
        hatalar.OracleUyumsuz: (422, "oracle_uyumsuz"),
        hatalar.OracleBekleniyor: (409, "oracle_bekleniyor"),
        hatalar.OracleKontrolsuz: (422, "oracle_kontrolsuz"),
        hatalar.OracleKontrolSiniri: (429, "oracle_kontrol_siniri"),
        hatalar.KararTablosuGecersiz: (422, "karar_tablosu_gecersiz"),
        hatalar.HataKosusuSuruyor: (409, "hata_kosusu_suruyor"),
        hatalar.IliskiGecersiz: (422, "iliski_gecersiz"),
    }
    assert set(hatalar.__all__) == {s.__name__ for s in beklenen}
    for sinif, (durum, kod) in beklenen.items():
        assert issubclass(sinif, WorkflowError)
        assert (sinif.status_code, sinif.kod) == (durum, kod)
    h = hatalar.KararTablosuGecersiz("Karar tablosu geçersiz", ["ad: boş olamaz", "x: y"])
    assert h.hatalar == ["ad: boş olamaz", "x: y"]
    assert str(h) == "Karar tablosu geçersiz — ad: boş olamaz; x: y"
    assert str(hatalar.IliskiGecersiz("İlişki geçersiz")) == "İlişki geçersiz"


# ---------------------------------------------------------------------- akış


@pytest.mark.parametrize("tur", TURLER)
def test_mutlu_yol_gonder_onayla(session: Session, make_user: MakeUser, tur: str) -> None:
    analist, po = make_user("analyst"), make_user("po")
    n = _nesne(session, tur)
    assert (n.durum, n.onaylanan_hash, n.ai_generated) == ("draft", None, False)
    assert content_hash_of(n) == n.icerik_hash

    transition(session, n, "pending_po", analist, "draft")  # gönder: onay kaydı gerekmez
    assert n.durum == "pending_po" and n.onaylanan_hash is None
    rv = _onayla(session, n, po)
    assert (rv.nesne_turu, rv.karar, rv.user_id) == (tur, "approve", po.id)
    assert rv.onaylanan_hash == n.icerik_hash
    transition(session, n, "approved", po, "pending_po")
    assert (n.durum, n.onaylanan_hash) == ("approved", n.icerik_hash)
    assert approved_hash_matches(session, n)
    session.commit()
    eylemler = session.execute(
        text("SELECT eylem FROM audit_event WHERE nesne = :n ORDER BY id"), {"n": f"{tur}:{n.id}"}
    ).scalars()
    assert list(eylemler) == [f"{tur}.transition", "review.approve", f"{tur}.transition"]


@pytest.mark.parametrize("tur", TURLER)
def test_onay_kaydi_olmadan_onaylanamaz(session: Session, make_user: MakeUser, tur: str) -> None:
    analist = make_user("analyst")
    n = _nesne(session, tur)
    with pytest.raises(InvalidTransition):
        transition(session, n, "approved", analist, "draft")
    transition(session, n, "pending_po", analist, "draft")
    for aktor in (analist, SYSTEM):
        with pytest.raises(GateClosed, match="insan onayı yok"):
            transition(session, n, "approved", aktor, "pending_po")
    assert n.durum == "pending_po"


@pytest.mark.parametrize("tur", TURLER)
@pytest.mark.parametrize("rol", ["analyst", "engineer", "tester", "presenter"])
def test_yalniz_po_karar_verir(session: Session, make_user: MakeUser, tur: str, rol: str) -> None:
    n = _nesne(session, tur)
    transition(session, n, "pending_po", SYSTEM, "draft")
    for karar in ("approve", "request_changes"):
        with pytest.raises(ApprovalNotAllowed, match=f"{rol} rolü {tur} için karar veremez"):
            _record(session, n, make_user(rol), karar)


def _record(session: Session, n: Any, user: Principal | None, karar: str, **kw: Any) -> Review:
    kw.setdefault("beklenen_hash", content_hash_of(n))
    return record_approval(session, n, user, karar, **kw)


@pytest.mark.parametrize("tur", TURLER)
def test_sistem_ide_ve_jira_onay_veremez(session: Session, make_user: MakeUser, tur: str) -> None:
    po = make_user("po")
    n = _nesne(session, tur)
    transition(session, n, "pending_po", SYSTEM, "draft")
    ide = Principal(po.id, po.kullanici_adi, "po", "ide")
    for kim in (SYSTEM, ide, None):
        with pytest.raises(ApprovalNotAllowed):
            _record(session, n, kim, "approve")
    with pytest.raises(ApprovalNotAllowed, match="Jira kanalı yalnızca PO teyidi"):
        _record(session, n, None, "approve", kanal="jira", harici_onaylayan="po@firma")
    for karar in ("po_approve", "edit", "reject", "reopen", "merge"):
        with pytest.raises(InvalidDecision, match="geçersiz karar"):
            _record(session, n, po, karar)
    with pytest.raises(InvalidDecision, match="şu alanları değiştiremez"):
        _record(session, n, po, "approve", degisiklik={"icerik": {"ad": "başka"}})


@pytest.mark.parametrize("tur", TURLER)
def test_gorulen_hash_zorunlu_ve_guncel_olmali(
    session: Session, make_user: MakeUser, tur: str
) -> None:
    po = make_user("po")
    n = _nesne(session, tur)
    transition(session, n, "pending_po", SYSTEM, "draft")
    with pytest.raises(InvalidDecision, match="icerik_hash"):
        record_approval(session, n, po, "approve")
    with pytest.raises(OnayHashUyusmuyor):
        record_approval(session, n, po, "approve", beklenen_hash="eski")


@pytest.mark.parametrize("tur", TURLER)
def test_onaydan_sonra_icerik_degisirse_kapi_kapanir(
    session: Session, make_user: MakeUser, tur: str
) -> None:
    po = make_user("po")
    n = _nesne(session, tur)
    transition(session, n, "pending_po", SYSTEM, "draft")
    _onayla(session, n, po)
    n.icerik = {**n.icerik, "ad": "PO'nun görmediği ad"}
    n.icerik_hash = content_hash(n.icerik)
    with pytest.raises(GateClosed):
        transition(session, n, "approved", po, "pending_po")


@pytest.mark.parametrize("tur", TURLER)
def test_degisiklik_iste_ve_geri_cek(session: Session, make_user: MakeUser, tur: str) -> None:
    analist, po = make_user("analyst"), make_user("po")
    n = _nesne(session, tur)
    # PO değişiklik ister: onaylamayan kayıtlı karar + pending_po → draft.
    transition(session, n, "pending_po", analist, "draft")
    rv = _record(session, n, po, "request_changes", gerekce="R2 eksik")
    assert (rv.karar, rv.gerekce, rv.ret_nedeni) == ("request_changes", "R2 eksik", None)
    transition(session, n, "draft", po, "pending_po", sebep="degisiklik_istendi")
    assert n.durum == "draft" and not approved_hash_matches(session, n)
    # `request_changes` kapıyı açmaz.
    transition(session, n, "pending_po", analist, "draft")
    with pytest.raises(GateClosed):
        transition(session, n, "approved", po, "pending_po")
    # Analist geri çeker: onay kaydı gerekmez.
    transition(session, n, "draft", analist, "pending_po", sebep="geri_cekildi")
    assert n.durum == "draft"
    assert session.scalars(select(Review).where(Review.nesne_id == n.id)).all() == [rv]


@pytest.mark.parametrize("tur", TURLER)
def test_yeniden_ac_onayli_hashi_siler(session: Session, make_user: MakeUser, tur: str) -> None:
    analist, po = make_user("analyst"), make_user("po")
    n = _nesne(session, tur)
    transition(session, n, "pending_po", analist, "draft")
    _onayla(session, n, po)
    transition(session, n, "approved", po, "pending_po")
    transition(session, n, "draft", analist, "approved", sebep="yeniden_acildi")
    assert (n.durum, n.onaylanan_hash) == ("draft", None)
    # Düzenlenip yeniden gönderilen içerik eski onayla geçemez; PO yeniden onaylar.
    n.icerik = {**n.icerik, "ad": "Düzeltilmiş"}
    n.icerik_hash = content_hash(n.icerik)
    transition(session, n, "pending_po", analist, "draft")
    with pytest.raises(GateClosed):
        transition(session, n, "approved", po, "pending_po")
    _onayla(session, n, po)
    transition(session, n, "approved", po, "pending_po")
    assert (n.durum, n.onaylanan_hash) == ("approved", n.icerik_hash)


@pytest.mark.parametrize("tur", TURLER)
@pytest.mark.parametrize("kaynak", ["draft", "pending_po", "approved"])
def test_her_durumdan_superseded_ve_son_durum(
    session: Session, make_user: MakeUser, tur: str, kaynak: str
) -> None:
    po = make_user("po")
    n = _nesne(session, tur)
    if kaynak != "draft":
        transition(session, n, "pending_po", SYSTEM, "draft")
    if kaynak == "approved":
        _onayla(session, n, po)
        transition(session, n, "approved", po, "pending_po")
    transition(session, n, "superseded", SYSTEM, kaynak, sebep="yeni_taslak")
    assert n.durum == "superseded"
    for hedef in ("draft", "pending_po", "approved"):
        with pytest.raises(InvalidTransition):
            transition(session, n, hedef, SYSTEM, "superseded")


@pytest.mark.parametrize("tur", TURLER)
def test_beklenen_durum_ve_yazma_korumasi(session: Session, tur: str) -> None:
    n = _nesne(session, tur)
    with pytest.raises(ConcurrentTransition):
        transition(session, n, "approved", SYSTEM, "pending_po")
    n.durum = "approved"
    with pytest.raises(StateWriteForbidden, match=f"{tur}.durum"):
        session.flush()
    session.rollback()

    req = _req(session)
    icerik = dict(ICERIK[tur])
    ortak = {"requirement_id": req.id, "icerik": icerik, "icerik_hash": content_hash(icerik)}
    session.add(STATEFUL[tur](sira_no=1, durum="approved", **ortak))
    with pytest.raises(StateWriteForbidden, match="yalnızca 'draft' durumuyla"):
        session.flush()
    session.rollback()
    req = _req(session)
    session.add(
        STATEFUL[tur](sira_no=1, onaylanan_hash="h", **(ortak | {"requirement_id": req.id}))
    )
    with pytest.raises(StateWriteForbidden, match="onaylanan_hash"):
        session.flush()
    session.rollback()


def test_iliski_tabloya_baglanir_ve_sira_tekildir(session: Session) -> None:
    req = _req(session)
    t = _nesne(session, "karar_tablosu", 1, req)
    i = _nesne(session, "metamorfik_iliski", 1, req)
    i.karar_tablosu_id = t.id
    i.gereksinim_hash = content_hash_of(req)  # korunan alan değil; servis yazar
    session.flush()
    assert isinstance(t, KararTablosu) and isinstance(i, MetamorfikIliski)
    session.commit()
    _nesne(session, "karar_tablosu", 2, req)
    session.commit()
    with pytest.raises(Exception, match="karar_tablosu_sira_uq"):
        _nesne(session, "karar_tablosu", 2, req)
    session.rollback()


# ---------------------------------------------------------------------- migrasyon 0022

YENI_TABLOLAR = (
    "karar_tablosu",
    "metamorfik_iliski",
    "case_oracle_kontrol",
    "metamorfik_turetme",
    "hata_kosusu",
    "hata_kosusu_adim",
)


def _app(db: Db) -> psycopg.Connection:
    return psycopg.connect(db.app_url.replace("+psycopg", ""), autocommit=True)


def test_tp_app_yazar_ama_silemez(db: Db) -> None:
    with _app(db) as c:
        rid = c.execute(
            "INSERT INTO requirement (kaynak, baslik, kaynak_hash) "
            "VALUES ('free_text', 'b', 'h') RETURNING id"
        ).fetchone()[0]
        cid = uuid.uuid4()
        c.execute(
            "INSERT INTO test_case (id, requirement_id, sira_no, icerik, icerik_hash) "
            "VALUES (%s, %s, 1, '{}', 'x')",
            (cid, rid),
        )
        tid = c.execute(
            "INSERT INTO karar_tablosu (requirement_id, sira_no, icerik, icerik_hash) "
            "VALUES (%s, 1, '{}', 'h') RETURNING id",
            (rid,),
        ).fetchone()[0]
        iid = c.execute(
            "INSERT INTO metamorfik_iliski (requirement_id, karar_tablosu_id, sira_no, icerik, "
            "icerik_hash) VALUES (%s, %s, 1, '{}', 'h') RETURNING id",
            (rid, tid),
        ).fetchone()[0]
        c.execute(
            "INSERT INTO case_oracle_kontrol (test_case_id, icerik_hash, sonuc) "
            "VALUES (%s, 'x', 'uyumlu')",
            (cid,),
        )
        c.execute(
            "INSERT INTO metamorfik_turetme (iliski_id, kaynak_case_id, sonuc) "
            "VALUES (%s, %s, 'olgu_yok')",
            (iid, cid),
        )
        kid = c.execute("INSERT INTO hata_kosusu DEFAULT VALUES RETURNING id").fetchone()[0]
        c.execute(
            "INSERT INTO hata_kosusu_adim (kosu_id, platform, asama, sira) "
            "VALUES (%s, 'web', 'temel', 0)",
            (kid,),
        )
        c.execute(
            "INSERT INTO hata_kosusu_adim (kosu_id, platform, asama, hata_kodu, sira) "
            "VALUES (%s, 'web', 'hata', 'kampanya_esik_7', 1)",
            (kid,),
        )
        varsayilan = c.execute(
            "SELECT k.durum, a.sonuc FROM hata_kosusu k JOIN hata_kosusu_adim a "
            "ON a.kosu_id = k.id WHERE a.sira = 0"
        ).fetchone()
        assert varsayilan == ("queued", "bekliyor")
        for tablo in YENI_TABLOLAR:
            c.execute(f"UPDATE {tablo} SET id = id")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(f"DELETE FROM {tablo}")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(f"TRUNCATE {tablo}")
        # Tekillik ve CHECK kısıtları
        with pytest.raises(
            psycopg.errors.UniqueViolation, match="case_oracle_kontrol_case_hash_uq"
        ):
            c.execute(
                "INSERT INTO case_oracle_kontrol (test_case_id, icerik_hash, sonuc) "
                "VALUES (%s, 'x', 'uyumsuz')",
                (cid,),
            )
        with pytest.raises(psycopg.errors.UniqueViolation, match="metamorfik_turetme_cift_uq"):
            c.execute(
                "INSERT INTO metamorfik_turetme (iliski_id, kaynak_case_id, sonuc) "
                "VALUES (%s, %s, 'turetildi')",
                (iid, cid),
            )
        for sql in (
            "INSERT INTO case_oracle_kontrol (test_case_id, icerik_hash, sonuc) "
            f"VALUES ('{cid}', 'y', 'belki')",
            f"UPDATE karar_tablosu SET durum = 'published' WHERE id = '{tid}'",
            f"UPDATE hata_kosusu SET durum = 'bitti' WHERE id = '{kid}'",
            # temel / kapanış adımında hata kodu olmaz; hata adımında zorunludur
            "INSERT INTO hata_kosusu_adim (kosu_id, platform, asama, hata_kodu, sira) "
            f"VALUES ('{kid}', 'web', 'kapanis', 'x', 2)",
            "INSERT INTO hata_kosusu_adim (kosu_id, platform, asama, sira) "
            f"VALUES ('{kid}', 'web', 'hata', 3)",
            "INSERT INTO hata_kosusu_adim (kosu_id, platform, asama, sira) "
            f"VALUES ('{kid}', 'linux', 'temel', 4)",
        ):
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute(sql)
        # PO kararı review'a yazılabilir (nesne türü CHECK genişledi)
        for tur in TURLER:
            c.execute(
                "INSERT INTO review (nesne_turu, nesne_id, harici_onaylayan, karar, "
                "onaylanan_hash) VALUES (%s, gen_random_uuid(), 'po', 'approve', 'h')",
                (tur,),
            )


def test_0022_geri_alinir_ve_yeniden_yukselir(db: Db) -> None:
    dsn = db.owner_url.replace("+psycopg", "")
    ekle = (
        "INSERT INTO review (nesne_turu, nesne_id, harici_onaylayan, karar, onaylanan_hash) "
        "VALUES ('karar_tablosu', gen_random_uuid(), 'po', 'approve', 'h')"
    )
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(ekle)
    run_alembic(db.owner_url, "0020", "downgrade")
    with psycopg.connect(dsn, autocommit=True) as c:
        kalan = c.execute(
            "SELECT count(*) FROM pg_tables WHERE tablename = ANY(%s)", (list(YENI_TABLOLAR),)
        ).fetchone()
        assert kalan == (0,)
        # İnsan kararı silinmez (review append-only); eski alan yalnız yeni satırlara uygulanır.
        assert c.execute("SELECT count(*) FROM review").fetchone() == (1,)
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(ekle)
    run_alembic(db.owner_url, "head")
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(ekle)
        assert c.execute("SELECT count(*) FROM karar_tablosu").fetchone() == (0,)
