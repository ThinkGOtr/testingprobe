"""Ekilmiş hata koşusu işleri (core-worker; `discover()` yükler). Model çağrısı yoktur.

- `hata_kosusu.calistir`: koşunun bir adımı (uzun şerit). İlk `bekliyor` adımı koşar, sonucu yazar
  ve sonraki adımın işini kuyruğa alır; uzun şerit adımlar arasında serbest kalır. `max_deneme=2`:
  worker yarıda kalırsa adım bir kez daha koşar. Süre sınırı adım başınadır
  (`service.adim_zaman_asimi_s`).
- `hata_kosusu.tarama`: süren ama işi kalmamış koşuları kapatır (`service.kurtar_hepsi`); süren
  koşu kaldıkça `service.TARAMA_S` sonrasına yeniden planlanır. `baslat` ve worker açılışı planlar.
- `on_worker_start`: aynı kapatma + süren koşu varsa taramayı planlar.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from tp_core.db import get_engine
from tp_core.features.hata_kosusu import service
from tp_core.workflow.jobs import UZUN_SERIT, JobContext, job_handler

log = logging.getLogger(__name__)


@job_handler(
    service.JOB,
    max_deneme=service.ADIM_DENEME,
    backoff_s=5.0,
    zaman_asimi_s=service.adim_zaman_asimi_s(),
    serit=UZUN_SERIT,
)
def calistir(ctx: JobContext) -> dict[str, Any]:
    return service.calistir(ctx)


@job_handler(service.JOB_TARAMA, max_deneme=1, zaman_asimi_s=120)
def tarama(_ctx: JobContext) -> dict[str, Any]:
    sonuc: dict[str, Any] = {"devam": True}
    try:
        sonuc = service.tara()
        return sonuc
    finally:
        # Zincir kopmasın: hata olsa da süren koşu varken tarama yeniden planlanır.
        if sonuc.get("devam"):
            with get_engine().begin() as conn:
                service.tarama_planla(conn)


def on_worker_start(conn: Connection) -> None:
    with Session(bind=conn, join_transaction_mode="rollback_only") as session:
        n = service.kurtar_hepsi(session)
        devam = service.suren_var(session)
        session.commit()
    if devam:
        service.tarama_planla(conn, gecikme_s=0)
    if n:
        log.info("yarıda kalan %d ekilmiş hata koşusu kapatıldı", n)
