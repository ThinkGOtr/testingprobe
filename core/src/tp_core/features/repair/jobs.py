"""Onarım işleri (core-worker). Yeniden denenmez: yan etkili adımlar (dal, PR) idempotent
değildir; engellenen/başarısız onarım yeni istekle AYNI script üzerinde yeniden kuyruğa alınır.

- `repair.fix`: yoklama → aria doğrulaması → yama → AST koruması → tam yerel kontrol → bot PR.
- `repair.merge`: insan onaylı merge (onaylanan head'e bağlı) → push CI.

Worker açılışı (`on_worker_start`): işi bitmiş ama `pending|verifying|checking`'de kalmış onarımlar
`failed` olur (aksi halde tüm kardeş hatalar "onarım zaten sürüyor" der); forge'da merge edilmiş
ama DB'de `pr_open` kalan onarımlar uzlaştırılır (push CI kuyruğa alınır).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Connection
from sqlalchemy.orm import Session

from tp_core.db import get_engine
from tp_core.features.repair import service
from tp_core.workflow.jobs import JobContext, job_handler

log = logging.getLogger(__name__)


def _fix_zaman_asimi() -> int:
    """Sembol + yoklama + AST + bir tam `/check` (CI istemci zaman aşımı) + pay."""
    from tp_core.features.ci.clients import check_timeout_s

    return int(600 + check_timeout_s())


@job_handler(service.FIX_JOB, max_deneme=1, zaman_asimi_s=_fix_zaman_asimi())
def fix(ctx: JobContext) -> dict[str, Any]:
    return service.run_fix(ctx, get_engine())


@job_handler(service.MERGE_JOB, max_deneme=1, zaman_asimi_s=120)
def merge(ctx: JobContext) -> dict[str, Any]:
    return service.run_merge(ctx, get_engine())


def on_worker_start(conn: Connection) -> None:
    with Session(bind=conn, join_transaction_mode="rollback_only") as session:
        n = service.sweep_stuck(session)
        session.commit()
    if n:
        log.warning("yarıda kalmış %d locator onarımı 'failed' yapıldı", n)
    try:
        m = service.reconcile_merged()
    except Exception:  # forge erişilemezse açılış durmaz; merge isteği yine uzlaştırır
        log.warning("onarım merge uzlaştırması yapılamadı", exc_info=True)
        m = 0
    if m:
        log.warning("forge'da merge edilmiş %d onarım uzlaştırıldı", m)
