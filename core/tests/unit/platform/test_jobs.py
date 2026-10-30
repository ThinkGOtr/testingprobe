"""İş kuyruğu: kayıt, idempotency, SKIP LOCKED, yeniden deneme/geri çekilme, zaman aşımı,
worker döngüsü, özellik keşfi ve bütçe."""

from __future__ import annotations

import sys
import textwrap
import threading
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tp_core import worker
from tp_core.audit import PgCallRecorder
from tp_core.models import WorkflowInstance
from tp_core.workflow import jobs
from tp_core.workflow.budget import (
    BudgetExceeded,
    assert_budget,
    budget_status,
    enforce_budget,
)
from tp_core.workflow.jobs import (
    HandlerSpec,
    JobContext,
    PermanentJobError,
    cancel,
    claim,
    enqueue,
    job_handler,
    process_one,
    reap_stale,
    start_workflow,
)


def _job(engine: Engine, job_id: uuid.UUID):
    with engine.connect() as c:
        return c.execute(text("SELECT * FROM job WHERE id = :i"), {"i": job_id}).one()


def _kayit(**fns) -> dict[str, HandlerSpec]:
    reg: dict[str, HandlerSpec] = {}
    for tur, (fn, kw) in fns.items():
        job_handler(tur, registry=reg, **kw)(fn)
    return reg


def test_enqueue_claim_complete(engine: Engine) -> None:
    gorulen: list[JobContext] = []
    reg = _kayit(topla=(lambda ctx: gorulen.append(ctx) or {"toplam": 3}, {}))
    with engine.begin() as c:
        jid = enqueue(c, "topla", {"a": 1, "b": 2, "u": uuid.UUID(int=5)})
    sonuc = process_one(engine, "w1", reg)
    assert sonuc is not None and sonuc.durum == "done"
    assert gorulen[0].yuk == {"a": 1, "b": 2, "u": str(uuid.UUID(int=5))}
    assert (gorulen[0].deneme, gorulen[0].max_deneme) == (1, 3)
    row = _job(engine, jid)
    assert (row.durum, row.deneme, row.sonuc, row.kilitleyen) == ("done", 1, {"toplam": 3}, "w1")
    assert row.bitis is not None
    assert process_one(engine, "w1", reg) is None  # kuyruk boş


def test_idempotency_anahtari(engine: Engine) -> None:
    with engine.begin() as c:
        a = enqueue(c, "noop", idempotency_key="publish:case-1")
        b = enqueue(c, "noop", {"farkli": True}, idempotency_key="publish:case-1")
        d = enqueue(c, "noop")
    assert a == b != d
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM job")).scalar_one() == 2


def test_hata_yeniden_denenir_geri_cekilmeyle(engine: Engine) -> None:
    denemeler: list[int] = []

    def kirik(ctx: JobContext) -> None:
        denemeler.append(ctx.deneme)
        if ctx.deneme < 3:
            raise RuntimeError(f"geçici hata {ctx.deneme}")

    reg = _kayit(kirik=(kirik, {"max_deneme": 3, "backoff_s": 60}))
    with engine.begin() as c:
        jid = enqueue(c, "kirik")
    assert process_one(engine, "w", reg).durum == "retry"
    row = _job(engine, jid)
    assert (row.durum, row.deneme, row.son_hata) == ("retry", 1, "geçici hata 1")
    with engine.connect() as c:
        bekleme = c.execute(
            text("SELECT extract(epoch FROM run_after - now()) FROM job WHERE id = :i"),
            {"i": jid},
        ).scalar_one()
    assert 50 < bekleme <= 60
    assert process_one(engine, "w", reg) is None  # run_after gelecekte
    for beklenen_bekleme in (120,):
        with engine.begin() as c:
            c.execute(text("UPDATE job SET run_after = now() WHERE id = :i"), {"i": jid})
        assert process_one(engine, "w", reg).retry_in_s == beklenen_bekleme
    with engine.begin() as c:
        c.execute(text("UPDATE job SET run_after = now() WHERE id = :i"), {"i": jid})
    assert process_one(engine, "w", reg).durum == "done"
    assert denemeler == [1, 2, 3]
    assert _job(engine, jid).son_hata is None


def test_deneme_hakki_biter_failed(engine: Engine) -> None:
    def hep_kirik(_ctx: JobContext) -> None:
        raise ValueError("bozuk")

    reg = _kayit(hep=(hep_kirik, {"max_deneme": 2, "backoff_s": 0}))
    with engine.begin() as c:
        jid = enqueue(c, "hep")
    assert process_one(engine, "w", reg).durum == "retry"
    assert process_one(engine, "w", reg).durum == "failed"
    row = _job(engine, jid)
    assert (row.durum, row.deneme, row.son_hata) == ("failed", 2, "bozuk")


def test_satirdaki_max_deneme_kayittakini_ezer(engine: Engine) -> None:
    reg = _kayit(k=(lambda _c: 1 / 0, {"max_deneme": 5}))
    with engine.begin() as c:
        jid = enqueue(c, "k", max_deneme=1)
    assert process_one(engine, "w", reg).durum == "failed"
    assert _job(engine, jid).deneme == 1


def test_kalici_hata_yeniden_denenmez(engine: Engine) -> None:
    def insan_gerek(_ctx: JobContext) -> None:
        raise PermanentJobError("şema 2 kez geçersiz; insana düştü")

    reg = _kayit(p=(insan_gerek, {"max_deneme": 5}))
    with engine.begin() as c:
        jid = enqueue(c, "p")
    assert process_one(engine, "w", reg).durum == "failed"
    assert _job(engine, jid).deneme == 1


def test_bilinmeyen_tur_failed(engine: Engine) -> None:
    with engine.begin() as c:
        jid = enqueue(c, "kimse.bilmiyor")
    assert process_one(engine, "w", {}).durum == "failed"
    assert "bilinmeyen" in _job(engine, jid).son_hata


def test_skip_locked_iki_worker_farkli_is_alir(engine: Engine) -> None:
    with engine.begin() as c:
        ids = {enqueue(c, "noop") for _ in range(2)}
    with engine.begin() as c1, engine.begin() as c2:
        a = claim(c1, "w1")
        b = claim(c2, "w2")
        assert a is not None and b is not None
        assert {a.id, b.id} == ids
        assert claim(c2, "w2") is None


def test_paralel_isleme_her_is_bir_kez(engine: Engine) -> None:
    sayac: dict[str, int] = {}
    kilit = threading.Lock()

    def say(ctx: JobContext) -> None:
        with kilit:
            sayac[str(ctx.job_id)] = sayac.get(str(ctx.job_id), 0) + 1

    reg = _kayit(say=(say, {}))
    with engine.begin() as c:
        for _ in range(30):
            enqueue(c, "say")

    def calis(ad: str) -> None:
        while process_one(engine, ad, reg) is not None:
            pass

    iplikler = [threading.Thread(target=calis, args=(f"w{i}",)) for i in range(4)]
    for t in iplikler:
        t.start()
    for t in iplikler:
        t.join()
    assert len(sayac) == 30 and set(sayac.values()) == {1}


def test_zaman_asimi_toplanir_ve_eski_sonuc_yazilamaz(engine: Engine) -> None:
    with engine.begin() as c:  # kayıtsız tür: varsayılan politika (3 deneme) → retry
        jid = enqueue(c, "kayitsiz.tur", zaman_asimi_s=1)
    with engine.begin() as c:
        job = claim(c, "olu-worker")
        c.execute(
            text("UPDATE job SET baslama = now() - interval '5 seconds' WHERE id = :i"),
            {"i": jid},
        )
    with engine.begin() as c:
        assert reap_stale(c) == 1
    row = _job(engine, jid)
    assert (row.durum, row.kilitleyen) == ("retry", None)
    with engine.begin() as c:  # geç kalan worker sonucu yazamaz
        assert not jobs.complete(c, job.id, "olu-worker")


def _calisiyor_yap(engine: Engine, jid: uuid.UUID, *, baslama: str, sessiz: str = "0") -> None:
    with engine.begin() as c:
        assert claim(c, "olu-worker") is not None
        c.execute(
            text(
                "UPDATE job SET baslama = now() - CAST(:b AS interval), "
                "guncelleme = now() - CAST(:g AS interval) WHERE id = :i"
            ),
            {"b": baslama, "g": f"{sessiz} seconds", "i": jid},
        )


def test_ajan_isi_zaman_asiminda_yeniden_denenmez(engine: Engine) -> None:
    """§8.1: ajan işleri max_deneme=1; satırda değer verilmese de kayıttaki politika uygulanır."""
    reg = _kayit(**{"agent.x": (lambda _c: None, {"max_deneme": 1, "zaman_asimi_s": 7200})})
    with engine.begin() as c:
        jid = enqueue(c, "agent.x", registry=reg)
    row = _job(engine, jid)
    assert (row.max_deneme, row.zaman_asimi_s) == (1, 7200)  # satır etkin politikayı taşır
    _calisiyor_yap(engine, jid, baslama="2 hours 1 minute")
    with engine.begin() as c:
        assert reap_stale(c, registry=reg) == 1
    row = _job(engine, jid)
    assert (row.durum, row.kilitleyen) == ("failed", None)
    assert row.bitis is not None and "zaman aşımı" in row.son_hata


def test_satira_yazilmamis_politika_worker_kaydindan_cozulur(engine: Engine) -> None:
    """core-api işleyiciyi bilmeden kuyruğa ekler (NULL); reaper worker'ın kaydını kullanır."""
    reg = _kayit(**{"long.x": (lambda _c: None, {"max_deneme": 1, "zaman_asimi_s": 7200})})
    with engine.begin() as c:
        jid = enqueue(c, "long.x", registry={})
    row = _job(engine, jid)
    assert (row.max_deneme, row.zaman_asimi_s) == (None, None)
    _calisiyor_yap(engine, jid, baslama="20 minutes")  # 900 sn'yi aştı ama 7200'ü aşmadı
    with engine.begin() as c:
        assert reap_stale(c, registry=reg) == 0
    assert _job(engine, jid).durum == "running"
    _calisiyor_yap_tekrar = "UPDATE job SET baslama = now() - interval '3 hours' WHERE id = :i"
    with engine.begin() as c:
        c.execute(text(_calisiyor_yap_tekrar), {"i": jid})
        assert reap_stale(c, registry=reg) == 1
    assert _job(engine, jid).durum == "failed"


def test_nabzi_kesilen_is_toplanir(engine: Engine) -> None:
    reg = _kayit(**{"uzun.y": (lambda _c: None, {"max_deneme": 3, "zaman_asimi_s": 7200})})
    with engine.begin() as c:
        canli = enqueue(c, "uzun.y", registry=reg)
        olu = enqueue(c, "uzun.y", registry=reg)
    _calisiyor_yap(engine, canli, baslama="10 minutes", sessiz="5")
    _calisiyor_yap(engine, olu, baslama="10 minutes", sessiz="90")
    with engine.begin() as c:
        assert reap_stale(c, registry=reg) == 1
    assert _job(engine, canli).durum == "running"
    olu_row = _job(engine, olu)
    assert (olu_row.durum, olu_row.bitis) == ("retry", None)
    assert "nabız" in olu_row.son_hata


def test_calisan_is_nabiz_yazar(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    monkeypatch.setattr(jobs, "HEARTBEAT_S", 0.05)
    gozlem: dict[str, float] = {}

    def yavas(ctx: JobContext) -> None:
        time.sleep(0.4)
        with engine.connect() as c:
            gozlem["fark"] = c.execute(
                text("SELECT EXTRACT(EPOCH FROM guncelleme - baslama) FROM job WHERE id = :i"),
                {"i": ctx.job_id},
            ).scalar_one()

    reg = _kayit(yavas=(yavas, {"max_deneme": 1}))
    with engine.begin() as c:
        enqueue(c, "yavas", registry=reg)
    assert process_one(engine, "w-nabiz", reg).durum == "done"
    assert float(gozlem["fark"]) >= 0.2


def test_worker_yeniden_baslayinca_kalan_isler_birakilir(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Konteyner yeniden başladı: aynı hostname'in önceki sürecinin `running` işi beklemeden
    bırakılır ve yeniden işlenir; başka makinenin işi ve ajan işi (max_deneme=1) yeniden
    çalıştırılmaz."""
    import socket

    calisan: list[str] = []
    tur = f"test.restart.{uuid.uuid4().hex[:6]}"
    ajan = f"agent.restart.{uuid.uuid4().hex[:6]}"
    job_handler(tur, max_deneme=3)(lambda ctx: calisan.append(ctx.tur))
    job_handler(ajan, max_deneme=1)(lambda ctx: calisan.append(ctx.tur))
    try:
        with engine.begin() as c:
            yarim = enqueue(c, tur)
            ajan_id = enqueue(c, ajan)
            baska = enqueue(c, tur)
        host = socket.gethostname()
        with engine.begin() as c:
            for jid, kim in ((yarim, f"{host}:1"), (ajan_id, f"{host}:1"), (baska, "baska:1")):
                c.execute(
                    text(
                        "UPDATE job SET durum = 'running', deneme = 1, kilitleyen = :w, "
                        "baslama = now(), guncelleme = now() WHERE id = :i"
                    ),
                    {"w": kim, "i": jid},
                )
        monkeypatch.setattr(worker, "_sahipsizler_birakildi", False)
        assert worker.tek_tur() is True  # bıraktı ve yeniden işledi
        assert worker.tek_tur() is False
        assert calisan == [tur]
        assert _job(engine, yarim).durum == "done"
        ajan_row = _job(engine, ajan_id)
        assert (ajan_row.durum, ajan_row.bitis is not None) == ("failed", True)
        assert "yeniden başladı" in ajan_row.son_hata
        assert _job(engine, baska).durum == "running"
    finally:
        jobs.REGISTRY.pop(tur, None)
        jobs.REGISTRY.pop(ajan, None)


def test_release_orphans_hostname_desenini_kacirir(engine: Engine) -> None:
    with engine.begin() as c:
        a = enqueue(c, "kayitsiz.a")
        b = enqueue(c, "kayitsiz.b")
        c.execute(
            text(
                "UPDATE job SET durum = 'running', deneme = 1, kilitleyen = :w, baslama = now() "
                "WHERE id = :i"
            ),
            {"w": "host_1:5", "i": a},
        )
        c.execute(
            text(
                "UPDATE job SET durum = 'running', deneme = 1, kilitleyen = :w, baslama = now() "
                "WHERE id = :i"
            ),
            {"w": "hostX1:5", "i": b},
        )
        assert jobs.release_orphans(c, host="host_1") == 1
    assert (_job(engine, a).durum, _job(engine, b).durum) == ("retry", "running")


def test_iptal(engine: Engine) -> None:
    with engine.begin() as c:
        jid = enqueue(c, "noop")
        assert cancel(c, jid)
        assert not cancel(c, jid)
    assert _job(engine, jid).durum == "cancelled"
    assert process_one(engine, "w") is None


def test_start_workflow(engine: Engine) -> None:
    with engine.begin() as c:
        wf, jid = start_workflow(
            c, "RequirementToCases", "analist", job_tur="noop", yuk={"jira_key": "TPD-1"},
            idempotency_key="r2c:TPD-1",
        )  # fmt: skip
        wf2, jid2 = start_workflow(c, "RequirementToCases", "analist", idempotency_key="r2c:TPD-1")
    assert (wf, jid) == (wf2, jid2)
    row = _job(engine, jid)
    assert row.workflow_id == wf and row.yuk == {"jira_key": "TPD-1", "workflow_id": str(wf)}
    with engine.connect() as c:
        w = c.execute(text("SELECT * FROM workflow_instance WHERE id = :i"), {"i": wf}).one()
        assert (w.durum, w.job_id, w.baslatan) == ("running", jid, "analist")


def test_start_workflow_eszamanli_ayni_anahtar_tek_akis(engine: Engine) -> None:
    """Çift tıklama: aynı idempotency anahtarıyla eşzamanlı iki çağrı tek iş akışı açar."""
    bariyer = threading.Barrier(2)
    sonuclar: list[tuple[uuid.UUID, uuid.UUID]] = []
    hatalar: list[BaseException] = []

    def baslat() -> None:
        try:
            with engine.begin() as c:
                bariyer.wait(5)
                sonuclar.append(start_workflow(c, "demo", "u", idempotency_key="k1"))
                import time

                time.sleep(0.2)  # diğer çağrı kilitte beklerken commit gecikir
        except BaseException as exc:
            hatalar.append(exc)

    iplikler = [threading.Thread(target=baslat) for _ in range(2)]
    for t in iplikler:
        t.start()
    for t in iplikler:
        t.join(15)
    assert hatalar == []
    assert len(sonuclar) == 2 and sonuclar[0] == sonuclar[1]
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM workflow_instance")).scalar_one() == 1
        assert c.execute(text("SELECT count(*) FROM job")).scalar_one() == 1
        n = c.execute(
            text("SELECT count(*) FROM audit_event WHERE eylem = 'workflow.started'")
        ).scalar_one()
        assert n == 1


def test_start_workflow_akissiz_isin_anahtariyla_yetim_akis_acmaz(engine: Engine) -> None:
    with engine.begin() as c:
        enqueue(c, "noop", idempotency_key="k-duz")
    with engine.begin() as c, pytest.raises(ValueError, match="bağlı olmayan"):
        start_workflow(c, "demo", "u", idempotency_key="k-duz")
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM workflow_instance")).scalar_one() == 0


def test_cift_kayit_reddedilir() -> None:
    reg: dict[str, HandlerSpec] = {}
    job_handler("x", registry=reg)(lambda _c: None)
    with pytest.raises(ValueError, match="iki kez"):
        job_handler("x", registry=reg)(lambda _c: None)
    with pytest.raises(ValueError):
        job_handler("y", max_deneme=0)


def test_backoff_ust_sinirli() -> None:
    spec = HandlerSpec("t", lambda _c: None, backoff_s=10, max_backoff_s=25)
    assert [spec.backoff(n) for n in (1, 2, 3, 4)] == [10, 20, 25, 25]


# -------------------------------------------------------------- worker döngüsü


def test_worker_tek_tur_kayitli_isleyiciyi_calistirir(engine: Engine) -> None:
    calisti: list[uuid.UUID] = []
    tur = f"test.{uuid.uuid4().hex[:6]}"
    job_handler(tur)(lambda ctx: calisti.append(ctx.job_id))
    try:
        with engine.begin() as c:
            jid = enqueue(c, tur)
        assert worker.tek_tur() is True
        assert calisti == [jid]
        assert worker.tek_tur() is False
    finally:
        jobs.REGISTRY.pop(tur, None)


class _KayitliBekleme(threading.Event):
    def __init__(self, tur_sayisi: int) -> None:
        super().__init__()
        self.beklemeler: list[float] = []
        self._kalan = tur_sayisi

    def wait(self, timeout: float | None = None) -> bool:
        self.beklemeler.append(float(timeout or 0))
        return self.is_set()


def test_db_kesintisinde_kisa_uyari_ve_ustel_bekleme(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    from sqlalchemy.exc import OperationalError

    dur = _KayitliBekleme(0)
    turlar = iter(["db", "db", "db", "db", "ok", "db", "son"])

    def tek_tur() -> bool:
        adim = next(turlar)
        if adim == "db":
            raise OperationalError("SELECT 1", {}, Exception("connection refused\nuzun iz"))
        if adim == "son":
            dur.set()
        return False

    monkeypatch.setattr(worker, "tek_tur", tek_tur)
    with caplog.at_level(logging.INFO, logger="tp_core.worker"):
        worker.run(dur, aralik=1.0)
    assert dur.beklemeler == [1.0, 2.0, 4.0, 8.0, 1.0, 1.0, 1.0]
    uyarilar = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(uyarilar) == 5
    assert all(r.exc_info is None for r in uyarilar)  # traceback yok
    assert "DB erişilemiyor: connection refused; 1 sn sonra tekrar" in uyarilar[0].getMessage()
    assert "uzun iz" not in uyarilar[0].getMessage()
    kurtarma = [r for r in caplog.records if "yeniden kuruldu" in r.getMessage()]
    assert len(kurtarma) == 2  # iki kesinti, iki kurtarma (her biri bir kez)


def test_db_bekleme_ust_siniri(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy.exc import OperationalError

    dur = _KayitliBekleme(0)
    sayac = {"n": 0}

    def tek_tur() -> bool:
        sayac["n"] += 1
        if sayac["n"] > 8:
            dur.set()
        raise OperationalError("SELECT 1", {}, Exception("down"))

    monkeypatch.setattr(worker, "tek_tur", tek_tur)
    worker.run(dur, aralik=1.0)
    assert max(dur.beklemeler) == worker.DB_BEKLEME_UST_S
    assert dur.beklemeler[:6] == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]


def test_worker_run_durur(engine: Engine) -> None:
    dur = threading.Event()
    t = threading.Thread(target=worker.run, args=(dur, 0.01))
    t.start()
    dur.set()
    t.join(timeout=5)
    assert not t.is_alive()


def test_ozellik_isleyicileri_kesfedilir(tmp_path: Path) -> None:
    paket = f"tp_fake_features_{uuid.uuid4().hex[:6]}"
    (tmp_path / paket / "ornek").mkdir(parents=True)
    (tmp_path / paket / "__init__.py").write_text("")
    (tmp_path / paket / "ornek" / "__init__.py").write_text("")
    (tmp_path / paket / "ornek" / "jobs.py").write_text(
        textwrap.dedent(
            f"""
            from tp_core.workflow.jobs import job_handler

            @job_handler("{paket}.ornek")
            def h(ctx):
                return None
            """
        )
    )
    (tmp_path / paket / "bos").mkdir()
    (tmp_path / paket / "bos" / "__init__.py").write_text("")
    sys.path.insert(0, str(tmp_path))
    try:
        assert jobs.discover(paket) == [f"{paket}.ornek.jobs"]
        assert f"{paket}.ornek" in jobs.REGISTRY
        assert jobs.discover("yok_boyle_paket") == []
    finally:
        sys.path.remove(str(tmp_path))
        jobs.REGISTRY.pop(f"{paket}.ornek", None)


# ------------------------------------------------------------------------ bütçe


def _maliyet(engine: Engine, usd: float, wf: uuid.UUID | None = None) -> None:
    PgCallRecorder(engine).record_ai_call(
        {"amac": "a", "saglayici": "anthropic", "model": "m", "mod": "live",
         "maliyet": usd, "workflow_id": wf}
    )  # fmt: skip


def test_butce_gunluk_ve_is_akisi(engine: Engine) -> None:
    wf = uuid.uuid4()
    _maliyet(engine, 1.5, wf)
    _maliyet(engine, 0.25, wf)
    _maliyet(engine, 10, None)
    with engine.connect() as c:
        d = budget_status(c, wf, daily_limit=30, workflow_limit=2)
        assert d.ok
        assert (d.daily_spent, d.workflow_spent) == (Decimal("11.75"), Decimal("1.75"))
        assert not budget_status(c, wf, daily_limit=30, workflow_limit=2, planned_usd=0.5).ok
        assert "iş akışı" in budget_status(c, wf, daily_limit=30, workflow_limit=1.75).reason
        assert "günlük" in budget_status(c, None, daily_limit=11.75, workflow_limit=2).reason
        with pytest.raises(BudgetExceeded) as hata:
            assert_budget(c, wf, daily_limit=5, workflow_limit=2)
        assert hata.value.status.as_dict()["daily_spent_usd"] == "11.750000"


def test_butce_varsayilanlari_ayarlardan(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    from tp_core.config import get_settings

    monkeypatch.setenv("TP_DAILY_BUDGET_USD", "1")
    get_settings.cache_clear()
    _maliyet(engine, 1)
    with engine.connect() as c:
        d = budget_status(c)
    assert (d.daily_limit, d.workflow_limit, d.ok) == (Decimal("1"), Decimal("2.0"), False)


def test_butce_asiminda_is_akisi_duraklar(engine: Engine) -> None:
    with Session(engine) as s:
        wf = WorkflowInstance(tur="CasesToCode", baslatan="muhendis")
        s.add(wf)
        s.commit()
        _maliyet(engine, 3, wf.id)
        with pytest.raises(BudgetExceeded):
            enforce_budget(s, wf.id, daily_limit=30, workflow_limit=2)
        s.commit()
        s.refresh(wf)
        assert wf.durum == "paused"


def test_gecit_butce_asimi_isi_yeniden_denemez_ve_akisi_duraklatir(engine: Engine) -> None:
    from tp_core.gateway import BudgetExceeded as GecitButceAsimi

    cagri: list[int] = []

    def pahali(_ctx: JobContext) -> None:
        cagri.append(1)
        raise GecitButceAsimi("workflow", 2.4, 2.0)

    reg = _kayit(pahali=(pahali, {"max_deneme": 3}))
    with engine.begin() as c:
        wf, jid = start_workflow(c, "CasesToCode", "muhendis", job_tur="pahali", yuk={})
    sonuc = process_one(engine, "w1", reg)
    assert sonuc is not None and sonuc.durum == "failed" and sonuc.butce_asildi
    assert _job(engine, jid).durum == "failed"
    assert process_one(engine, "w1", reg) is None  # yeniden kuyruğa girmedi
    assert cagri == [1]
    with engine.connect() as c:
        durum = c.execute(
            text("SELECT durum FROM workflow_instance WHERE id = :i"), {"i": wf}
        ).scalar_one()
        olay = c.execute(
            text("SELECT count(*) FROM audit_event WHERE nesne = :n AND ozet->>'to' = 'paused'"),
            {"n": f"workflow_instance:{wf}"},
        ).scalar_one()
    assert durum == "paused"
    assert olay == 1


def test_is_akisi_butce_istisnasi_gecidinkinin_alt_sinifi() -> None:
    from tp_core.gateway import BudgetExceeded as GecitButceAsimi
    from tp_core.workflow.budget import BudgetStatus

    exc = BudgetExceeded(
        BudgetStatus(Decimal(1), Decimal(30), Decimal("2.5"), Decimal(2), "iş akışı aşıldı")
    )
    assert isinstance(exc, GecitButceAsimi)
    assert (exc.scope, exc.spent_usd, exc.cap_usd) == ("workflow", 2.5, 2.0)
    assert str(exc) == "iş akışı aşıldı"
