"""CI işleri (core-worker; `discover()` yükler). Bu işlerde model çağrısı yoktur (Constitution II).

- `ci.run`          bir koşu: local → toolchain `/check` + ayrıştırma; github → yoklama başlar.
- `ci.github_poll`  GitHub workflow koşusunu bulur, bitene kadar kendini yeniden planlar, alır.
- `ci.nightly`      gece koşusu (`TP_CI_NIGHTLY_SAAT`, Europe/Istanbul); ertesi günü planlar.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from tp_core.db import get_engine
from tp_core.features.ci import service
from tp_core.features.ci.clients import check_timeout_s
from tp_core.workflow.jobs import JobContext, PermanentJobError, job_handler


def _run_id(ctx: JobContext) -> uuid.UUID:
    try:
        return uuid.UUID(str((ctx.yuk or {})["run_id"]))
    except (KeyError, ValueError) as exc:
        raise PermanentJobError("iş yükünde geçerli run_id yok") from exc


# toolchain /check tek kilitlidir (kod üretiminin yerel kontrolüyle paylaşılır): 409 → yeniden dene.
# İş süre sınırı istemci zaman aşımından uzundur: sınır aşımında worker süreci düşer (tüm işler).
@job_handler(
    service.JOB_RUN, max_deneme=5, backoff_s=30.0, zaman_asimi_s=int(check_timeout_s()) + 300
)
def ci_run(ctx: JobContext) -> dict[str, Any]:
    engine = get_engine()
    sonuc = service.run_job(engine, _run_id(ctx), deneme=ctx.deneme, son_deneme=ctx.son_deneme)
    # test-runner her koşuda eski koşu dizinlerini siler (`TP_RUNS_KEEP`): kayıtlar hemen uydurulur.
    _budananlari_isle(engine)
    return sonuc


def _budananlari_isle(engine: Any) -> int:
    """Silinmiş koşu dizinlerini işaretler; hata işi/açılışı düşürmez."""
    try:
        with Session(engine) as session, session.begin():
            n = service.mark_pruned_runs(session)
    except Exception:
        logging.getLogger(__name__).exception("budanmış koşu dizinleri işaretlenemedi")
        return 0
    if n:
        logging.getLogger(__name__).info("%d koşunun artefakt dizini silinmiş: işaretlendi", n)
    return n


@job_handler(service.JOB_GITHUB_POLL, max_deneme=5, backoff_s=15.0, zaman_asimi_s=600)
def ci_github_poll(ctx: JobContext) -> dict[str, Any]:
    run_id = _run_id(ctx)
    try:
        return service.github_poll(get_engine(), run_id, int((ctx.yuk or {}).get("tur") or 0))
    except PermanentJobError:
        raise
    except Exception as exc:
        if ctx.son_deneme:
            service.finalize_error(get_engine(), run_id, f"GitHub sonucu alınamadı: {exc}")
        raise


@job_handler(service.JOB_NIGHTLY, max_deneme=3, backoff_s=60.0, zaman_asimi_s=120)
def ci_nightly(ctx: JobContext) -> dict[str, Any]:
    tarih = str((ctx.yuk or {}).get("tarih") or "")
    if not tarih:
        raise PermanentJobError("gece işi yükünde tarih yok")
    return service.nightly_job(get_engine(), tarih)


@job_handler(service.JOB_ZAMAN_ASIMI, max_deneme=2, backoff_s=60.0, zaman_asimi_s=120)
def ci_zaman_asimi(ctx: JobContext) -> dict[str, Any]:
    """Sırada / sürüyor kalan koşuları zaman aşımıyla kapatır; sonraki taramayı planlar."""
    engine = get_engine()
    try:
        return service.timeout_sweep_job(engine)
    finally:
        # Zincir kopmasın: tarama hata verse de sonraki tarama planlanır (bu iş artık `running`).
        with engine.begin() as conn:
            service.plan_timeout_sweep(conn)


def on_worker_start(conn: Connection) -> None:
    """Worker açılışı: işi bitmiş ama `queued/running`'de kalmış koşular `error` olur; sonraki
    gece koşusu planlı değilse planlanır (idempotent anahtar: `ci.nightly:<tarih>`)."""
    with Session(bind=conn, join_transaction_mode="rollback_only") as session:
        n = service.sweep_stuck_runs(session)
        session.commit()
    if n:
        logging.getLogger(__name__).info("yarıda kalan %d CI koşusu error olarak kapatıldı", n)
    service.plan_nightly(conn)
    # Takılı koşu zaman aşımı (TP_CI_KOSU_ZAMAN_ASIMI_S, varsayılan 6 saat): açılışta bir kez,
    # sonra periyodik iş zinciri.
    try:
        with Session(bind=conn, join_transaction_mode="create_savepoint") as session:
            n = service.timeout_stale_runs(session)
            session.commit()
        if n:
            logging.getLogger(__name__).info("%d koşu zaman aşımıyla kapatıldı", n)
        service.plan_timeout_sweep(conn)
    except Exception:
        logging.getLogger(__name__).exception("koşu zaman aşımı taraması başarısız")
    # Kendi savepoint'inde: hata açılışın diğer işlerini (tarama, gece planı) geri almaz.
    try:
        with Session(bind=conn, join_transaction_mode="create_savepoint") as session:
            n = service.mark_pruned_runs(session)
            session.commit()
    except Exception:
        logging.getLogger(__name__).exception("budanmış koşu dizinleri işaretlenemedi")
        n = 0
    if n:
        logging.getLogger(__name__).info("%d koşunun artefakt dizini silinmiş: işaretlendi", n)
