"""`cases.generate` ve `cases.deepen` işleri (core-worker): model geçidiyle case üretimi ve
derinleştirme (011 P5/P6)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Connection
from sqlalchemy.orm import Session

from tp_core.db import get_engine
from tp_core.features.cases.deepen import DEEPEN_JOB, run_deepening
from tp_core.features.cases.service import GEN_JOB, run_generation, sweep_stuck_generations
from tp_core.workflow.jobs import JobContext, job_handler

log = logging.getLogger(__name__)


@job_handler(GEN_JOB, max_deneme=2, zaman_asimi_s=600)
def generate_cases(ctx: JobContext) -> dict[str, Any]:
    return run_generation(ctx, get_engine())


@job_handler(DEEPEN_JOB, max_deneme=2, zaman_asimi_s=600)
def deepen_cases(ctx: JobContext) -> dict[str, Any]:
    return run_deepening(ctx, get_engine())


def on_worker_start(conn: Connection) -> None:
    """Worker açılışı: iş dışı çöküşle (`release_orphans`) `generating`'de kalanları `failed` yap.

    Asıl kurtarma `start_generation`'dadır (yeniden başlatmada); bu tarama portalda takılı
    görünmesini de önler.
    """
    with Session(bind=conn, join_transaction_mode="rollback_only") as session:
        n = sweep_stuck_generations(session)
        session.commit()
    if n:
        log.info("generating'de kalan %d gereksinim failed'a alındı", n)
