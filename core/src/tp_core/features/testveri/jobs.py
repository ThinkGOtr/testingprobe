"""Worker açılışı: test verisi kataloğunun tohumu (specs/013-sprint-otomasyonu §3.3).

İş işleyicisi yoktur; `on_worker_start` katalogda olmayan tohum anahtarlarını ekler (idempotent).
core-worker demo DB'yi (`DEMOAPP_RO_DATABASE_URL`) okuyabildiği için bayi/ürün/kampanya/ayar
kayıtları burada dolar; `make seed` (core-api) yalnız sabitleri ekleyebilir.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection
from sqlalchemy.orm import Session

from tp_core.features.testveri.service import tohumla

log = logging.getLogger(__name__)


def on_worker_start(conn: Connection) -> None:
    with Session(bind=conn, join_transaction_mode="rollback_only") as session:
        n = tohumla(session)
        session.commit()
    if n:
        log.info("test verisi kataloğuna %d tohum kaydı eklendi", n)
