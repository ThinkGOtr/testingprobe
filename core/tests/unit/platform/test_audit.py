"""Denetim zinciri (append_audit / verify_chain), CallRecorder ve seed — gerçek Postgres."""

from __future__ import annotations

import threading
import uuid
from decimal import Decimal

import psycopg
import pytest
from sqlalchemy import Engine, text

from tp_core import ports, seed
from tp_core.audit import (
    GENESIS_HASH,
    PgAuditLog,
    PgCallRecorder,
    append_audit,
    chain_tip,
    row_anchor,
    verify_call_anchors,
    verify_chain,
)
from tp_core.audit.recorder import AI_CALL_COLUMNS, record_tool_call
from tp_core.proje import KURULUM, proje_icinde

from .conftest import Db


def _dogrula(engine: Engine):
    with engine.connect() as c:
        return verify_chain(c)


def test_bos_zincir_gecerli(engine: Engine) -> None:
    sonuc = _dogrula(engine)
    assert (sonuc.ok, sonuc.count, sonuc.tip_hash) == (True, 0, GENESIS_HASH)


def test_ekleme_zinciri_kurar(engine: Engine) -> None:
    log = PgAuditLog(engine)
    assert isinstance(log, ports.AuditLog)
    i1 = log.append("analist", "case.approved", "test_case:1", {"hash": "abc"})
    i2 = log.append("system", "x.y", None, {"büyük": 1e20, "ondalık": 0.1, "ç": ["ğ", None]})
    assert i2 > i1
    with engine.connect() as c:
        rows = c.execute(text("SELECT id, prev_hash, hash FROM audit_event ORDER BY id")).all()
        assert rows[0].prev_hash == GENESIS_HASH
        assert rows[1].prev_hash == rows[0].hash
        assert chain_tip(c) == rows[1].hash
    sonuc = _dogrula(engine)
    assert sonuc.ok and sonuc.count == 2


def test_islem_geri_alinirsa_zincir_bozulmaz(engine: Engine) -> None:
    PgAuditLog(engine).append("a", "bir.iki", None, {})
    with pytest.raises(RuntimeError), engine.begin() as c:
        append_audit(c, "a", "geri.alinan", None, {})
        raise RuntimeError("iptal")
    PgAuditLog(engine).append("a", "uc.dort", None, {})
    sonuc = _dogrula(engine)
    assert sonuc.ok and sonuc.count == 2


def test_eszamanli_yazicilar_catallanmaz(engine: Engine) -> None:
    log = PgAuditLog(engine)
    hatalar: list[BaseException] = []

    def yaz(n: int) -> None:
        try:
            for i in range(10):
                log.append(f"w{n}", "paralel.yazim", None, {"i": i})
        except BaseException as exc:
            hatalar.append(exc)

    iplikler = [threading.Thread(target=yaz, args=(n,)) for n in range(6)]
    for t in iplikler:
        t.start()
    for t in iplikler:
        t.join()
    assert hatalar == []
    sonuc = _dogrula(engine)
    assert sonuc.ok and sonuc.count == 60


def _sahip(db: Db) -> psycopg.Connection:
    # Süper kullanıcı tetikleyicileri devre dışı bırakarak kurcalamayı taklit eder.
    c = db.srv.super_conn(db.name)
    c.execute("SET session_replication_role = replica")
    return c


def test_icerik_kurcalama_tespit_edilir(db: Db, engine: Engine) -> None:
    log = PgAuditLog(engine)
    for i in range(3):
        log.append("analist", "case.approved", f"test_case:{i}", {"i": i})
    with _sahip(db) as c:
        hedef = c.execute("SELECT id FROM audit_event ORDER BY id OFFSET 1 LIMIT 1").fetchone()[0]
        c.execute("UPDATE audit_event SET aktor = 'saldirgan' WHERE id = %s", (hedef,))
    sonuc = _dogrula(engine)
    assert not sonuc.ok
    assert sonuc.broken_at == hedef
    assert sonuc.count == 1
    assert "hash" in (sonuc.reason or "")


def test_satir_silme_tespit_edilir(db: Db, engine: Engine) -> None:
    log = PgAuditLog(engine)
    for i in range(3):
        log.append("analist", "x.y", None, {"i": i})
    with _sahip(db) as c:
        c.execute("DELETE FROM audit_event WHERE id = (SELECT min(id) + 1 FROM audit_event)")
    sonuc = _dogrula(engine)
    assert not sonuc.ok and "prev_hash" in (sonuc.reason or "")


def test_gecersiz_aktor_reddedilir(engine: Engine) -> None:
    with pytest.raises(ValueError), engine.begin() as c:
        append_audit(c, "", "x.y")
    with pytest.raises(ValueError), engine.begin() as c:
        append_audit(c, "a" * 201, "x.y")


# ------------------------------------------------------------------ CallRecorder


def test_ai_call_kaydi_ve_es_anlamlilar(engine: Engine) -> None:
    rec = PgCallRecorder(engine)
    assert isinstance(rec, ports.CallRecorder)
    wf = uuid.uuid4()
    cid = rec.record_ai_call(
        {
            "purpose": "generate_cases",
            "provider": "replay",
            "model": "claude-sonnet",
            "mode": "replay",
            "bundle_hash": "b" * 64,
            "input": {"messages": [{"role": "user", "content": "x"}]},
            "output": {"cases": []},
            "schema_valid": True,
            "input_tokens": 10,
            "output_tokens": 5,
            "cost_usd": 0.0123,
            "workflow_id": wf,
        }
    )
    with engine.connect() as c:
        r = c.execute(text("SELECT * FROM ai_call WHERE id = :i"), {"i": cid}).one()
    assert (r.amac, r.saglayici, r.mod, r.girdi_token, r.cikti_token) == (
        "generate_cases", "replay", "replay", 10, 5
    )  # fmt: skip
    assert r.maliyet == Decimal("0.012300")
    assert r.workflow_id == wf
    assert r.cikti == {"cases": []}


def test_ai_call_ayni_id_idempotent(engine: Engine) -> None:
    rec = PgCallRecorder(engine)
    cid = uuid.uuid4()
    satir = {"id": cid, "amac": "a", "saglayici": "anthropic", "model": "m", "mod": "live"}
    assert rec.record_ai_call(satir) == cid
    assert rec.record_ai_call({**satir, "maliyet": 5}) == cid
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*), max(maliyet) FROM ai_call")).one() == (1, 0)


@pytest.mark.parametrize(
    ("satir", "mesaj"),
    [
        ({"amac": "a", "saglayici": "s", "model": "m"}, "zorunlu"),
        ({"amac": "a", "saglayici": "s", "model": "m", "mod": "live", "uydurma": 1}, "bilinmeyen"),
        ({"amac": "a", "purpose": "b", "saglayici": "s", "model": "m", "mod": "live"}, "iki kez"),
    ],
)
def test_ai_call_gecersiz_satir(engine: Engine, satir: dict, mesaj: str) -> None:
    with pytest.raises(ValueError, match=mesaj):
        PgCallRecorder(engine).record_ai_call(satir)


def test_ai_call_gecersiz_mod_db_tarafinda_reddedilir(engine: Engine) -> None:
    with pytest.raises(Exception, match="ai_call_mod_ck"):
        PgCallRecorder(engine).record_ai_call(
            {"amac": "a", "saglayici": "s", "model": "m", "mod": "canli"}
        )


def test_tool_call_kaydi(engine: Engine) -> None:
    rec = PgCallRecorder(engine)
    ai = rec.record_ai_call({"amac": "a", "saglayici": "s", "model": "m", "mod": "replay"})
    tid = rec.record_tool_call(
        {
            "call_id": ai,
            "channel": "agent",
            "tool": "browser_click",
            "args": {"ref": "e12"},
            "result_summary": "ok",
            "allowed": False,
        }
    )
    with engine.connect() as c:
        r = c.execute(text("SELECT * FROM tool_call WHERE id = :i"), {"i": tid}).one()
    assert (r.ai_call_id, r.kanal, r.arac, r.izin_verildi) == (ai, "agent", "browser_click", False)
    assert r.arguman_ozeti == {"ref": "e12"}


def test_ai_ve_arac_cagrilari_zincire_sabitlenir(engine: Engine) -> None:
    """Her yeni ai_call/tool_call satırı aynı işlemde denetim zincirine bağlanır (VIII); aynı
    id ile yeniden yazım ikinci bir denetim satırı üretmez."""
    from tp_core.audit.canonical import content_hash

    rec = PgCallRecorder(engine)
    cid = uuid.uuid4()
    satir = {"id": cid, "amac": "generate_cases", "saglayici": "replay", "model": "m",
             "mod": "replay", "bundle_hash": "b" * 64, "cikti": {"cases": []}}  # fmt: skip
    rec.record_ai_call(satir)
    rec.record_ai_call(satir)  # idempotent
    tid = rec.record_tool_call({"ai_call_id": cid, "kanal": "agent", "arac": "browser_click"})
    with engine.connect() as c:
        olaylar = c.execute(
            text("SELECT aktor, eylem, nesne, ozet FROM audit_event ORDER BY id")
        ).all()
        assert verify_chain(c).ok
    assert [(o.aktor, o.eylem, o.nesne) for o in olaylar] == [
        ("system", "ai_call.recorded", f"ai_call:{cid}"),
        ("system", "tool_call.recorded", f"tool_call:{tid}"),
    ]
    ozet = olaylar[0].ozet
    assert (ozet["mod"], ozet["model"], ozet["amac"], ozet["bundle_hash"]) == (
        "replay", "m", "generate_cases", "b" * 64
    )  # fmt: skip
    # Çapa, SAKLANAN satırdan yeniden hesaplanabilir: tüm kolonlar (NULL dahil), jsonb
    # ayrıştırılmış, numeric metin, uuid metin.
    assert ozet["capa_surumu"] == 2
    with engine.connect() as c:
        kolonlar = ", ".join(AI_CALL_COLUMNS)
        saklanan = (
            c.execute(text(f"SELECT {kolonlar} FROM ai_call WHERE id = :i"), {"i": cid})
            .mappings()
            .one()
        )
        assert ozet["satir_sha256"] == row_anchor("ai_call", saklanan)
        # Bağımsız yeniden hesap: okunan satır, uuid/Decimal metne çevrilerek kanonik JSON;
        # sonradan eklenen `ek` (0005) NULL iken çapaya girmez.
        el_ile = {
            k: str(v) if isinstance(v, uuid.UUID | Decimal) else v
            for k, v in saklanan.items()
            if not (k == "ek" and v is None)
        }
        assert el_ile["cikti"] == {"cases": []} and el_ile["id"] == str(cid)
        assert ozet["satir_sha256"] == content_hash(el_ile)
        capalar = verify_call_anchors(c)
    assert capalar.ok and capalar.checked == 2 and capalar.broken == []
    assert olaylar[1].ozet["ai_call_id"] == str(cid)


def _ai_call_yaz(engine: Engine, **ek: object) -> uuid.UUID:
    satir = {"amac": "generate_cases", "saglayici": "anthropic", "model": "claude",
             "mod": "live", "maliyet": 0.0123, "girdi_token": 10,
             "maskeli_girdi": {"z": 1, "a": [1.5, {"y": "ş", "b": None}], "m": 1e20},
             "cikti": {"cases": [{"title": "Kampanya", "steps": []}]}} | ek  # fmt: skip
    return PgCallRecorder(engine).record_ai_call(satir)


def test_capa_jsonb_anahtar_sirasi_ve_numeric_olcegine_dayanikli(engine: Engine) -> None:
    """jsonb anahtarları yeniden sıralar, numeric Decimal('0.012300') döner: çapa yine tutar."""
    cid = _ai_call_yaz(engine)
    with engine.connect() as c:
        maliyet = c.execute(text("SELECT maliyet FROM ai_call WHERE id = :i"), {"i": cid})
        assert isinstance(maliyet.scalar_one(), Decimal)
        sonuc = verify_call_anchors(c)
    assert sonuc.ok and sonuc.checked == 1


@pytest.mark.parametrize(
    ("sql", "neden"),
    [
        ("UPDATE ai_call SET cikti = '{\"cases\": []}'::jsonb WHERE id = %s", "değiştirilmiş"),
        ("UPDATE ai_call SET maliyet = 0 WHERE id = %s", "değiştirilmiş"),
        ("UPDATE ai_call SET mod = 'replay' WHERE id = %s", "değiştirilmiş"),
        ("DELETE FROM ai_call WHERE id = %s", "silinmiş"),
    ],
)
def test_kurcalanan_ai_call_satiri_tespit_edilir(
    db: Db, engine: Engine, sql: str, neden: str
) -> None:
    cid = _ai_call_yaz(engine)
    diger = _ai_call_yaz(engine)
    with _sahip(db) as c:
        c.execute(sql, (cid,))
    with engine.connect() as c:
        sonuc = verify_call_anchors(c)
        assert verify_chain(c).ok  # zincirin kendisi sağlam; kurcalama çapadan görülür
    assert not sonuc.ok
    assert [b["nesne"] for b in sonuc.broken] == [f"ai_call:{cid}"]
    assert neden in sonuc.broken[0]["reason"]
    assert f"ai_call:{diger}" not in {b["nesne"] for b in sonuc.broken}


def test_kurcalanan_tool_call_ve_capasiz_satir_tespit_edilir(db: Db, engine: Engine) -> None:
    rec = PgCallRecorder(engine)
    tid = rec.record_tool_call({"kanal": "agent", "arac": "browser_click", "izin_verildi": True})
    with _sahip(db) as c:
        c.execute("UPDATE tool_call SET izin_verildi = false WHERE id = %s", (tid,))
        # Kaydediciyi atlayan (zincire çapalanmamış) satır.
        c.execute(
            "INSERT INTO tool_call (project_id, kanal, arac) "
            "VALUES ('_kurulum', 'agent', 'browser_evaluate')"
        )
    with engine.connect() as c:
        sonuc = verify_call_anchors(c)
    assert not sonuc.ok and sonuc.sabitsiz == 1
    nedenler = {b["nesne"].split(":")[0]: b["reason"] for b in sonuc.broken}
    assert len(sonuc.broken) == 2 and set(nedenler) == {"tool_call"}
    assert any(b["nesne"] == f"tool_call:{tid}" for b in sonuc.broken)


def test_ek_kolonu_saklanir_ve_capaya_girer(db: Db, engine: Engine) -> None:
    """0005: `ek` jsonb saklanır; değeri değiştirmek ya da NULL'lamak çapayı bozar."""
    cid = _ai_call_yaz(engine, ek={"replay_kokeni": "golden_promoted"})
    bos = _ai_call_yaz(engine)
    with engine.connect() as c:
        saklanan = c.execute(text("SELECT ek FROM ai_call WHERE id = :i"), {"i": cid})
        assert saklanan.scalar_one() == {"replay_kokeni": "golden_promoted"}
        assert verify_call_anchors(c).ok
    with _sahip(db) as c:
        c.execute("UPDATE ai_call SET ek = NULL WHERE id = %s", (cid,))
        c.execute(
            'UPDATE ai_call SET ek = \'{"replay_kokeni": "recorded"}\'::jsonb WHERE id = %s',
            (bos,),
        )
    with engine.connect() as c:
        sonuc = verify_call_anchors(c)
    assert not sonuc.ok
    assert {b["nesne"] for b in sonuc.broken} == {f"ai_call:{cid}", f"ai_call:{bos}"}


def test_ek_kolonundan_onceki_capa_gecerli_kalir(engine: Engine) -> None:
    """0005'ten önce `ek` olmadan hesaplanan capa_surumu=2 çapası (NULL ek) hâlâ doğrulanır."""
    from tp_core.audit.canonical import content_hash
    from tp_core.audit.recorder import _kanonik

    cid = _ai_call_yaz(engine)
    with engine.connect() as c:
        satir = c.execute(text("SELECT * FROM ai_call WHERE id = :i"), {"i": cid}).mappings().one()
    eski_kolonlar = {k: t for k, t in AI_CALL_COLUMNS.items() if k != "ek"}
    eski_capa = content_hash({k: _kanonik(t, satir[k]) for k, t in eski_kolonlar.items()})
    assert row_anchor("ai_call", satir) == eski_capa


def test_eski_surum_capa_sayilir_ama_dogrulanamaz(engine: Engine) -> None:
    cid = _ai_call_yaz(engine)
    with engine.begin() as c:
        # 0.x kaydedicisinin yazdığı gibi sürümsüz çapa (yalnızca sayılır).
        nesne = f"ai_call:{uuid.UUID(int=1)}"
        append_audit(c, "system", "ai_call.recorded", nesne, {"satir_sha256": "x"})
        sonuc = verify_call_anchors(c)
    assert sonuc.ok and sonuc.eski == 1 and sonuc.checked == 1, cid


def test_ai_call_yazilamazsa_denetim_satiri_da_yazilmaz(engine: Engine) -> None:
    with pytest.raises(Exception, match="ai_call_mod_ck"):
        PgCallRecorder(engine).record_ai_call(
            {"amac": "a", "saglayici": "s", "model": "m", "mod": "canli"}
        )
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM audit_event")).scalar_one() == 0


# ------------------------------------------------------------------------- seed


def test_seed_idempotent_ve_zincirli(engine: Engine) -> None:
    # Rol başına bir demo hesabı (specs/012-rol-yetki §3: 8 rol).
    assert seed.seed() == 8
    assert seed.seed() == 0
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM app_user")).scalar_one() == 8
        ozetler = c.execute(
            text("SELECT ozet FROM audit_event WHERE eylem = 'seed.applied' ORDER BY id")
        ).scalars()
        assert list(ozetler) == [{"yeni": 8}, {"yeni": 0}]
        sonuc = verify_chain(c)
    assert sonuc.ok and sonuc.count == 2


# ------------------------------------------- proje başına zincir (TP-COK-PROJE-PLANI §1.3, Ş1)


def test_zincir_proje_basina_genesisten_baslar_ve_bagimsiz_dogrulanir(
    engine: Engine, iki_proje: tuple[str, str]
) -> None:
    a, b = iki_proje
    with proje_icinde(a, kaynak="test"):
        PgAuditLog(engine).append("x", "a.bir", None, {})
        PgAuditLog(engine).append("x", "a.iki", None, {})
    with proje_icinde(b, kaynak="test"):
        PgAuditLog(engine).append("x", "b.bir", None, {})
    PgAuditLog(engine).append("x", "kurulum.bir", None, {})  # bağlamsız → '_kurulum'
    with engine.connect() as c:
        satirlar = c.execute(
            text("SELECT project_id, eylem, prev_hash, hash FROM audit_event ORDER BY id")
        ).all()
        assert [(r.project_id, r.eylem) for r in satirlar] == [
            (a, "a.bir"), (a, "a.iki"), (b, "b.bir"), (KURULUM, "kurulum.bir"),
        ]  # fmt: skip
        # her zincir kendi GENESIS'iyle başlar (tekillik (project_id, prev_hash))
        assert [r.prev_hash for r in satirlar].count(GENESIS_HASH) == 3
        assert satirlar[1].prev_hash == satirlar[0].hash
        for pid, n, uc in ((a, 2, satirlar[1].hash), (b, 1, satirlar[2].hash),
                           (KURULUM, 1, satirlar[3].hash)):  # fmt: skip
            sonuc = verify_chain(c, pid)
            assert (sonuc.ok, sonuc.count, sonuc.tip_hash) == (True, n, uc)
            assert chain_tip(c, pid) == uc
        with proje_icinde(a, kaynak="test"):
            assert chain_tip(c) == satirlar[1].hash  # varsayılan: bağlamdaki proje
            assert verify_chain(c).count == 2
        assert chain_tip(c, "bos-proje") == GENESIS_HASH


def test_baska_projenin_zinciri_kilidi_beklemez(db: Db, engine: Engine) -> None:
    """Kilit `(AUDIT_LOCK_KEY, hashtext(pid))`: A'nın açık işlemi B'yi bekletmez, A'yı bekletir."""
    with engine.connect() as c1:
        tx = c1.begin()
        append_audit(c1, "x", "a.bir", project_id="a")
        with engine.connect() as c2:
            c2.execute(text("SET lock_timeout = '1s'"))
            c2.commit()
            with c2.begin():
                append_audit(c2, "x", "b.bir", project_id="b")
            with pytest.raises(Exception, match="lock timeout"), c2.begin():
                append_audit(c2, "x", "a.iki", project_id="a")
        tx.commit()
    with engine.connect() as c:
        assert verify_chain(c, "a").count == 1 and verify_chain(c, "b").count == 1


def test_audit_on_commit_cagri_anindaki_projeye_yazar(engine: Engine) -> None:
    from sqlalchemy.orm import Session

    from tp_core.audit import audit_on_commit, pending_audit

    with Session(engine) as s:
        with proje_icinde("a", kaynak="test"):
            audit_on_commit(s, "x", "a.olay", "n:1", {"k": 1})
        audit_on_commit(s, "x", "acik.olay", project_id="b")
        assert pending_audit(s) == [
            ("x", "a.olay", "n:1", {"k": 1}),
            ("x", "acik.olay", None, None),
        ]
        with proje_icinde("c", kaynak="test"):  # commit anındaki bağlam kaydı taşımaz
            s.commit()
    with engine.connect() as c:
        assert c.execute(text("SELECT project_id, eylem FROM audit_event ORDER BY id")).all() == [
            ("a", "a.olay"),
            ("b", "acik.olay"),
        ]


def test_cagri_kaydi_ve_capasi_ayni_projede_dogrulanir(db: Db, engine: Engine) -> None:
    rec = PgCallRecorder(engine)
    with proje_icinde("a", kaynak="test"):
        aid = rec.record_ai_call(
            {"amac": "t", "saglayici": "replay", "model": "m", "mod": "replay"}
        )
        rec.record_tool_call({"kanal": "agent", "arac": "browser_click"})
    with engine.begin() as c:
        record_tool_call(c, {"kanal": "ide", "arac": "x"}, project_id="b")
    with engine.connect() as c:
        assert (
            c.execute(text("SELECT project_id FROM ai_call WHERE id = :i"), {"i": aid}).scalar_one()
            == "a"
        )
        sa_, sb = verify_call_anchors(c, "a"), verify_call_anchors(c, "b")
        assert (sa_.ok, sa_.checked, sa_.sabitsiz) == (True, 2, 0)
        assert (sb.ok, sb.checked) == (True, 1)
        assert verify_chain(c, "a").count == 2 and verify_chain(c, "b").count == 1
    # Başka projeye "taşınmış" satır (çapası A zincirinde, satırı B'de): A'da silinmiş, B'de
    # çapasız görünür.
    with _sahip(db) as c:
        c.execute("UPDATE tool_call SET project_id = 'b' WHERE project_id = 'a'")
    with engine.connect() as c:
        sa_, sb = verify_call_anchors(c, "a"), verify_call_anchors(c, "b")
        assert not sa_.ok and "silinmiş" in sa_.broken[0]["reason"]
        assert not sb.ok and sb.sabitsiz == 1
