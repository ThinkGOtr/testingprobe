"""0017: asistan tabloları model ↔ şema eşitliği, kısmi tekil indeksler, CHECK kısıtları,
tp_app yetkileri, `tool_call` kanal genişlemesi ve downgrade/upgrade (AI-ASISTAN-PLANI §8)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from tests.unit.conftest import Db, PgServer, run_alembic
from tp_core.models import Base, enums
from tp_core.models import asistan as asistan

TABLOLAR = {
    "asistan_sohbet",
    "asistan_mesaj",
    "asistan_durum",
    "asistan_oneri_geri_bildirim",
    "asistan_hiz",
}


def _ilgili(fark: object) -> bool:
    metin = repr(fark)
    return any(t in metin for t in (*TABLOLAR, "tool_call", "ai_call_parent_ix"))


_HIZ_EKLE = (
    "INSERT INTO asistan_hiz (kullanici_id, kova, pencere_baslangic) VALUES (%s, 'x', now())"
)
_ONERI_EKLE = (
    "INSERT INTO asistan_oneri_geri_bildirim (kullanici_id, kural_id, deger) VALUES (%s, 'k', 1)"
)


def _app(db: Db) -> psycopg.Connection:
    return psycopg.connect(db.app_url.replace("+psycopg", ""), autocommit=True)


@pytest.fixture
def c(db: Db) -> Iterator[psycopg.Connection]:
    with _app(db) as conn:
        yield conn


def _kullanici(c: psycopg.Connection) -> uuid.UUID:
    uid = uuid.uuid4()
    c.execute(
        "INSERT INTO app_user (id, kullanici_adi, rol, parola_hash) "
        "VALUES (%s, %s, 'analyst', 'h')",
        (uid, f"u_{uid.hex[:8]}"),
    )
    return uid


def _sohbet(c: psycopg.Connection, uid: uuid.UUID) -> uuid.UUID:
    return c.execute(
        "INSERT INTO asistan_sohbet (kullanici_id) VALUES (%s) RETURNING id", (uid,)
    ).fetchone()[0]


def _mesaj(
    c: psycopg.Connection, sohbet: uuid.UUID, uid: uuid.UUID, sira: int, **alan
) -> uuid.UUID:
    kolonlar = {"sohbet_id": sohbet, "kullanici_id": uid, "sira": sira, "rol": "assistant", **alan}
    adlar = ", ".join(kolonlar)
    yer = ", ".join(["%s"] * len(kolonlar))
    return c.execute(
        f"INSERT INTO asistan_mesaj ({adlar}) VALUES ({yer}) RETURNING id",
        tuple(kolonlar.values()),
    ).fetchone()[0]


# ------------------------------------------------------------------ şema


def test_asistan_modelleri_ve_migrasyon_ayni(db: Db) -> None:
    assert set(Base.metadata.tables) >= TABLOLAR
    eng = create_engine(db.owner_url)
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        farklar = [f for f in compare_metadata(ctx, Base.metadata) if _ilgili(f)]
    eng.dispose()
    assert farklar == []


def test_ai_call_parent_call_id_indeksli(db: Db) -> None:
    """Soru başı bütçe sorgusu her ajan turunda `parent_call_id` ile arar (tam tarama yok)."""
    with psycopg.connect(db.owner_url.replace("+psycopg", ""), autocommit=True) as o:
        tanim = o.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'ai_call' "
            "AND indexname = 'ai_call_parent_ix'"
        ).fetchone()
    assert tanim is not None and "(parent_call_id)" in tanim[0]


def test_kisit_adlari_sozlesmeyle_ayni(db: Db) -> None:
    """API IntegrityError'ı kısıt adına göre 409'a eşler; adlar migrasyonla birebir olmalı."""
    with psycopg.connect(db.owner_url.replace("+psycopg", ""), autocommit=True) as o:
        indeksler = {
            r[0]: r[1]
            for r in o.execute(
                "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'asistan_mesaj'"
            )
        }
        hiz = o.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
            (asistan.HIZ_UQ,),
        ).fetchone()[0]
    assert asistan.MESAJ_SIRA_UQ in indeksler
    assert "WHERE (ust_mesaj_id IS NOT NULL)" in indeksler[asistan.MESAJ_UST_UQ]
    bekleyen = indeksler[asistan.MESAJ_BEKLEYEN_UQ]
    assert "UNIQUE" in bekleyen and "'kullanici'" in bekleyen and "'running'" in bekleyen
    assert "NULLS NOT DISTINCT" in hiz


def test_tool_kanal_enum_asistan_icerir() -> None:
    assert {"agent", "ide", "asistan"} == enums.TOOL_KANAL


# ------------------------------------------------------------------ yetkiler


def test_tp_app_asistan_tablolarinda_tam_dml(c: psycopg.Connection) -> None:
    uid = _kullanici(c)
    sid = _sohbet(c, uid)
    c.execute("UPDATE asistan_sohbet SET silindi = true, silinme = now() WHERE id = %s", (sid,))
    mid = _mesaj(c, sid, uid, 1, rol="user", durum="done", icerik="soru")
    c.execute("UPDATE asistan_mesaj SET geri_bildirim = 1 WHERE id = %s", (mid,))
    c.execute("INSERT INTO asistan_durum (mod, kalp_atisi) VALUES ('live', now())")
    c.execute("UPDATE asistan_durum SET model_hazir = true")
    c.execute(
        "INSERT INTO asistan_oneri_geri_bildirim (kullanici_id, kural_id, deger, jira_anahtari) "
        "VALUES (%s, 'k', 2, 'TPD-1')",
        (uid,),
    )
    c.execute(_HIZ_EKLE, (uid,))
    for tablo in sorted(TABLOLAR):
        c.execute(f"DELETE FROM {tablo}")


# ------------------------------------------------------------------ kısmi tekil indeksler


def test_sohbette_sira_tekil(c: psycopg.Connection) -> None:
    uid = _kullanici(c)
    sid = _sohbet(c, uid)
    _mesaj(c, sid, uid, 1, rol="user", durum="done")
    with pytest.raises(psycopg.errors.UniqueViolation, match=asistan.MESAJ_SIRA_UQ):
        _mesaj(c, sid, uid, 1, rol="user", durum="done")
    _mesaj(c, _sohbet(c, uid), uid, 1, rol="user", durum="done")  # başka sohbette serbest


def test_kullanici_basina_tek_bekleyen_soru(c: psycopg.Connection) -> None:
    uid, diger = _kullanici(c), _kullanici(c)
    sid = _sohbet(c, uid)
    ilk = _mesaj(c, sid, uid, 1, durum="pending")
    with pytest.raises(psycopg.errors.UniqueViolation, match=asistan.MESAJ_BEKLEYEN_UQ):
        _mesaj(c, _sohbet(c, uid), uid, 1, durum="running")
    # Kullanıcı mesajları ve başka kullanıcı sayılmaz.
    _mesaj(c, sid, uid, 2, rol="user", durum="pending")
    _mesaj(c, _sohbet(c, diger), diger, 1, durum="pending")
    # Otomatik yükseltme çocuğu bekleyen hakkını tüketmez.
    _mesaj(
        c, sid, uid, 3, durum="pending", tetik="otomatik", amac="assistant_deep", ust_mesaj_id=ilk
    )
    # İlk mesaj bitince yeni soru açılabilir.
    c.execute("UPDATE asistan_mesaj SET durum = 'done' WHERE id = %s", (ilk,))
    _mesaj(c, sid, uid, 4, durum="pending")
    for i, son in enumerate(("done", "error", "iptal"), start=10):
        c.execute(
            "UPDATE asistan_mesaj SET durum = %s WHERE kullanici_id = %s AND rol = 'assistant' "
            "AND tetik = 'kullanici' AND durum = 'pending'",
            (son, uid),
        )
        _mesaj(c, sid, uid, i, durum="pending")


def test_bir_cevap_bir_kez_derinlestirilir(c: psycopg.Connection) -> None:
    uid = _kullanici(c)
    sid = _sohbet(c, uid)
    ust = _mesaj(c, sid, uid, 1, durum="done")
    _mesaj(c, sid, uid, 2, durum="done", amac="assistant_deep", ust_mesaj_id=ust)
    with pytest.raises(psycopg.errors.UniqueViolation, match=asistan.MESAJ_UST_UQ):
        _mesaj(c, sid, uid, 3, durum="done", amac="assistant_deep", ust_mesaj_id=ust)
    # Üst mesajı olmayanlar sınırsız.
    _mesaj(c, sid, uid, 4, durum="done")
    _mesaj(c, sid, uid, 5, durum="done")


def test_hiz_sayaci_global_kovada_tekil_ve_atomik(c: psycopg.Connection) -> None:
    uid = _kullanici(c)
    sql = (
        "INSERT INTO asistan_hiz (kullanici_id, kova, pencere_baslangic) "
        "VALUES (%s, %s, '2026-11-03T10:00:00+00') "
        "ON CONFLICT (kullanici_id, kova, pencere_baslangic) "
        "DO UPDATE SET sayi = asistan_hiz.sayi + 1 RETURNING sayi"
    )
    assert [c.execute(sql, (None, "jira_global")).fetchone()[0] for _ in range(3)] == [1, 2, 3]
    assert c.execute(sql, (uid, "jira_global")).fetchone()[0] == 1
    assert c.execute(sql, (uid, "oneri_liste")).fetchone()[0] == 1
    assert c.execute("SELECT count(*) FROM asistan_hiz").fetchone()[0] == 3
    with pytest.raises(psycopg.errors.UniqueViolation, match=asistan.HIZ_UQ):
        c.execute(
            "INSERT INTO asistan_hiz (kova, pencere_baslangic) "
            "VALUES ('jira_global', '2026-11-03T10:00:00+00')"
        )


# ------------------------------------------------------------------ CHECK kısıtları


@pytest.mark.parametrize(
    "alan",
    [
        {"rol": "system"},
        {"durum": "uydurma"},
        {"kaynak": "baska"},
        {"amac": "triage"},
        {"kip": "sohbet"},
        {"tetik": "zamanlayici"},
        {"geri_bildirim": 0},
        {"geri_bildirim": 2},
        # otomatik tetik yalnız üst mesajlı derin çocuk olabilir
        {"tetik": "otomatik"},
        {"tetik": "otomatik", "amac": "assistant_deep"},
    ],
)
def test_mesaj_check_kisitlari_gecersiz_degeri_reddeder(c: psycopg.Connection, alan: dict) -> None:
    uid = _kullanici(c)
    sid = _sohbet(c, uid)
    with pytest.raises(psycopg.errors.CheckViolation):
        _mesaj(c, sid, uid, 1, **{"durum": "done", **alan})


def test_mesaj_check_gecerli_degerleri_kabul_eder(c: psycopg.Connection) -> None:
    uid = _kullanici(c)
    sid = _sohbet(c, uid)
    ust = _mesaj(c, sid, uid, 1, durum="done", kaynak="model", amac="assistant", kip="oneri")
    _mesaj(
        c, sid, uid, 2, durum="pending", tetik="otomatik", amac="assistant_deep", ust_mesaj_id=ust
    )
    for i, k in enumerate(sorted(enums.ASISTAN_KAYNAK), start=3):
        _mesaj(c, sid, uid, i, durum="error", kaynak=k, geri_bildirim=-1)
    varsayilan = c.execute(
        "SELECT kip, tetik FROM asistan_mesaj WHERE id = %s",
        (_mesaj(c, sid, uid, 99, rol="user", durum="done"),),
    ).fetchone()
    assert varsayilan == ("soru", "kullanici")


def test_durum_tekil_satir_ve_mod(c: psycopg.Connection) -> None:
    c.execute("INSERT INTO asistan_durum DEFAULT VALUES")
    assert c.execute("SELECT id, mod, maskeleme FROM asistan_durum").fetchone() == (1, "off", False)
    with pytest.raises(psycopg.errors.UniqueViolation):
        c.execute("INSERT INTO asistan_durum DEFAULT VALUES")
    with pytest.raises(psycopg.errors.CheckViolation):
        c.execute("INSERT INTO asistan_durum (id) VALUES (2)")
    with pytest.raises(psycopg.errors.CheckViolation):
        c.execute("UPDATE asistan_durum SET mod = 'replay'")


def test_oneri_geri_bildirim_deger_check(c: psycopg.Connection) -> None:
    uid = _kullanici(c)
    for d in (-1, 1, 2):
        c.execute(
            "INSERT INTO asistan_oneri_geri_bildirim (kullanici_id, kural_id, deger, varlik_id, "
            "varlik_durum) VALUES (%s, 'k', %s, gen_random_uuid(), 'draft')",
            (uid, d),
        )
    for d in (0, 3, -2):
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO asistan_oneri_geri_bildirim (kullanici_id, kural_id, deger) "
                "VALUES (%s, 'k', %s)",
                (uid, d),
            )


def test_kullanici_silinince_kayitlari_silinir(db: Db, c: psycopg.Connection) -> None:
    uid = _kullanici(c)
    sid = _sohbet(c, uid)
    ust = _mesaj(c, sid, uid, 1, durum="done")
    _mesaj(c, sid, uid, 2, durum="done", amac="assistant_deep", ust_mesaj_id=ust)
    c.execute(_ONERI_EKLE, (uid,))
    c.execute(_HIZ_EKLE, (uid,))
    c.execute("DELETE FROM app_user WHERE id = %s", (uid,))
    for tablo in ("asistan_sohbet", "asistan_mesaj", "asistan_oneri_geri_bildirim", "asistan_hiz"):
        assert c.execute(f"SELECT count(*) FROM {tablo}").fetchone()[0] == 0


# ------------------------------------------------------------------ tool_call kanalı


def test_tool_call_asistan_kanalini_kabul_eder(c: psycopg.Connection) -> None:
    for kanal in ("agent", "ide", "asistan"):
        c.execute("INSERT INTO tool_call (kanal, arac) VALUES (%s, 'probe_requirement')", (kanal,))
    with pytest.raises(psycopg.errors.CheckViolation):
        c.execute("INSERT INTO tool_call (kanal, arac) VALUES ('portal', 'probe_requirement')")
    # append-only korunur
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("DELETE FROM tool_call WHERE kanal = 'asistan'")


def test_0017_downgrade_ve_yeniden_yukseltme(pg: PgServer) -> None:
    """Asistan satırı yokken geri alınır (tablolar düşer, kanal daralır); `kanal='asistan'`
    tool_call satırı varken geri alma bilerek başarısız olur (append-only, satır silinmez)."""
    ad = pg.create_empty_db()
    owner = pg.url("tp_owner", ad)
    dsn = owner.replace("+psycopg", "")
    try:
        run_alembic(owner, "head")
        run_alembic(owner, "0016", "downgrade")
        with psycopg.connect(dsn, autocommit=True) as o:
            for tablo in TABLOLAR:
                assert o.execute("SELECT to_regclass(%s)", (tablo,)).fetchone() == (None,)
            with pytest.raises(psycopg.errors.CheckViolation):
                o.execute("INSERT INTO tool_call (kanal, arac) VALUES ('asistan', 'x')")
        run_alembic(owner, "head")
        with psycopg.connect(dsn, autocommit=True) as o:
            o.execute("INSERT INTO tool_call (kanal, arac) VALUES ('asistan', 'x')")
        with pytest.raises(Exception, match="tool_call_kanal_ck"):
            run_alembic(owner, "0016", "downgrade")
        with psycopg.connect(dsn, autocommit=True) as o:
            assert o.execute("SELECT version_num FROM alembic_version").fetchone() == ("0017",)
            assert o.execute("SELECT to_regclass('asistan_mesaj')").fetchone()[0] is not None
    finally:
        with pg.super_conn() as s:
            s.execute(f'DROP DATABASE IF EXISTS "{ad}" WITH (FORCE)')
