"""Migrasyon 0002/0003: model ↔ şema eşitliği, yetkiler, append-only, zincir backfill, downgrade."""

from __future__ import annotations

import json
import re
import uuid

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, create_engine, text

from tp_core.audit import GENESIS_HASH, append_audit, chain_hash, chain_tip, verify_chain
from tp_core.audit.canonical import iso_utc
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


def _ev_pid(conn: Connection) -> str:
    """0045'in mevcut veriyi damgaladığı proje (`tp_proje` env kaydı; şablon `TP_HOME_PROJECT`'e
    göre `'varsayilan'` ya da geliştiricinin değeri)."""
    return conn.execute(
        text("SELECT pid FROM tp_proje WHERE kaynak = 'env' ORDER BY olusturma LIMIT 1")
    ).scalar_one()


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
            "INSERT INTO ai_call (project_id, amac, saglayici, model, mod) "
            "VALUES ('p', 't', 'replay', 'm', 'replay')"
        )
        c.execute(
            "INSERT INTO tool_call (project_id, kanal, arac) "
            "VALUES ('p', 'agent', 'browser_snapshot')"
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
            c.execute(f"DELETE FROM {tablo}")
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
            c.execute(f"TRUNCATE {tablo}")


def test_tp_app_diger_tablolarda_tam_dml(db: Db) -> None:
    rid = uuid.uuid4()
    with _app(db) as c:
        c.execute(
            "INSERT INTO requirement (id, project_id, kaynak, baslik, kaynak_hash) "
            "VALUES (%s, 'p', 'free_text', 'b', 'h')",
            (rid,),
        )
        c.execute("UPDATE requirement SET baslik = 'c' WHERE id = %s", (rid,))
        c.execute(
            "INSERT INTO pull_request (project_id, number, branch, baslik, head_sha, acan) "
            "VALUES ('p', 1, 'b','t','s','bot')"
        )
        c.execute("INSERT INTO review (project_id, nesne_turu, nesne_id, harici_onaylayan, kanal, "
                  "karar, onaylanan_hash) VALUES ('p', 'requirement', %s, 'po@sim', 'jira', "
                  "'po_approve', 'h')", (rid,))  # fmt: skip
        c.execute("DELETE FROM requirement WHERE id = %s", (rid,))


# 0045 öncesi şema (proje sütunu yok) ve head (proje kapsamlı) için.
_REVIEW_INSERT_ESKI = (
    "INSERT INTO review (nesne_turu, nesne_id, harici_onaylayan, kanal, karar, onaylanan_hash) "
    "VALUES ('requirement', gen_random_uuid(), 'po@firma', 'jira', 'reject', 'h')"
)
_REVIEW_INSERT = _REVIEW_INSERT_ESKI.replace("INTO review (", "INTO review (project_id, ").replace(
    "VALUES (", "VALUES ('p', "
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
        c.execute(
            "INSERT INTO run (project_id, kaynak, tetik, sonuc) "
            "VALUES ('p', 'github', 'manual', 'passed')"
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO run (project_id, kaynak, tetik, sonuc) "
                "VALUES ('p', 'github', 'elle', 'passed')"
            )


def test_job_zaman_asimi_bos_birakilabilir(db: Db) -> None:
    with _app(db) as c:
        c.execute("INSERT INTO job (tur) VALUES ('x')")
        assert c.execute("SELECT zaman_asimi_s FROM job").fetchone() == (None,)


def test_check_kisitlari_gecersiz_degeri_reddeder(db: Db) -> None:
    with _app(db) as c:
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO requirement (project_id, kaynak, baslik, kaynak_hash, durum) "
                "VALUES ('p', 'free_text', 'b', 'h', 'uydurma')"
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO requirement (project_id, kaynak, baslik, kaynak_hash) "
                "VALUES ('p', 'jira', 'b', 'h')"
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute(
                "INSERT INTO review (project_id, nesne_turu, nesne_id, harici_onaylayan, karar, "
                "onaylanan_hash) VALUES ('p', 'test_case', gen_random_uuid(), 'x', 'reject', 'h')"
            )


def test_audit_hash_zorunlu(db: Db) -> None:
    # Zinciri atlayan ham INSERT reddedilir: tüm yazıcılar append_audit'ten geçmek zorunda.
    with _app(db) as c, pytest.raises(psycopg.errors.NotNullViolation):
        c.execute("INSERT INTO audit_event (project_id, aktor, eylem) VALUES ('p', 'x', 'y')")


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
            # 0045: eski tek zincir varsayılan projenin zinciri olarak aynen geçerli.
            sonuc = verify_chain(conn, _ev_pid(conn))
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
            pid = c.execute("SELECT project_id FROM requirement WHERE id = %s", (rid,)).fetchone()
            with pytest.raises(psycopg.errors.NotNullViolation, match='"id"'):
                c.execute(
                    "INSERT INTO test_case (project_id, requirement_id, sira_no, icerik, "
                    "icerik_hash) VALUES (%s, %s, 2, '{}', 'x')",
                    (pid[0], rid),
                )
            with pytest.raises(psycopg.errors.UniqueViolation, match="test_case_sira_uq"):
                c.execute(
                    "INSERT INTO test_case (id, project_id, requirement_id, sira_no, icerik, "
                    "icerik_hash) VALUES (gen_random_uuid(), %s, %s, 1, '{}', 'x')",
                    (pid[0], rid),
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
            c.execute(_REVIEW_INSERT_ESKI.replace("'requirement'", "'test_case'").replace(
                "'reject'", "'reopen'"))  # fmt: skip
        run_alembic(owner, "0007", "downgrade")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT count(*) FROM review WHERE karar = 'reopen'").fetchone() == (
                1,
            )
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute(_REVIEW_INSERT_ESKI.replace("'reject'", "'reopen'"))
        run_alembic(owner, "head")  # yeniden yükseltilebilir
        with psycopg.connect(dsn, autocommit=True) as c:
            pid = c.execute("SELECT DISTINCT project_id FROM review").fetchone()[0]
            c.execute(_REVIEW_INSERT.replace("'reject'", "'reopen'").replace("'p'", f"'{pid}'"))
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
            "INSERT INTO requirement (id, project_id, kaynak, baslik, kaynak_hash) "
            "VALUES (%s, 'p', 'free_text', 'b', 'h')",
            (rid,),
        )
        ekle = (
            "INSERT INTO case_set_audit (project_id, requirement_id, set_hash, durum, karar) "
            "VALUES ('p', %s, 'h', %s, %s)"
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
            "INSERT INTO test_verisi (id, project_id, anahtar, deger, guncelleyen) "
            "VALUES (%s, 'p', 'a.b', 'x', 't')",
            (kid,),
        )
        c.execute(
            "INSERT INTO test_verisi_surum (project_id, test_verisi_id, surum, islem, deger, "
            "gizli, degistiren) VALUES ('p', %s, 1, 'olustur', 'x', false, 't')",
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


def test_0043_oturum_org_proje_downgrade_veriyi_korur(pg: PgServer) -> None:
    """Config R1 geri dönüşü: 0043 (oturum.org_id / project_id) dolu satırla geri alınır, oturum
    satırları kalır (yalnız iki sütun düşer) ve yeniden yükseltmede sütunlar NULL gelir."""
    ad = pg.create_empty_db()
    owner = pg.url("tp_owner", ad)
    dsn = owner.replace("+psycopg", "")

    def kolonlar(c: psycopg.Connection) -> set[str]:
        return {
            r[0]
            for r in c.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'oturum'"
            )
        }

    try:
        run_alembic(owner, "0043")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert {"org_id", "project_id"} <= kolonlar(c)
            uid = c.execute(
                "INSERT INTO app_user (id, kullanici_adi, rol, parola_hash) "
                "VALUES (gen_random_uuid(), 'r1-geri', 'admin', 'x') RETURNING id"
            ).fetchone()[0]
            c.execute(
                "INSERT INTO oturum (id, user_id, son_kullanma, org_id, project_id) "
                "VALUES (gen_random_uuid(), %s, now() + interval '1 hour', 'o1', 'p1')",
                (uid,),
            )
        run_alembic(owner, "0042", "downgrade")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert not {"org_id", "project_id"} & kolonlar(c)
            assert c.execute("SELECT count(*) FROM oturum").fetchone() == (1,)
        run_alembic(owner, "head")  # yeniden yükseltilebilir
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT org_id, project_id FROM oturum").fetchone() == (None, None)
    finally:
        with pg.super_conn() as c:
            c.execute(f'DROP DATABASE IF EXISTS "{ad}" WITH (FORCE)')


# ------------------------------------------------- 0045 proje kapsamı (TP-COK-PROJE-PLANI §1.4)

EV = "bayi-pid"


def _eski_zincir(c: psycopg.Connection, n: int) -> str:
    """0045 öncesi şemada (proje sütunu yok) geçerli bir zincir yazar; uç hash'i döndürür."""
    prev = GENESIS_HASH
    for i in range(n):
        id_, zaman = c.execute(
            "SELECT nextval(pg_get_serial_sequence('audit_event', 'id')), now()"
        ).fetchone()
        ozet = {"i": i, "ad": "ş"}
        h = chain_hash(
            prev,
            {"id": id_, "zaman": iso_utc(zaman), "aktor": "a", "eylem": "e.x", "nesne": None,
             "ozet": ozet},
        )  # fmt: skip
        c.execute(
            "INSERT INTO audit_event (id, zaman, aktor, eylem, nesne, ozet, prev_hash, hash) "
            "VALUES (%s, %s, 'a', 'e.x', NULL, %s::jsonb, %s, %s)",
            (id_, zaman, json.dumps(ozet), prev, h),
        )
        prev = h
    return prev


def _yeni_bos_db(pg: PgServer, hedef: str) -> tuple[str, str, str]:
    ad = pg.create_empty_db()
    owner = pg.url("tp_owner", ad)
    run_alembic(owner, hedef)
    return ad, owner, owner.replace("+psycopg", "")


def _sil(pg: PgServer, ad: str) -> None:
    with pg.super_conn() as c:
        c.execute(f'DROP DATABASE IF EXISTS "{ad}" WITH (FORCE)')


def test_0045_mevcut_veri_ev_projesine_damgalanir_zincir_ve_satirlar_bozulmaz(
    pg: PgServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """K4: tüm satırlar TP_HOME_PROJECT ile damgalanır; hızlı varsayılan satırı yeniden yazmaz
    (xmin/ctid aynı → append-only tetikleyicisi çalışmadı), zincir ve uç hash aynen geçerli;
    sayaç tohumları; sütun varsayılanı kalmaz; tekillikler proje başına."""
    monkeypatch.setenv("TP_HOME_PROJECT", EV)
    ad, owner, dsn = _yeni_bos_db(pg, "0044")
    try:
        with psycopg.connect(dsn, autocommit=True) as c:
            uc = _eski_zincir(c, 3)
            rid = c.execute(
                "INSERT INTO requirement (kaynak, jira_key, baslik, kaynak_hash) "
                "VALUES ('jira', 'TPD-1', 'b', 'h') RETURNING id"
            ).fetchone()[0]
            c.execute(_REVIEW_INSERT_ESKI.replace("'reject'", "'po_approve'"))
            c.execute(
                "INSERT INTO ai_call (amac, saglayici, model, mod) "
                "VALUES ('t', 'replay', 'm', 'replay')"
            )
            c.execute(
                "INSERT INTO pull_request (branch, baslik, head_sha, acan) VALUES "
                "('b1','t','s','bot'), ('b2','t','s','bot')"
            )
            for _ in range(3):
                c.execute("SELECT nextval('ajan_testi_talebi_no_seq')")
            c.execute("INSERT INTO asistan_durum (id, mod) VALUES (1, 'off')")
            c.execute(
                "INSERT INTO otomasyon_ayari (anahtar, deger, guncelleyen) VALUES ('k', '1', 'x')"
            )
            c.execute(
                "INSERT INTO job (tur, durum, idempotency_key) VALUES "
                "('noop', 'done', 'gece:2026-11-14'), ('noop', 'queued', NULL)"
            )
            once = {
                t: c.execute(
                    f"SELECT array_agg(xmin::text || ctid::text ORDER BY id) FROM {t}"
                ).fetchone()[0]
                for t in ("audit_event", "review", "ai_call")
            }
        run_alembic(owner, "head")
        with psycopg.connect(dsn, autocommit=True) as c:
            for t, deger in once.items():
                sonra = c.execute(
                    f"SELECT array_agg(xmin::text || ctid::text ORDER BY id) FROM {t}"
                ).fetchone()[0]
                assert sonra == deger, f"{t} satırları yeniden yazıldı"
            for t in ("audit_event", "review", "ai_call", "requirement", "pull_request",
                      "asistan_durum", "otomasyon_ayari", "job"):  # fmt: skip
                assert c.execute(f"SELECT array_agg(DISTINCT project_id) FROM {t}").fetchone() == (
                    [EV],
                ), t
            varsayilanli = c.execute(
                "SELECT table_name FROM information_schema.columns WHERE column_name = "
                "'project_id' AND column_default IS NOT NULL AND table_name <> 'asistan_hiz'"
            ).fetchall()
            assert varsayilanli == []
            tetik = c.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname LIKE '%append_only' "
                "AND tgenabled = 'O'"
            ).fetchone()
            assert tetik == (4,)
            assert dict(
                c.execute("SELECT ad, deger FROM proje_sayac WHERE project_id = %s", (EV,))
            ) == {"pr": 2, "talep": 3}
            assert c.execute("SELECT project_id, mod FROM asistan_durum").fetchall() == [
                (EV, "off")
            ]
            # tekillik proje başına
            c.execute(
                "INSERT INTO requirement (project_id, kaynak, jira_key, baslik, kaynak_hash) "
                "VALUES ('diger', 'jira', 'TPD-1', 'b', 'h')"
            )
            with pytest.raises(psycopg.errors.UniqueViolation):
                c.execute(
                    "INSERT INTO requirement (project_id, kaynak, jira_key, baslik, kaynak_hash)"
                    " VALUES (%s, 'jira', 'TPD-1', 'b', 'h')",
                    (EV,),
                )
            c.execute(
                "INSERT INTO pull_request (project_id, number, branch, baslik, head_sha, acan) "
                "VALUES ('diger', 1, 'b','t','s','bot')"
            )
            with pytest.raises(psycopg.errors.NotNullViolation):  # dizi varsayılanı kalktı
                c.execute(
                    "INSERT INTO pull_request (project_id, branch, baslik, head_sha, acan) "
                    "VALUES ('diger', 'b','t','s','bot')"
                )
            c.execute("UPDATE requirement SET baslik = 'x' WHERE id = %s", (rid,))
        eng = create_engine(owner)
        with eng.begin() as conn:
            sonuc = verify_chain(conn, EV)
            assert sonuc.ok and sonuc.count == 3 and sonuc.tip_hash == uc, sonuc
            assert chain_tip(conn, EV) == uc
            # yeni proje zinciri GENESIS'ten başlar; iki zincir bağımsız sürer
            append_audit(conn, "a", "e.y", project_id="diger")
            append_audit(conn, "a", "e.y", project_id=EV)
        with eng.connect() as conn:
            assert verify_chain(conn, EV).count == 4
            yeni = verify_chain(conn, "diger")
            assert yeni.ok and yeni.count == 1
        eng.dispose()
    finally:
        _sil(pg, ad)


def test_0045_downgrade_tek_projede_calisir_ve_yeniden_yukselir(
    pg: PgServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_HOME_PROJECT", EV)
    ad, owner, dsn = _yeni_bos_db(pg, "head")
    try:
        eng = create_engine(owner)
        with eng.begin() as conn:
            append_audit(conn, "a", "e.x", project_id=EV)
            append_audit(conn, "a", "e.x", project_id=EV)
        eng.dispose()
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute(
                "INSERT INTO pull_request (project_id, number, branch, baslik, head_sha, acan) "
                "VALUES (%s, 5, 'b','t','s','bot')",
                (EV,),
            )
            c.execute("INSERT INTO asistan_durum (project_id, mod) VALUES (%s, 'off')", (EV,))
            c.execute(
                "INSERT INTO job (project_id, tur) VALUES (NULL, 'noop'), (%s, 'noop')", (EV,)
            )
        run_alembic(owner, "0044", "downgrade")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE column_name = 'project_id' "
                "AND table_name NOT IN ('oturum', 'proje_sayac')"
            ).fetchone() == (0,)
            assert c.execute("SELECT count(*) FROM audit_event").fetchone() == (2,)
            # dizi geri geldi ve mevcut numaradan devam eder
            assert c.execute(
                "INSERT INTO pull_request (branch, baslik, head_sha, acan) "
                "VALUES ('b','t','s','bot') RETURNING number"
            ).fetchone() == (6,)
            assert c.execute("SELECT id, mod FROM asistan_durum").fetchall() == [(1, "off")]
        run_alembic(owner, "head")
        eng = create_engine(owner)
        with eng.connect() as conn:
            sonuc = verify_chain(conn, EV)
            assert sonuc.ok and sonuc.count == 2, sonuc
            assert (
                conn.execute(
                    text("SELECT deger FROM proje_sayac WHERE project_id = :p AND ad = 'pr'"),
                    {"p": EV},
                ).scalar_one()
                == 6
            )
        eng.dispose()
    finally:
        _sil(pg, ad)


def test_0045_downgrade_cok_projede_reddedilir(db: Db) -> None:
    with _app(db) as c:
        for pid in ("p1", "p2"):
            c.execute(
                "INSERT INTO requirement (project_id, kaynak, baslik, kaynak_hash) "
                "VALUES (%s, 'free_text', 'b', 'h')",
                (pid,),
            )
    with pytest.raises(RuntimeError, match="birden çok projenin"):
        run_alembic(db.owner_url, "0044", "downgrade")


def test_0045_home_kipinde_proje_yoksa_durur(pg: PgServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TP_HOME_PROJECT", raising=False)
    monkeypatch.setenv("CONFIG_SOURCE", "home")
    ad, owner, dsn = _yeni_bos_db(pg, "0044")
    try:
        with pytest.raises(RuntimeError, match="TP_HOME_PROJECT boş"):
            run_alembic(owner, "head")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0044",)
    finally:
        _sil(pg, ad)


def test_0045_job_idempotency_proje_basina_ve_kurulum_ici_tekil(db: Db) -> None:
    with _app(db) as c:
        ekle = (
            "INSERT INTO job (project_id, tur, idempotency_key) VALUES (%s, 'noop', 'k') "
            "ON CONFLICT (project_id, idempotency_key) WHERE idempotency_key IS NOT NULL "
            "DO NOTHING RETURNING id"
        )
        assert c.execute(ekle, ("a",)).fetchone() is not None
        assert c.execute(ekle, ("b",)).fetchone() is not None
        assert c.execute(ekle, ("a",)).fetchone() is None
        assert c.execute(ekle, (None,)).fetchone() is not None
        assert c.execute(ekle, (None,)).fetchone() is None  # NULLS NOT DISTINCT
