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
    ASISTAN_SERIT,
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


def test_asistan_serit_kapaliyken_asistan_isi_genel_seritte_kosmaz(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`TP_WORKER_ASISTAN_SERIT=0`: asistan işi genel şeritte alınmaz (orada zaman aşımı tüm
    süreci kapatırdı); kuyrukta kalır, genel işler işlenir, süreç çıkış kodu 0. Kalp atışı
    taze (şeridi açık başka worker var sayılır): kapalı şerit temizliği işe dokunmaz."""
    monkeypatch.setenv("TP_WORKER_ASISTAN_SERIT", "0")
    monkeypatch.setattr(worker, "_son_kapali_temizlik", 0.0)
    _kalp_atisi(engine, 0)
    ek = uuid.uuid4().hex[:6]
    a_tur, genel_tur = f"t.askapali.{ek}", f"t.genel.{ek}"
    calisti = threading.Event()

    def asistan_isi(_c) -> None:
        calisti.set()
        time.sleep(5)

    job_handler(a_tur, max_deneme=1, zaman_asimi_s=1, serit=ASISTAN_SERIT)(asistan_isi)
    job_handler(genel_tur, max_deneme=1, zaman_asimi_s=30)(lambda _c: None)
    dur = threading.Event()
    sonuc: list[int] = []
    t = threading.Thread(target=lambda: sonuc.append(worker.run(dur, aralik=0.02)), daemon=True)
    try:
        assert worker.asistan_serit_turleri() == frozenset()
        with engine.begin() as c:
            a_id = enqueue(c, a_tur)  # önce eklenen (en eski)
            g_id = enqueue(c, genel_tur)
        t.start()
        assert _bekle(lambda: _durum(engine, g_id) == "done")
        assert a_tur in (worker._genel_haric or [])
        time.sleep(0.2)
        assert not calisti.is_set()
        assert _durum(engine, a_id) == "queued"
        assert t.is_alive()
    finally:
        dur.set()
        t.join(timeout=10)
        jobs.REGISTRY.pop(a_tur, None)
        jobs.REGISTRY.pop(genel_tur, None)
    assert sonuc == [0]
    assert worker._genel_haric is None


def test_asili_asistan_is_parcacigi_yuva_tutar(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zaman aşımına uğrayan asistan işi `failed` yazılır (global bekleyende sayılmaz) ama asılı
    iş parçacığı durana dek yuva tutar: koşan + asılı ≤ `TP_WORKER_ASISTAN_PARALEL`."""
    monkeypatch.setenv("TP_WORKER_ASISTAN_PARALEL", "1")
    monkeypatch.setattr(worker, "_asistan_aktif", 0)
    monkeypatch.setattr(worker, "_asistan_asili", [])
    ek = uuid.uuid4().hex[:6]
    tur = f"t.asili.{ek}"
    serbest = threading.Event()
    job_handler(tur, max_deneme=1, zaman_asimi_s=1, serit=ASISTAN_SERIT)(
        lambda _c: serbest.wait(10)
    )
    try:
        with engine.begin() as c:
            ilk = enqueue(c, tur)
        assert worker.asistan_tur({tur}) is True
        assert _durum(engine, ilk) == "failed"
        assert len(worker._asistan_asili) == 1 and worker._asistan_asili[0].is_alive()
        with engine.begin() as c:
            ikinci = enqueue(c, tur)
        # asılı iş parçacığı yuvayı tutuyor: yeni iş alınmaz
        assert worker.asistan_tur({tur}) is False
        assert _durum(engine, ikinci) == "queued"
        assert worker._asistan_aktif == 0
        serbest.set()
        assert _bekle(lambda: not worker._asistan_asili[0].is_alive())
        assert worker.asistan_tur({tur}) is True
        assert _durum(engine, ikinci) == "done"
        assert worker._asistan_asili == []
    finally:
        serbest.set()
        jobs.REGISTRY.pop(tur, None)


def _kalp_atisi(engine: Engine, yas_s: int | None) -> None:
    with engine.begin() as c:
        c.execute(text("DELETE FROM asistan_durum"))
        if yas_s is not None:
            c.execute(
                text(
                    "INSERT INTO asistan_durum (id, mod, model_hazir, maskeleme, musteri_verisi, "
                    "kalp_atisi) VALUES (1, 'off', false, true, false, "
                    "now() - make_interval(secs => :y))"
                ),
                {"y": yas_s},
            )


def _soru(engine: Engine, kullanici_id: uuid.UUID, tur: str) -> tuple[uuid.UUID, uuid.UUID]:
    sohbet_id, mesaj_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as c:
        jid = enqueue(c, tur, {"mesaj_id": str(mesaj_id)})
        c.execute(
            text("INSERT INTO asistan_sohbet (id, kullanici_id) VALUES (:s, :k)"),
            {"s": sohbet_id, "k": kullanici_id},
        )
        c.execute(
            text(
                "INSERT INTO asistan_mesaj (id, sohbet_id, kullanici_id, sira, rol, durum, "
                "job_id) VALUES (:m, :s, :k, 2, 'assistant', 'pending', :j)"
            ),
            {"m": mesaj_id, "s": sohbet_id, "k": kullanici_id, "j": jid},
        )
    return jid, mesaj_id


def _yaslandir(engine: Engine, jid: uuid.UUID) -> None:
    with engine.begin() as c:
        c.execute(
            text("UPDATE job SET olusturma = now() - interval '1 hour' WHERE id = :i"),
            {"i": jid},
        )


def _mesaj_durumu(engine: Engine, mesaj_id: uuid.UUID) -> tuple[str, str | None]:
    with engine.connect() as c:
        r = c.execute(
            text("SELECT durum, hata_kodu FROM asistan_mesaj WHERE id = :i"), {"i": mesaj_id}
        ).one()
    return r.durum, r.hata_kodu


def test_asistan_serit_kapaliyken_bekleyen_soru_kalp_atisi_bayatlayinca_kapanir(
    engine: Engine, make_user
) -> None:
    """`TP_WORKER_ASISTAN_SERIT=0`: kapanmadan hemen önce kabul edilen soru süresiz `pending`
    kalmaz. Kalp atışı tazeyken (şeridi açık başka worker olabilir) dokunulmaz; API eşiğinden
    eskiyse ve iş de eşikten eskiyse iş `cancelled`, mesaj `error/zaman_asimi` olur (yeni iş,
    şeridi açık worker'ın yeniden başlama penceresi için korunur). Diğer türlere dokunulmaz."""
    ek = uuid.uuid4().hex[:6]
    a_tur, genel_tur = f"t.askapali2.{ek}", f"t.genel2.{ek}"
    job_handler(a_tur, max_deneme=1, zaman_asimi_s=30, serit=ASISTAN_SERIT)(lambda _c: None)
    try:
        kullanici = make_user("tester")
        jid, mid = _soru(engine, kullanici.id, a_tur)
        with engine.begin() as c:
            gid = enqueue(c, genel_tur)

        _kalp_atisi(engine, 10)  # taze: başka worker şeridi açık olabilir
        assert worker.kapali_serit_temizle({a_tur}) == 0
        assert _durum(engine, jid) == "queued"
        assert _mesaj_durumu(engine, mid) == ("pending", None)

        _kalp_atisi(engine, 10_000)  # bayat: API artık soru kabul etmiyor
        # ...ama iş yeni: şeridi açık worker yeniden başlıyor olabilir; dokunulmaz.
        assert worker.kapali_serit_temizle({a_tur}) == 0
        assert _durum(engine, jid) == "queued"
        assert _mesaj_durumu(engine, mid) == ("pending", None)

        _yaslandir(engine, jid)  # iş de eşikten eski: şerit gerçekten kapalı
        assert worker.kapali_serit_temizle({a_tur}) == 1
        assert _durum(engine, jid) == "cancelled"
        assert _mesaj_durumu(engine, mid) == ("error", "zaman_asimi")
        assert _durum(engine, gid) == "queued"
        assert worker.kapali_serit_temizle({a_tur}) == 0  # idempotent

        _kalp_atisi(engine, None)  # hiç kalp atışı yok
        jid2, mid2 = _soru(engine, kullanici.id, a_tur)
        assert worker.kapali_serit_temizle({a_tur}) == 0  # yeni iş korunur
        _yaslandir(engine, jid2)
        assert worker.kapali_serit_temizle({a_tur}) == 1
        assert _durum(engine, jid2) == "cancelled"
        assert _mesaj_durumu(engine, mid2)[0] == "error"
        assert worker.kapali_serit_temizle(set()) == 0
    finally:
        jobs.REGISTRY.pop(a_tur, None)
