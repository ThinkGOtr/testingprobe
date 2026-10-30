"""İş zaman aşımı yürütücüde uygulanır; başarısız iş bağlı iş akışını `failed` yapar.

Regresyonlar:
- Tek worker'da asılı bir işleyici `zaman_asimi_s`'i aşsa da `done` oluyordu (reaper aynı iş
  parçacığında, iş bitene kadar çalışamıyordu) ve sonraki tüm işleri bekletiyordu.
- İşleyici hatası, bilinmeyen tür, zaman aşımı, nabız kaybı ve sahipsiz iş `failed` olunca
  iş akışı sonsuza kadar `running` kalıyordu.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from tp_core import worker
from tp_core.audit import verify_chain
from tp_core.worker import healthcheck
from tp_core.workflow import jobs
from tp_core.workflow.jobs import (
    HandlerSpec,
    JobContext,
    PermanentJobError,
    claim,
    enqueue,
    job_handler,
    process_one,
    reap_stale,
    release_orphans,
    start_workflow,
)


@pytest.fixture(autouse=True)
def _canlilik_dosyasi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    yol = tmp_path / "canli"
    monkeypatch.setenv("TP_WORKER_LIVENESS_FILE", str(yol))
    return yol


def _kayit(**fns) -> dict[str, HandlerSpec]:
    reg: dict[str, HandlerSpec] = {}
    for tur, (fn, kw) in fns.items():
        job_handler(tur, registry=reg, **kw)(fn)
    return reg


def _job(engine: Engine, job_id: uuid.UUID):
    with engine.connect() as c:
        return c.execute(text("SELECT * FROM job WHERE id = :i"), {"i": job_id}).one()


def _akis(engine: Engine, wf_id: uuid.UUID):
    with engine.connect() as c:
        return c.execute(
            text("SELECT durum FROM workflow_instance WHERE id = :i"), {"i": wf_id}
        ).scalar_one()


def _akis_denetimi(engine: Engine, wf_id: uuid.UUID) -> list[dict]:
    with engine.connect() as c:
        assert verify_chain(c).ok
        return list(
            c.execute(
                text(
                    "SELECT ozet FROM audit_event WHERE nesne = :n "
                    "AND eylem = 'workflow_instance.transition' ORDER BY id"
                ),
                {"n": f"workflow_instance:{wf_id}"},
            ).scalars()
        )


def _akis_baslat(engine: Engine, tur: str, reg: dict[str, HandlerSpec]):
    with engine.begin() as c:
        wf_id, jid = start_workflow(c, tur, "analist", job_tur=tur)
        # start_workflow politikayı küresel kayıttan çözer; testler yerel kayıt kullanır.
        spec = reg[tur]
        c.execute(
            text("UPDATE job SET max_deneme = :m, zaman_asimi_s = :z WHERE id = :i"),
            {"m": spec.max_deneme, "z": spec.zaman_asimi_s, "i": jid},
        )
    return wf_id, jid


# ------------------------------------------------------------ zaman aşımı yürütücüde


def test_asili_isleyici_zaman_asiminda_birakilir_tek_worker(engine: Engine) -> None:
    """`zaman_asimi_s=1`, işleyici 6 sn uyur: process_one ~1 sn'de döner, iş `failed`."""
    serbest = threading.Event()

    def asili(_ctx: JobContext) -> None:
        serbest.wait(6)

    reg = _kayit(**{"agent.asili": (asili, {"max_deneme": 1, "zaman_asimi_s": 1})})
    with engine.begin() as c:
        jid = enqueue(c, "agent.asili", registry=reg)
        sonraki = enqueue(c, "noop")
    try:
        t0 = time.monotonic()
        sonuc = process_one(engine, "w-tek", reg)
        gecen = time.monotonic() - t0
    finally:
        serbest.set()
    assert sonuc is not None and sonuc.zaman_asimi and sonuc.durum == "failed"
    assert gecen < 4, gecen
    row = _job(engine, jid)
    assert row.durum == "failed" and "zaman aşımı" in row.son_hata and row.bitis is not None
    assert _job(engine, sonraki).durum == "queued"  # kuyruk kilitlenmedi


def test_zaman_asimi_deneme_hakki_varsa_retry(engine: Engine) -> None:
    serbest = threading.Event()
    reg = _kayit(yavas=(lambda _c: serbest.wait(5), {"max_deneme": 3, "zaman_asimi_s": 1}))
    with engine.begin() as c:
        jid = enqueue(c, "yavas", registry=reg)
    try:
        sonuc = process_one(engine, "w-r", reg)
    finally:
        serbest.set()
    assert sonuc is not None and sonuc.zaman_asimi and sonuc.durum == "retry"
    row = _job(engine, jid)
    assert (row.durum, row.bitis) == ("retry", None)


def test_satirdaki_zaman_asimi_kayittakini_ezer(engine: Engine) -> None:
    serbest = threading.Event()
    reg = _kayit(uzun=(lambda _c: serbest.wait(5), {"max_deneme": 1, "zaman_asimi_s": 3600}))
    with engine.begin() as c:
        enqueue(c, "uzun", registry=reg, zaman_asimi_s=1)
    try:
        sonuc = process_one(engine, "w-s", reg)
    finally:
        serbest.set()
    assert sonuc is not None and sonuc.zaman_asimi


def test_zamaninda_biten_is_etkilenmez(engine: Engine) -> None:
    reg = _kayit(hizli=(lambda _c: {"ok": True}, {"zaman_asimi_s": 5}))
    with engine.begin() as c:
        jid = enqueue(c, "hizli", registry=reg)
    sonuc = process_one(engine, "w-h", reg)
    assert sonuc is not None and not sonuc.zaman_asimi and sonuc.durum == "done"
    assert _job(engine, jid).sonuc == {"ok": True}


def test_isleyici_baglam_degiskenlerini_gorur(engine: Engine) -> None:
    """İşleyici ayrı iş parçacığında koşar ama çağıranın contextvars bağlamını taşır."""
    from tp_core.models.guard import _izinli

    gorulen: list[bool] = []
    reg = _kayit(bak=(lambda _c: gorulen.append(_izinli.get()), {}))
    with engine.begin() as c:
        enqueue(c, "bak", registry=reg)
    token = _izinli.set(True)
    try:
        process_one(engine, "w-b", reg)
    finally:
        _izinli.reset(token)
    assert gorulen == [True]


def test_worker_zaman_asiminda_cikis_koduyla_durur(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, _canlilik_dosyasi: Path
) -> None:
    serbest = threading.Event()
    tur = f"agent.hang.{uuid.uuid4().hex[:6]}"
    job_handler(tur, max_deneme=1, zaman_asimi_s=1)(lambda _c: serbest.wait(6))
    monkeypatch.setattr(worker, "_sahipsizler_birakildi", True)
    try:
        with engine.begin() as c:
            jid = enqueue(c, tur)
        dur = threading.Event()
        t0 = time.monotonic()
        kod = worker.run(dur, aralik=0.01)
        assert kod == worker.ZAMAN_ASIMI_CIKIS_KODU
        assert time.monotonic() - t0 < 5
        assert _job(engine, jid).durum == "failed"
        assert _canlilik_dosyasi.exists()
    finally:
        serbest.set()
        jobs.REGISTRY.pop(tur, None)


def test_worker_normal_durdurmada_sifir_doner(engine: Engine) -> None:
    dur = threading.Event()
    dur.set()
    assert worker.run(dur, aralik=0.01) == 0


# ------------------------------------------------------------- canlılık sağlık kontrolü


def test_saglik_kontrolu_canlilik_dosyasini_denetler(
    engine: Engine, _canlilik_dosyasi: Path
) -> None:
    assert healthcheck.main() == 0  # dosya yok (açılış): yalnızca DB
    worker.canli()
    assert _canlilik_dosyasi.exists()
    assert healthcheck.main() == 0
    eski = time.time() - worker.CANLILIK_ESIGI_S - 10
    os.utime(_canlilik_dosyasi, (eski, eski))
    assert healthcheck.canlilik_hatasi() is not None
    assert healthcheck.main() == 1


def test_canlilik_is_beklerken_tazelenir(engine: Engine) -> None:
    sayac: list[float] = []
    reg = _kayit(bekle=(lambda _c: time.sleep(0.5), {"zaman_asimi_s": 5}))
    with engine.begin() as c:
        enqueue(c, "bekle", registry=reg)
    eski = jobs.CANLILIK_ARALIGI_S
    jobs.CANLILIK_ARALIGI_S = 0.1
    try:
        process_one(engine, "w-c", reg, canli=lambda: sayac.append(time.monotonic()))
    finally:
        jobs.CANLILIK_ARALIGI_S = eski
    assert len(sayac) >= 3


# ------------------------------------------------------ başarısız iş → iş akışı failed


def _hata(_ctx: JobContext) -> None:
    raise RuntimeError("Jira 500")


def _kalici(_ctx: JobContext) -> None:
    raise PermanentJobError("şema geçersiz")


@pytest.mark.parametrize(
    ("fn", "kw", "hata"),
    [
        (_hata, {"max_deneme": 1}, "Jira 500"),
        (_kalici, {"max_deneme": 3}, "şema geçersiz"),
    ],
)
def test_basarisiz_is_akisi_failed_yapar(engine: Engine, fn, kw: dict, hata: str) -> None:
    reg = _kayit(**{"akis.is": (fn, kw)})
    wf_id, jid = _akis_baslat(engine, "akis.is", reg)
    sonuc = process_one(engine, "w-f", reg)
    assert sonuc is not None and sonuc.durum == "failed"
    assert _job(engine, jid).durum == "failed"
    assert _akis(engine, wf_id) == "failed"
    kayitlar = _akis_denetimi(engine, wf_id)
    assert [(k["from"], k["to"]) for k in kayitlar] == [("running", "failed")]
    assert hata in kayitlar[0]["sebep"]


def test_yeniden_denenecek_hata_akisi_bozmaz(engine: Engine) -> None:
    reg = _kayit(**{"akis.r": (_hata, {"max_deneme": 3})})
    wf_id, _ = _akis_baslat(engine, "akis.r", reg)
    assert process_one(engine, "w-r", reg).durum == "retry"
    assert _akis(engine, wf_id) == "running"


def test_bilinmeyen_tur_akisi_failed_yapar(engine: Engine) -> None:
    with engine.begin() as c:
        wf_id, _ = start_workflow(c, "kayitsiz.akis", "analist")
    assert process_one(engine, "w-u", {}).durum == "failed"
    assert _akis(engine, wf_id) == "failed"


def test_zaman_asimi_akisi_failed_yapar(engine: Engine) -> None:
    serbest = threading.Event()
    reg = _kayit(**{"agent.akis": (lambda _c: serbest.wait(5), {"max_deneme": 1,
                                                                 "zaman_asimi_s": 1})})  # fmt: skip
    wf_id, _ = _akis_baslat(engine, "agent.akis", reg)
    try:
        process_one(engine, "w-z", reg)
    finally:
        serbest.set()
    assert _akis(engine, wf_id) == "failed"
    assert "zaman aşımı" in _akis_denetimi(engine, wf_id)[0]["sebep"]


def test_reaper_zaman_asimi_akisi_failed_yapar(engine: Engine) -> None:
    """Çökmüş başka bir worker'ın ajan işi (max_deneme=1) reaper tarafından toplanır."""
    reg = _kayit(**{"agent.uzak": (lambda _c: None, {"max_deneme": 1, "zaman_asimi_s": 60})})
    wf_id, jid = _akis_baslat(engine, "agent.uzak", reg)
    with engine.begin() as c:
        assert claim(c, "baska-makine:1") is not None
        c.execute(
            text("UPDATE job SET baslama = now() - interval '5 minutes' WHERE id = :i"),
            {"i": jid},
        )
    with engine.begin() as c:
        assert reap_stale(c, registry=reg) == 1
    assert _job(engine, jid).durum == "failed"
    assert _akis(engine, wf_id) == "failed"
    assert "zaman aşımı" in _akis_denetimi(engine, wf_id)[0]["sebep"]


def test_reaper_retry_akisi_running_birakir(engine: Engine) -> None:
    reg = _kayit(**{"uzak.r": (lambda _c: None, {"max_deneme": 3, "zaman_asimi_s": 60})})
    wf_id, jid = _akis_baslat(engine, "uzak.r", reg)
    with engine.begin() as c:
        claim(c, "baska:1")
        c.execute(
            text("UPDATE job SET guncelleme = now() - interval '5 minutes' WHERE id = :i"),
            {"i": jid},
        )
        assert reap_stale(c, registry=reg) == 1
    assert _job(engine, jid).durum == "retry"
    assert _akis(engine, wf_id) == "running"


def test_sahipsiz_is_akisi_failed_yapar(engine: Engine) -> None:
    reg = _kayit(**{"agent.yetim": (lambda _c: None, {"max_deneme": 1})})
    wf_id, jid = _akis_baslat(engine, "agent.yetim", reg)
    with engine.begin() as c:
        claim(c, "makine-a:42")
    with engine.begin() as c:
        assert release_orphans(c, host="makine-a", registry=reg) == 1
    assert _job(engine, jid).durum == "failed"
    assert _akis(engine, wf_id) == "failed"


def test_insan_bekleyen_akisa_dokunulmaz(engine: Engine) -> None:
    """İşleyici akışı `waiting_human` yaptıysa sonraki iş hatası onu `failed` yapmaz."""
    from sqlalchemy.orm import Session

    from tp_core.models import WorkflowInstance
    from tp_core.workflow.service import SYSTEM, transition

    def bekle_sonra_patla(ctx: JobContext) -> None:
        with Session(engine) as s:
            wf = s.get(WorkflowInstance, ctx.workflow_id)
            transition(s, wf, "waiting_human", SYSTEM, "running")
            s.commit()
        raise PermanentJobError("insan kararı gerekli")

    reg = _kayit(**{"akis.h": (bekle_sonra_patla, {})})
    wf_id, _ = _akis_baslat(engine, "akis.h", reg)
    assert process_one(engine, "w-h", reg).durum == "failed"
    assert _akis(engine, wf_id) == "waiting_human"
