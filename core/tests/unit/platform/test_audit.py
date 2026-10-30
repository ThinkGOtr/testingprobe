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
from tp_core.audit.recorder import AI_CALL_COLUMNS

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
        c.execute("INSERT INTO tool_call (kanal, arac) VALUES ('agent', 'browser_evaluate')")
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
    assert seed.seed() == 5
    assert seed.seed() == 0
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM app_user")).scalar_one() == 5
        ozetler = c.execute(
            text("SELECT ozet FROM audit_event WHERE eylem = 'seed.applied' ORDER BY id")
        ).scalars()
        assert list(ozetler) == [{"yeni": 5}, {"yeni": 0}]
        sonuc = verify_chain(c)
    assert sonuc.ok and sonuc.count == 2
