"""Migrasyon 0002/0003: model ↔ şema eşitliği, yetkiler, append-only, zincir backfill, downgrade."""

from __future__ import annotations

import re
import uuid

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text

from tp_core.audit import append_audit, verify_chain
from tp_core.models import Base
from tp_core.workflow.states import MACHINES

from .conftest import Db, PgServer, run_alembic

APPEND_ONLY = ("ai_call", "tool_call", "audit_event")
# 0003: insan kararları (onay kapılarının doğruluk kaynağı) da append-only.
TP_APP_YAZAMAZ = (*APPEND_ONLY, "review")


def test_modeller_ve_migrasyon_ayni(db: Db) -> None:
    eng = create_engine(db.owner_url)
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        farklar = compare_metadata(ctx, Base.metadata)
    eng.dispose()
    # alembic_version tablosu modellerde yoktur.
    farklar = [
        f
        for f in farklar
        if not (f[0] == "remove_table" and getattr(f[1], "name", "") == "alembic_version")
    ]
    assert farklar == []


def test_tum_tablolar_var(db: Db) -> None:
    eng = create_engine(db.owner_url)
    with eng.connect() as conn:
        tablolar = set(
            conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            ).scalars()
        )
    eng.dispose()
    assert set(Base.metadata.tables) <= tablolar


@pytest.mark.parametrize("entity", sorted(MACHINES))
def test_durum_check_kisiti_makineyle_ayni(db: Db, entity: str) -> None:
    eng = create_engine(db.owner_url)
    with eng.connect() as conn:
        tanim = conn.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
            {"n": f"{entity}_durum_ck"},
        ).scalar_one()
    eng.dispose()
    assert set(re.findall(r"'([a-z_]+)'", tanim)) == set(MACHINES[entity].states)


def _app(db: Db) -> psycopg.Connection:
    return psycopg.connect(db.app_url.replace("+psycopg", ""), autocommit=True)


@pytest.mark.parametrize("tablo", TP_APP_YAZAMAZ)
@pytest.mark.parametrize("islem", ["UPDATE {t} SET id = id", "DELETE FROM {t}", "TRUNCATE {t}"])
def test_tp_app_append_only_tablolari_degistiremez(db: Db, tablo: str, islem: str) -> None:
    with _app(db) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute(islem.format(t=tablo))


@pytest.mark.parametrize("tablo", APPEND_ONLY)
def test_sahip_bile_append_only_tablolari_degistiremez(db: Db, tablo: str) -> None:
    eng = create_engine(db.app_url)
    with eng.begin() as conn:
        append_audit(conn, "test", "satir.var")
    eng.dispose()
    with psycopg.connect(db.owner_url.replace("+psycopg", ""), autocommit=True) as c:
        c.execute(
            "INSERT INTO ai_call (amac, saglayici, model, mod) "
            "VALUES ('t', 'replay', 'm', 'replay')"
        )
        c.execute("INSERT INTO tool_call (kanal, arac) VALUES ('agent', 'browser_snapshot')")
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
            c.execute(f"DELETE FROM {tablo}")
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
            c.execute(f"TRUNCATE {tablo}")


def test_tp_app_diger_tablolarda_tam_dml(db: Db) -> None:
    rid = uuid.uuid4()
    with _app(db) as c:
        c.execute(
            "INSERT INTO requirement (id, kaynak, baslik, kaynak_hash) "
            "VALUES (%s, 'free_text', 'b', 'h')",
            (rid,),
        )
        c.execute("UPDATE requirement SET baslik = 'c' WHERE id = %s", (rid,))
        c.execute(
            "INSERT INTO pull_request (branch, baslik, head_sha, acan) VALUES ('b','t','s','bot')"
        )
        c.execute("INSERT INTO review (nesne_turu, nesne_id, harici_onaylayan, kanal, karar, "
                  "onaylanan_hash) VALUES ('requirement', %s, 'po@sim', 'jira', 'po_approve', 'h')",
                  (rid,))  # fmt: skip
        c.execute("DELETE FROM requirement WHERE id = %s", (rid,))


_REVIEW_INSERT = (
    "INSERT INTO review (nesne_turu, nesne_id, harici_onaylayan, kanal, karar, onaylanan_hash) "
    "VALUES ('requirement', gen_random_uuid(), 'po@firma', 'jira', 'reject', 'h')"
)


def test_review_insan_karari_degistirilemez_ve_silinemez(db: Db) -> None:
    """Onay kaydı tp_app (core-api/core-worker) tarafından değiştirilemez: reddi silip ya da
    onaylanan hash'i güncelleyip kapıyı açmak mümkün değil (Constitution I/VIII)."""
    with _app(db) as c:
        c.execute(_REVIEW_INSERT.replace("'reject'", "'po_approve'"))  # INSERT serbest
        for islem in (
            "UPDATE review SET onaylanan_hash = 'sahte'",
            "UPDATE review SET karar = 'po_approve'",
            "DELETE FROM review",
            "TRUNCATE review",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(islem)
        assert c.execute("SELECT count(*) FROM review").fetchone() == (1,)
    # Tablo sahibi de (tetikleyici) değiştiremez.
    with psycopg.connect(db.owner_url.replace("+psycopg", ""), autocommit=True) as c:
        for islem in ("UPDATE review SET onaylanan_hash = 'sahte'", "DELETE FROM review",
                      "TRUNCATE review"):  # fmt: skip
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
                c.execute(islem)


def test_manual_tetigi_kabul_edilir(db: Db) -> None:
    """CI'nin workflow_dispatch tetiği (`manual`) run ve test_result'a yazılabilir."""
    with _app(db) as c:
        c.execute("INSERT INTO run (kaynak, tetik, sonuc) VALUES ('github', 'manual', 'passed')")
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute("INSERT INTO run (kaynak, tetik, sonuc) VALUES ('github', 'elle', 'passed')")


def test_job_zaman_asimi_bos_birakilabilir(db: Db) -> None:
    with _app(db) as c:
        c.execute("INSERT INTO job (tur) VALUES ('x')")
        assert c.execute("SELECT zaman_asimi_s FROM job").fetchone() == (None,)


def test_check_kisitlari_gecersiz_degeri_reddeder(db: Db) -> None:
    with _app(db) as c:
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO requirement (kaynak, baslik, kaynak_hash, durum) "
                "VALUES ('free_text', 'b', 'h', 'uydurma')"
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO requirement (kaynak, baslik, kaynak_hash) VALUES ('jira', 'b', 'h')"
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO review (nesne_turu, nesne_id, harici_onaylayan, karar, "
                "onaylanan_hash) VALUES ('test_case', gen_random_uuid(), 'x', 'reject', 'h')"
            )


def test_audit_hash_zorunlu(db: Db) -> None:
    # Zinciri atlayan ham INSERT reddedilir: tüm yazıcılar append_audit'ten geçmek zorunda.
    with _app(db) as c, pytest.raises(psycopg.errors.NotNullViolation):
        c.execute("INSERT INTO audit_event (aktor, eylem) VALUES ('x', 'y')")


def test_0001_verisi_zincire_baglanir_ve_downgrade_calisir(pg: PgServer) -> None:
    ad = pg.create_empty_db()
    owner = pg.url("tp_owner", ad)
    try:
        run_alembic(owner, "0001")
        with psycopg.connect(owner.replace("+psycopg", ""), autocommit=True) as c:
            c.execute(
                "INSERT INTO audit_event (aktor, eylem, ozet) VALUES "
                "('system', 'seed.applied', '{\"yeni\": 5}'), ('system', 'x', NULL), "
                "('ali', 'ş', '{\"büyük\": 1e20, \"liste\": [1, 2.5]}')"
            )
            c.execute("INSERT INTO job (tur) VALUES ('noop')")
        run_alembic(owner, "head")
        eng = create_engine(owner)
        with eng.connect() as conn:
            sonuc = verify_chain(conn)
            assert sonuc.ok, sonuc
            assert sonuc.count == 3
            assert conn.execute(text("SELECT run_after IS NOT NULL FROM job")).scalar_one()
        eng.dispose()

        run_alembic(owner, "0001", "downgrade")
        with psycopg.connect(owner.replace("+psycopg", ""), autocommit=True) as c:
            kolonlar = {
                r[0]
                for r in c.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'audit_event'"
                )
            }
            assert "hash" not in kolonlar
            assert c.execute("SELECT to_regclass('public.test_case')").fetchone() == (None,)
            assert c.execute("SELECT count(*) FROM audit_event").fetchone() == (3,)
        run_alembic(owner, "head")  # yeniden yükseltilebilir
    finally:
        with pg.super_conn() as c:
            c.execute(f'DROP DATABASE IF EXISTS "{ad}" WITH (FORCE)')


def test_0004_mevcut_veriyle_yukselir_ve_geri_alinir(pg: PgServer) -> None:
    """0003 verisi (gereksinim + rastgele kimlikli case) 0004'e taşınır; icerik_degisim dolu,
    case tekilliği ve kimlik varsayılanı uygulanır; downgrade/upgrade tekrar çalışır."""
    ad = pg.create_empty_db()
    owner = pg.url("tp_owner", ad)
    dsn = owner.replace("+psycopg", "")
    try:
        run_alembic(owner, "0003")
        with psycopg.connect(dsn, autocommit=True) as c:
            rid = c.execute(
                "INSERT INTO requirement (kaynak, jira_key, baslik, kaynak_hash, guncelleme) "
                "VALUES ('jira', 'TPD-1', 'b', 'h', '2026-01-02T03:04:05+00') RETURNING id"
            ).fetchone()[0]
            c.execute(
                "INSERT INTO test_case (requirement_id, sira_no, icerik, icerik_hash) "
                "VALUES (%s, 1, '{}', 'x')",
                (rid,),
            )
        run_alembic(owner, "head")
        with psycopg.connect(dsn, autocommit=True) as c:
            degisim, onay = c.execute(
                "SELECT icerik_degisim, onaylanan_hash FROM requirement WHERE id = %s", (rid,)
            ).fetchone()
            assert degisim.isoformat().startswith("2026-01-02T03:04:05") and onay is None
            with pytest.raises(psycopg.errors.NotNullViolation):
                c.execute(
                    "INSERT INTO test_case (requirement_id, sira_no, icerik, icerik_hash) "
                    "VALUES (%s, 2, '{}', 'x')",
                    (rid,),
                )
            with pytest.raises(psycopg.errors.UniqueViolation, match="test_case_sira_uq"):
                c.execute(
                    "INSERT INTO test_case (id, requirement_id, sira_no, icerik, icerik_hash) "
                    "VALUES (gen_random_uuid(), %s, 1, '{}', 'x')",
                    (rid,),
                )
        run_alembic(owner, "0003", "downgrade")
        with psycopg.connect(dsn, autocommit=True) as c:
            kolonlar = {
                r[0]
                for r in c.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'requirement'"
                )
            }
            assert not {"icerik_degisim", "onaylanan_hash"} & kolonlar
            c.execute(
                "INSERT INTO test_case (requirement_id, sira_no, icerik, icerik_hash) "
                "VALUES (%s, 1, '{}', 'x')",
                (rid,),
            )  # 0003'te kimlik varsayılanı ve tekillik yok
            # Yeniden yükseltmeden önce çift kaydı temizle (0004 tekilliği eklerken reddederdi).
            c.execute(
                "DELETE FROM test_case WHERE id <> "
                "(SELECT id FROM test_case ORDER BY olusturma, id LIMIT 1)"
            )
        run_alembic(owner, "head")
    finally:
        with pg.super_conn() as c:
            c.execute(f'DROP DATABASE IF EXISTS "{ad}" WITH (FORCE)')


def test_0008_downgrade_reopen_kararini_silmez(pg: PgServer) -> None:
    """'reopen' insan kararı varken 0008 geri alınabilir ve kayıt korunur (review append-only,
    Anayasa VIII); eski karar alanı yalnızca yeni satırlara uygulanır."""
    ad = pg.create_empty_db()
    owner = pg.url("tp_owner", ad)
    dsn = owner.replace("+psycopg", "")
    try:
        run_alembic(owner, "0008")
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute(_REVIEW_INSERT.replace("'requirement'", "'test_case'").replace(
                "'reject'", "'reopen'"))  # fmt: skip
        run_alembic(owner, "0007", "downgrade")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT count(*) FROM review WHERE karar = 'reopen'").fetchone() == (
                1,
            )
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute(_REVIEW_INSERT.replace("'reject'", "'reopen'"))
        run_alembic(owner, "head")  # yeniden yükseltilebilir
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute(_REVIEW_INSERT.replace("'reject'", "'reopen'"))
    finally:
        with pg.super_conn() as c:
            c.execute(f'DROP DATABASE IF EXISTS "{ad}" WITH (FORCE)')


# 0040 (eski 0026; specs/011 D1 #19): kalite tabloları en az yetkiyle; tamamlanan denetim kararlı.
KALITE_TABLOLARI = ("case_uretim", "tasarim_modeli", "case_set_review", "case_set_audit")


@pytest.mark.parametrize("tablo", KALITE_TABLOLARI)
@pytest.mark.parametrize("islem", ["DELETE FROM {t}", "TRUNCATE {t}"])
def test_0040_tp_app_kalite_kayitlarini_silemez(db: Db, tablo: str, islem: str) -> None:
    with _app(db) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute(islem.format(t=tablo))


def test_0040_tamamlanan_denetim_kararsiz_yazilamaz(db: Db) -> None:
    rid = uuid.uuid4()
    with _app(db) as c:
        c.execute(
            "INSERT INTO requirement (id, kaynak, baslik, kaynak_hash) "
            "VALUES (%s, 'free_text', 'b', 'h')",
            (rid,),
        )
        ekle = (
            "INSERT INTO case_set_audit (requirement_id, set_hash, durum, karar) "
            "VALUES (%s, 'h', %s, %s)"
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(ekle, (rid, "tamamlandi", None))
        c.execute(ekle, (rid, "bekliyor", None))
        c.execute(ekle, (rid, "tamamlandi", "KABUL"))
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute("UPDATE case_set_audit SET karar = NULL WHERE durum = 'tamamlandi'")
        # Gereksinim silinince kalite kayıtları (CASCADE) tablo sahibi yetkisiyle silinir.
        c.execute("DELETE FROM requirement WHERE id = %s", (rid,))
        assert c.execute("SELECT count(*) FROM case_set_audit").fetchone() == (0,)


def test_0030_test_verisi_gecmisi_silinemez_ve_engel_turu(db: Db) -> None:
    """013 §9: tp_app test_verisi'ni silemez; sürüm FK RESTRICT; `test_verisi` engel türü."""
    kid = uuid.uuid4()
    with _app(db) as c:
        c.execute(
            "INSERT INTO test_verisi (id, anahtar, deger, guncelleyen) "
            "VALUES (%s, 'a.b', 'x', 't')",
            (kid,),
        )
        c.execute(
            "INSERT INTO test_verisi_surum (test_verisi_id, surum, islem, deger, gizli, "
            "degistiren) VALUES (%s, 1, 'olustur', 'x', false, 't')",
            (kid,),
        )
        c.execute("UPDATE test_verisi SET silindi = true WHERE id = %s", (kid,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("DELETE FROM test_verisi WHERE id = %s", (kid,))
    with psycopg.connect(db.owner_url.replace("+psycopg", ""), autocommit=True) as c:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute("DELETE FROM test_verisi WHERE id = %s", (kid,))
        tanim = c.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'script_codegen_engel_ck'"
        ).fetchone()[0]
    assert "'test_verisi'" in tanim and "'unsourced_value'" in tanim
