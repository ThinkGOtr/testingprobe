"""Bug şeridinin worker işleri (Jira yazma kimliği ve model anahtarı yalnızca core-worker'da).

- `bugs.prepare`     mükerrer araması (güvenli JQL) + AI sıralama (`dup_rank`) + AI taslak
                     (`bug_draft`) + deterministik düzeltmeler.
- `bugs.publish`     `publish_bug`: onaylı taslağı Jira'ya yazar (yeni Bug ya da mevcut kayda
                     bağla); idempotent (`external_ref`, `tp-<uuid>`), yeniden denenir.
- `bugs.adopt_sweep` worker açılışında hazırlık hattına girmemiş taslakları (Faz 2 tutarlılık
                     taslakları dahil) hatta alır.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, text

from tp_core.db import get_engine
from tp_core.features.bugs import service
from tp_core.workflow.jobs import JobContext, enqueue, idempotency_lock, job_handler


@job_handler(service.PREPARE_JOB, max_deneme=2, zaman_asimi_s=600)
def prepare(ctx: JobContext) -> dict[str, Any]:
    return service.run_prepare(ctx, get_engine())


@job_handler(service.PUBLISH_JOB, max_deneme=3, backoff_s=5.0, zaman_asimi_s=300)
def publish(ctx: JobContext) -> dict[str, Any]:
    return service.run_publish(ctx)


@job_handler(service.SWEEP_JOB, max_deneme=3, zaman_asimi_s=300)
def adopt_sweep(_ctx: JobContext) -> dict[str, Any]:
    return {"alinan": service.adopt_pending(get_engine())}


def on_worker_start(conn: Connection) -> None:
    """Açılışta tek süpürme işi (kuyrukta bekleyen varsa yenisi eklenmez)."""
    idempotency_lock(conn, service.SWEEP_JOB)
    bekleyen = conn.execute(
        text("SELECT 1 FROM job WHERE tur = :t AND durum IN ('queued', 'retry') LIMIT 1"),
        {"t": service.SWEEP_JOB},
    ).first()
    if bekleyen is None:
        enqueue(conn, service.SWEEP_JOB, {})
