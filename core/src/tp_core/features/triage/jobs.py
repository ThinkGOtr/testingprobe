"""Triage işleri (core-worker; `discover()` yükler). AI yalnızca kural eşleşmezse (XI).

- `triage.classify` bir kırmızı koşunun başarısız testlerini sınıflandırır (koşu başına tek iş,
  idempotens `triage.classify:<run_id>`). Kod üretimi kontrol kaydı henüz yazılmadıysa
  (`TriageBekle`) kısa aralıkla yeniden denenir.
- `triage.sweep` triage'ı yapılmamış son kırmızı koşuları kuyruğa ekler ve kendini
  `TP_TRIAGE_SWEEP_S` (30 sn; 0 = kapalı) sonrasına yeniden planlar. Kanca bağlıysa (ci / codegen
  `on_run_finished`) yalnızca güvenlik ağıdır.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.engine import Connection

from tp_core.db import get_engine
from tp_core.features.triage import service, services
from tp_core.workflow.jobs import JobContext, PermanentJobError, job_handler

log = logging.getLogger(__name__)


def _run_id(ctx: JobContext) -> uuid.UUID:
    try:
        return uuid.UUID(str((ctx.yuk or {})["run_id"]))
    except (KeyError, ValueError) as exc:
        raise PermanentJobError("iş yükünde geçerli run_id yok") from exc


@job_handler(service.JOB_CLASSIFY, max_deneme=5, backoff_s=5.0, zaman_asimi_s=900)
def triage_classify(ctx: JobContext) -> dict[str, Any]:
    return service.classify_run(get_engine(), _run_id(ctx), son_deneme=ctx.son_deneme)


@job_handler(service.JOB_SWEEP, max_deneme=1, zaman_asimi_s=120)
def triage_sweep(_ctx: JobContext) -> dict[str, Any]:
    engine = get_engine()
    try:
        sonuc = service.sweep(engine)
        service.purge_sweep_jobs(engine)
        return sonuc
    finally:
        # Zincir kopmasın: hata olsa da bir sonraki süpürme planlanır.
        with engine.begin() as conn:
            service.ensure_sweep(conn, gecikme_s=services.sweep_s())


def on_worker_start(conn: Connection) -> None:
    """Worker açılışı: süpürme işi kuyrukta yoksa eklenir (hemen koşar: kaçan koşular)."""
    service.ensure_sweep(conn)
