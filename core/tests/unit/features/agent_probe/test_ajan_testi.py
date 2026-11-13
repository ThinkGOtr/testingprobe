"""Ajan ürünü bağlama ve Agent Probe ajan testi talebi (011 F6, K10; §4.4 A satırları).

Gerçek Postgres + gerçek API; Agent Probe süreç içi simülatör (`PgDeposu`: kayıt `ajan_testi_talebi`
satırı), denetlenebilir saat. Durum geçişleri: queued → running → passed (gereksinim `done` yalnız
`TP_AGENT_PROBE_SIM_TAMAMLAR=on` iken; varsayılan `simule`) | failed (bulgu, gereksinim
`po_approved` kalır); case üretimi ve tasarım modeli bağlı gereksinimde 409. Durum yalnız
`POST …/agent-test/refresh` (Testçi) ile ilerler; GET yan etkisizdir."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.unit.features.cases.helpers import login, rol_ol
from tp_core.audit import verify_chain
from tp_core.integrations.agent_probe import set_agent_probe_factory
from tp_core.integrations.agent_probe.sim import PgDeposu, SimAgentProbe, SimAjanTestleri
from tp_core.models import Requirement, session_scope


class Saat:
    def __init__(self) -> None:
        self.t = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.t


@pytest.fixture
def saat(db) -> Iterator[Saat]:
    s = Saat()
    set_agent_probe_factory(lambda: SimAgentProbe(SimAjanTestleri(PgDeposu(), saat=s)))
    yield s
    set_agent_probe_factory(None)


@pytest.fixture
def roller(make_user) -> dict:
    """012: ürünü Analist bağlar (`requirement.review`), ajan testini Testçi yürütür
    (`agent_test.run`)."""
    return {"analyst": make_user("analyst"), "tester": make_user("tester")}


@pytest.fixture
def analist(api: TestClient, roller: dict) -> TestClient:
    login(api, roller["analyst"])
    return api


def _bagla(api: TestClient, roller: dict, rid: uuid.UUID, urun_kodu: str | None):
    """Analist ajan ürününü bağlar; ardından Testçi oturumu açık kalır."""
    rol_ol(api, roller["analyst"])
    r = api.put(f"/requirements/{rid}/agent-product", json={"urun_kodu": urun_kodu})
    rol_ol(api, roller["tester"])
    return r


def _ilerlet(saat: Saat, s: float) -> None:
    saat.t = saat.t + timedelta(seconds=s)


def _yenile(api: TestClient, rid: uuid.UUID) -> dict:
    r = api.post(f"/requirements/{rid}/agent-test/refresh")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def sim_tamamlar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_AGENT_PROBE_SIM_TAMAMLAR", "on")


def test_urun_listesi_yalniz_hazir(analist: TestClient, saat: Saat) -> None:
    r = analist.get("/agent-probe/products")
    assert r.status_code == 200, r.text
    veri = r.json()
    assert veri["simulasyon"] is True and veri["kip"] == "sim"
    assert [u["kod"] for u in veri["urunler"]] == ["destek-asistani", "kredi-danismani"]


def test_gecen_ajan_testi_gereksinimi_tamamlar(
    analist: TestClient, roller: dict, saat: Saat, make_requirement, engine, sim_tamamlar
) -> None:
    rid = make_requirement()
    r = _bagla(analist, roller, rid, "destek-asistani")
    assert r.status_code == 200, r.text
    assert r.json()["urun_kodu"] == "destek-asistani" and r.json()["baslatilabilir"]

    # Bağlı gereksinimde case üretimi reddedilir.
    r = analist.post(f"/requirements/{rid}/generate-cases")
    assert r.status_code == 409 and r.json()["kod"] == "ajan_urunu", r.text

    r = analist.post(f"/requirements/{rid}/agent-test")
    assert r.status_code == 202, r.text
    talep = r.json()["talep"]
    assert talep["durum"] == "queued" and talep["talep_no"].startswith(f"APT-{saat.t.year}-")
    assert talep["simulasyon"] is True and not r.json()["baslatilabilir"]
    # Süren talep varken ikinci talep ve bağlantı değişikliği reddedilir.
    assert analist.post(f"/requirements/{rid}/agent-test").status_code == 409
    r = _bagla(analist, roller, rid, None)
    assert r.status_code == 409

    _ilerlet(saat, 10)
    # GET yan etkisizdir: süre geçse de durum yalnız POST refresh ile ilerler.
    v = analist.get(f"/requirements/{rid}/agent-test").json()
    assert v["talep"]["durum"] == "queued" and v["yenilenebilir"]
    assert _yenile(analist, rid)["talep"]["durum"] == "running"
    _ilerlet(saat, 60)
    assert analist.get(f"/requirements/{rid}/agent-test").json()["talep"]["durum"] == "running"
    v = _yenile(analist, rid)
    assert v["talep"]["durum"] == "passed" and v["talep"]["surec"] == "tamamlandi"
    assert v["talep"]["sonuc"]["gecen"] == 3 and not v["yenilenebilir"]
    with session_scope() as s:
        assert s.get(Requirement, rid).durum == "done"
    # Yeniden sorgu idempotent (bir kez işlenir).
    assert _yenile(analist, rid)["talep"] == v["talep"]
    with engine.connect() as c:
        eylemler = [
            r[0]
            for r in c.execute(
                text("SELECT eylem FROM audit_event WHERE nesne = :n ORDER BY id"),
                {"n": f"requirement:{rid}"},
            )
        ]
    for e in (
        "agent_probe.urun_baglandi",
        "agent_probe.test_baslatildi",
        "agent_probe.test_durumu",
        "agent_probe.sonuc_islendi",
        "requirement.transition",
    ):
        assert e in eylemler, eylemler
    assert eylemler.count("agent_probe.sonuc_islendi") == 1
    with engine.connect() as c:
        assert verify_chain(c).ok


def test_kalan_ajan_testi_bulgu_ve_yeniden_test(
    analist: TestClient, roller: dict, saat: Saat, make_requirement
) -> None:
    rid = make_requirement()
    _bagla(analist, roller, rid, "kredi-danismani")
    analist.post(f"/requirements/{rid}/agent-test")
    _ilerlet(saat, 200)
    v = _yenile(analist, rid)
    assert v["talep"]["durum"] == "failed" and v["talep"]["surec"] == "bulgu"
    assert v["talep"]["sonuc"]["kalan"] == 2
    with session_scope() as s:
        assert s.get(Requirement, rid).durum == "po_approved"
    assert v["baslatilabilir"]
    r = analist.post(f"/requirements/{rid}/agent-test")
    assert r.status_code == 202
    v = r.json()
    assert v["talep"]["durum"] == "queued" and len(v["gecmis"]) == 1
    assert v["talep"]["talep_no"] != v["gecmis"][0]["talep_no"]


def test_yetki_ve_engeller(api: TestClient, saat: Saat, make_requirement, make_user) -> None:
    rid = make_requirement(po_onayli=False)
    login(api, make_user("tester"))
    r = api.put(f"/requirements/{rid}/agent-product", json={"urun_kodu": "destek-asistani"})
    assert r.status_code == 403
    login(api, make_user("analyst"))
    r = api.put(f"/requirements/{rid}/agent-product", json={"urun_kodu": "kampanya-onerici"})
    assert r.status_code == 409 and r.json()["kod"] == "ajan_urunu_baglanamaz"
    r = api.put(f"/requirements/{rid}/agent-product", json={"urun_kodu": "destek-asistani"})
    assert r.status_code == 200
    v = api.get(f"/requirements/{rid}/agent-test").json()
    assert not v["baslatilabilir"] and "PO onaylı" in v["engel"]
    # Ajan testini başlatma / yenileme Testçinin (012 `agent_test.run`).
    assert api.post(f"/requirements/{rid}/agent-test").status_code == 403
    login(api, make_user("tester"))
    r = api.post(f"/requirements/{rid}/agent-test")
    assert r.status_code == 409 and r.json()["kod"] == "ajan_testi_baslatilamaz"
    assert api.get(f"/requirements/{uuid.uuid4()}/agent-test").status_code == 404
    assert api.post(f"/requirements/{uuid.uuid4()}/agent-test/refresh").status_code == 404
    # Yenileme (yan etkili) yalnız Testçi; GET herkese açık ve yan etkisiz.
    login(api, make_user("analyst"))
    assert api.post(f"/requirements/{rid}/agent-test/refresh").status_code == 403
    assert api.get(f"/requirements/{rid}/agent-test").status_code == 200


def test_icerik_degisirse_gecen_test_gereksinimi_ilerletmez(
    analist: TestClient, roller: dict, saat: Saat, make_requirement, sim_tamamlar
) -> None:
    rid = make_requirement()
    _bagla(analist, roller, rid, "destek-asistani")
    analist.post(f"/requirements/{rid}/agent-test")
    with session_scope() as s:
        s.get(Requirement, rid).aciklama = "Değişti"
    _ilerlet(saat, 100)
    v = _yenile(analist, rid)
    assert v["talep"]["durum"] == "passed" and v["talep"]["surec"] == "onay_gecersiz"
    with session_scope() as s:
        assert s.get(Requirement, rid).durum == "po_approved"


def test_case_varken_baglanamaz(
    analist: TestClient, roller: dict, saat: Saat, make_requirement, engine
) -> None:
    rid = make_requirement()
    with session_scope() as s:
        s.execute(
            text(
                "INSERT INTO test_case (id, requirement_id, sira_no, icerik, icerik_hash) "
                "VALUES (gen_random_uuid(), :r, 1, '{}'::jsonb, 'h')"
            ),
            {"r": rid},
        )
    r = _bagla(analist, roller, rid, "destek-asistani")
    assert r.status_code == 409, r.text


def test_simulasyon_sonucu_gereksinimi_tamamlamaz(
    analist: TestClient, roller: dict, saat: Saat, make_requirement, engine
) -> None:
    """Güvenlik #5: simüle edilmiş `passed` gerçek `done` geçişi yapmaz (varsayılan)."""
    rid = make_requirement()
    _bagla(analist, roller, rid, "destek-asistani")
    analist.post(f"/requirements/{rid}/agent-test")
    _ilerlet(saat, 100)
    v = _yenile(analist, rid)
    assert v["talep"]["durum"] == "passed" and v["talep"]["surec"] == "simule"
    assert "Simülasyon" in v["talep"]["surec_notu"] and v["sim_tamamlar"] is False
    with session_scope() as s:
        req = s.get(Requirement, rid)
        assert req.durum == "po_approved"
        # Durum makinesi koruması da simülasyonu geçmiş saymaz.
        from tp_core.features.agent_probe.service import ajan_testi_gecti

        assert ajan_testi_gecti(req) is False
    with engine.connect() as c:
        hedefler = [
            r[0]
            for r in c.execute(
                text(
                    "SELECT ozet->>'to' FROM audit_event WHERE nesne = :n "
                    "AND eylem = 'requirement.transition'"
                ),
                {"n": f"requirement:{rid}"},
            )
        ]
    assert "done" not in hedefler, hedefler


@pytest.mark.parametrize("durum", ["modeling", "model_ready", "generating", "cases_ready"])
def test_model_ve_uretim_durumlarinda_baglanti_degismez(
    analist: TestClient, saat: Saat, make_requirement, engine, durum: str
) -> None:
    rid = make_requirement()
    assert (
        analist.put(
            f"/requirements/{rid}/agent-product", json={"urun_kodu": "destek-asistani"}
        ).status_code
        == 200
    )
    with engine.begin() as c:  # test kurgusu: durum doğrudan (ORM koruması dışında)
        c.execute(text("UPDATE requirement SET durum = :d WHERE id = :r"), {"d": durum, "r": rid})
    for govde in ({"urun_kodu": "kredi-danismani"}, {"urun_kodu": None}):
        r = analist.put(f"/requirements/{rid}/agent-product", json=govde)
        assert r.status_code == 409 and r.json()["kod"] == "ajan_urunu_baglanamaz", r.text


def test_bagli_gereksinimde_tasarim_modeli_baslatilmaz(
    analist: TestClient, roller: dict, saat: Saat, make_requirement
) -> None:
    """İki tur yolu (POST design-model ve generate-cases kip=iki_tur) da 409 `ajan_urunu`."""
    rid = make_requirement()
    _bagla(analist, roller, rid, "destek-asistani")
    r = analist.post(f"/requirements/{rid}/design-model")
    assert r.status_code == 409 and r.json()["kod"] == "ajan_urunu", r.text
    r = analist.post(f"/requirements/{rid}/generate-cases", json={"kip": "iki_tur"})
    assert r.status_code == 409 and r.json()["kod"] == "ajan_urunu", r.text
    with session_scope() as s:
        assert s.get(Requirement, rid).durum == "po_approved"


class _KilitDenetleyenPort(SimAgentProbe):
    """`start_agent_test` sırasında gereksinim satırının kilitli OLMADIĞINI başka bağlantıdan
    `FOR UPDATE NOWAIT` ile doğrular (port çağrısı satır kilidi altında yapılmaz)."""

    def __init__(self, testler: SimAjanTestleri, sahip_url: str) -> None:
        super().__init__(testler)
        self.url = sahip_url
        self.kilitliydi: bool | None = None

    def start_agent_test(self, urun_kodu, requirement_id, gereksinim):  # type: ignore[no-untyped-def]
        import psycopg

        with psycopg.connect(self.url.replace("+psycopg", ""), autocommit=False) as c:
            try:
                c.execute(
                    "SELECT 1 FROM requirement WHERE id = %s FOR UPDATE NOWAIT", (requirement_id,)
                )
                self.kilitliydi = False
            except psycopg.errors.LockNotAvailable:
                self.kilitliydi = True
            c.rollback()
        return super().start_agent_test(urun_kodu, requirement_id, gereksinim)


def test_port_cagrisi_satir_kilidi_altinda_yapilmaz(
    analist: TestClient, roller: dict, saat: Saat, make_requirement, db
) -> None:
    port = _KilitDenetleyenPort(SimAjanTestleri(PgDeposu(), saat=saat), db.owner_url)
    set_agent_probe_factory(lambda: port)
    rid = make_requirement()
    _bagla(analist, roller, rid, "destek-asistani")
    r = analist.post(f"/requirements/{rid}/agent-test")
    assert r.status_code == 202, r.text
    assert port.kilitliydi is False


def test_talep_numarasi_diziden_tekil(saat: Saat, db) -> None:
    """Güvenlik #9: numara `ajan_testi_talebi_no_seq`'ten; ardışık çağrılar çakışmaz."""
    depo = PgDeposu()
    numaralar = [depo.sonraki_no(2026) for _ in range(5)]
    assert len(set(numaralar)) == 5 and numaralar == sorted(numaralar)


def test_tp_app_kayit_tablolarinda_yalniz_gereken_yetkiler(db) -> None:
    """Güvenlik #14 (0027): asistan_denetim S/I; ajan_testi_talebi S/I/U (kod neyi kullanıyorsa)."""
    import psycopg

    beklenen = {
        "asistan_denetim": {"SELECT", "INSERT"},
        "ajan_testi_talebi": {"SELECT", "INSERT", "UPDATE"},
        "ajan_urunu_baglantisi": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    }
    with psycopg.connect(db.app_url.replace("+psycopg", ""), autocommit=True) as c:
        for tablo, izinli in beklenen.items():
            for yetki in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                var = c.execute(
                    "SELECT has_table_privilege('tp_app', %s, %s)", (tablo, yetki)
                ).fetchone()[0]
                assert var == (yetki in izinli), (tablo, yetki)
        assert c.execute(
            "SELECT has_sequence_privilege('tp_app', 'ajan_testi_talebi_no_seq', 'USAGE')"
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("DELETE FROM asistan_denetim")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("DELETE FROM ajan_testi_talebi")
