"""Ekilmiş hata koşusu işi (core-worker; `discover()` yükler). Model çağrısı yoktur.

- `hata_kosusu.calistir`: seçilen platformlarda temel → her hata → kapanış (uzun şerit). İş süre
  sınırı koşu başına satıra yazılır (`service.is_zaman_asimi_s`: adım × `/check` zaman aşımı +
  pay); buradaki kayıt yalnızca satırda değer yoksa geçerli alt sınırdır.
- `on_worker_start`: işi bitmiş ama `queued/running`'de kalmış koşular `failed` olur.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from tp_core.features.hata_kosusu import service
from tp_core.workflow.jobs import UZUN_SERIT, JobContext, job_handler


@job_handler(
    service.JOB,
    max_deneme=1,
    zaman_asimi_s=service.is_zaman_asimi_s(3),
    serit=UZUN_SERIT,
)
def calistir(ctx: JobContext) -> dict[str, Any]:
    return service.calistir(ctx)


def on_worker_start(conn: Connection) -> None:
    with Session(bind=conn, join_transaction_mode="rollback_only") as session:
        n = service.kurtar_hepsi(session)
        session.commit()
    if n:
        logging.getLogger(__name__).info("yarıda kalan %d ekilmiş hata koşusu kapatıldı", n)
