"""Worker şeritleri: uzun işler (CI koşusu, onarım yerel kontrolü) ayrı yuvada koşar.

Regresyon: tek yuvalı worker'da `ci.run` 17:28:03–17:30:01 arasında koşarken
`requirements.po_poll` ve `triage.sweep` bekledi; jira-sim'e eklenen PO onayı ancak koşu
bitince alındı ve Demo-A e2e'nin 90 sn'lik "Case üret" beklemesi zaman aşımına uğradı.
"""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from tp_core import worker
from tp_core.config import get_settings
from tp_core.workflow import jobs
from tp_core.workflow.jobs import (
    UZUN_SERIT,
    HandlerSpec,
    claim,
    enqueue,
    job_handler,
    process_one,
    uzun_turler,
)


@pytest.fixture(autouse=True)
def _canlilik_dosyasi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_WORKER_LIVENESS_FILE", str(tmp_path / "canli"))
    monkeypatch.setenv("TP_WORKER_STATE_FILE", str(tmp_path / "surec"))


def _durum(engine: Engine, job_id: uuid.UUID) -> str:
    with engine.connect() as c:
        return c.execute(text("SELECT durum FROM job WHERE id = :i"), {"i": job_id}).scalar_one()


def _bekle(kosul, sure: float = 10.0) -> bool:
    son = time.monotonic() + sure
    while time.monotonic() < son:
        if kosul():
            return True
        time.sleep(0.02)
    return False


# ------------------------------------------------------------------ sahiplenme süzgeçleri


def test_claim_haric_ve_turler_suzgeci(engine: Engine) -> None:
    reg: dict[str, HandlerSpec] = {}
    for t in ("s.uzun", "s.kisa"):
        job_handler(t, registry=reg)(lambda _c: None)
    with engine.begin() as c:
        uzun_id = enqueue(c, "s.uzun", registry=reg)  # önce eklenen (en eski) uzun iş
        kisa_id = enqueue(c, "s.kisa", registry=reg)
    with engine.begin() as c:
        alinan = claim(c, "w", haric=["s.uzun"])
    assert alinan is not None and alinan.id == kisa_id
    with engine.begin() as c:
        assert claim(c, "w", haric=["s.uzun"]) is None  # yalnızca uzun iş kaldı
        alinan = claim(c, "w", ["s.uzun"])
    assert alinan is not None and alinan.id == uzun_id


def test_process_one_turler_disindakini_almaz(engine: Engine) -> None:
    reg: dict[str, HandlerSpec] = {}
    job_handler("s.genel", registry=reg)(lambda _c: None)
    with engine.begin() as c:
        jid = enqueue(c, "s.genel", registry=reg)
    assert process_one(engine, "w", reg, turler=["s.baska"]) is None
    assert _durum(engine, jid) == "queued"
    assert process_one(engine, "w", reg, haric=["s.baska"]).durum == "done"


# ------------------------------------------------------------------ şerit kaydı/yapılandırma


def test_uzun_turler_kayit_ve_ek() -> None:
    reg: dict[str, HandlerSpec] = {}
    job_handler("k.uzun", registry=reg, serit=UZUN_SERIT)(lambda _c: None)
    job_handler("k.kisa", registry=reg)(lambda _c: None)
    assert uzun_turler([" ek.tur ", ""], reg) == frozenset({"k.uzun", "ek.tur"})
    with pytest.raises(ValueError):
        job_handler("k.x", registry=reg, serit="hizli")


def test_uzun_serit_yapilandirmasi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_SESSION_SECRET", "x" * 40)
    monkeypatch.setenv("TP_DATABASE_URL", "postgresql+psycopg://tp_app@localhost:1/tp")
    get_settings.cache_clear()
    try:
        varsayilan = worker.uzun_serit_turleri()
        assert {"ci.run", "repair.fix"} <= varsayilan
        # PO sorgusu ve triage taraması asla uzun şeritte değildir (genel yuvada hemen koşar)
        assert not {"requirements.po_poll", "triage.sweep"} & varsayilan
        monkeypatch.setenv("TP_WORKER_UZUN_SERIT", "0")
        get_settings.cache_clear()
        assert worker.uzun_serit_turleri() == frozenset()
    finally:
        get_settings.cache_clear()


# ------------------------------------------------------------------ uçtan uca: iki yuva


def test_uzun_is_kosarken_kisa_isler_beklemez(engine: Engine) -> None:
    """Uzun iş (CI koşusu benzeri) koşarken PO sorgusu benzeri kısa iş hemen işlenir."""
    ek = uuid.uuid4().hex[:6]
    uzun_tur, kisa_tur = f"t.ci.{ek}", f"t.po.{ek}"
    basladi, serbest = threading.Event(), threading.Event()

    def uzun_is(_c) -> None:
        basladi.set()
        assert serbest.wait(10)

    job_handler(uzun_tur, max_deneme=1, zaman_asimi_s=30)(uzun_is)
    job_handler(kisa_tur, max_deneme=1, zaman_asimi_s=30)(lambda _c: None)
    dur = threading.Event()
    sonuc: list[int] = []
    t = threading.Thread(
        target=lambda: sonuc.append(worker.run(dur, aralik=0.02, uzun={uzun_tur})), daemon=True
    )
    try:
        with engine.begin() as c:
            uzun_id = enqueue(c, uzun_tur)
        t.start()
        assert basladi.wait(10)
        with engine.begin() as c:
            kisa_id = enqueue(c, kisa_tur)
        # uzun iş hâlâ koşarken kısa iş bitti
        assert _bekle(lambda: _durum(engine, kisa_id) == "done")
        assert _durum(engine, uzun_id) == "running"
        serbest.set()
        assert _bekle(lambda: _durum(engine, uzun_id) == "done")
    finally:
        serbest.set()
        dur.set()
        t.join(timeout=10)
        jobs.REGISTRY.pop(uzun_tur, None)
        jobs.REGISTRY.pop(kisa_tur, None)
    assert sonuc == [0]
    assert worker._genel_haric is None


def test_uzun_seritte_zaman_asimi_sureci_durdurur(engine: Engine) -> None:
    ek = uuid.uuid4().hex[:6]
    tur = f"t.asili.{ek}"
    serbest = threading.Event()
    job_handler(tur, max_deneme=1, zaman_asimi_s=1)(lambda _c: serbest.wait(6))
    try:
        with engine.begin() as c:
            jid = enqueue(c, tur)
        t0 = time.monotonic()
        kod = worker.run(threading.Event(), aralik=0.02, uzun={tur})
        assert kod == worker.ZAMAN_ASIMI_CIKIS_KODU
        assert time.monotonic() - t0 < 5
        assert _durum(engine, jid) == "failed"
    finally:
        serbest.set()
        jobs.REGISTRY.pop(tur, None)
