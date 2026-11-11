"""`/demo/status` Faz 5 ekleri: core-worker'ın model kipi (anahtar değeri asla) ve değerlendirme.

core-api model ayarlarını görmez; worker açılışta denetime yazar, durum ucu son kaydı okur.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tp_core.features.demo import jobs, service

SAHTE_ANAHTAR = "sk-ant-test-gizli-deger-0000"
SAHTE_ALAN = "wrkspc_gizli_0000"


def _kayitlar(engine: Engine) -> list[dict]:
    with engine.connect() as c:
        return [
            r[0]
            for r in c.execute(
                text("SELECT ozet FROM audit_event WHERE eylem = :e ORDER BY id"),
                {"e": service.MODEL_DURUMU_EYLEM},
            )
        ]


def test_worker_acilisi_model_kipini_yazar_sir_yazmaz(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TP_MODEL_MODE", "replay")
    monkeypatch.setenv("TP_REPLAY_STRICT", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", SAHTE_ANAHTAR)
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", SAHTE_ALAN)
    with Session(engine) as s:
        assert service.model_durumu_oku(s) is None  # kayıt yok → bilinmiyor
    with engine.begin() as conn:
        jobs.on_worker_start(conn)
    with engine.begin() as conn:
        jobs.on_worker_start(conn)  # değişmedi → yeni satır yok
    kayit = _kayitlar(engine)
    assert len(kayit) == 1
    assert kayit[0] == {
        "ayar": "replay",
        "mod": "replay",
        "replay_strict": True,
        "anahtar_var": True,
        "calisma_alani_var": True,
        "saglayici": "anthropic",
    }
    dokum = json.dumps(kayit)
    assert SAHTE_ANAHTAR not in dokum and SAHTE_ALAN not in dokum

    monkeypatch.setenv("TP_REPLAY_STRICT", "0")
    with engine.begin() as conn:
        jobs.on_worker_start(conn)
    assert [k["replay_strict"] for k in _kayitlar(engine)] == [True, False]
    with Session(engine) as s:
        m = service.model_durumu_oku(s)
    assert m is not None and m["replay_strict"] is False and m["mod"] == "replay"
    assert m["aciklama"].startswith("core-worker açılışında bildirdi")


def test_degerlendirme_durumu_durust_etiket() -> None:
    d = service.degerlendirme_durumu()
    assert isinstance(d, list) and d
    paketler = {x["paket"]: x for x in d}
    assert "triage" in paketler
    for x in d:
        durumlar = ("pending", "evaluated", "waived", "stale", "icerik_degisti", "missing")
        assert x["durum"] in durumlar
        if x["durum"] == "pending":
            assert x["etiket"] == "canlı değerlendirme bekliyor"
