"""Kod üretimi işleri (core-worker). Ajan işi yeniden denenmez (§8.1: `maximum_attempts=1`).

- `codegen.generate` / `codegen.break_verify` / `codegen.merge`: CasesToCode akışı.
- `codegen.update_branch`: main ilerleyince açık PR dalını günceller (yeni head → PR CI).
- `codegen.pr_close`: insan reddi / değişiklik isteği sonrası PR'a yorum + kapatma.
- `codegen.otomatik` (013 K16): toplu onayda onaylanan case'lerin otomatik web kod üretimi;
  `MAX_CASE`'lik parçalarla `start_generation` (`features/otomasyon/otokod.py:toplu_uret`).
- `codegen.pr_sync`: GitHub kipinde açık PR'ların forge durumunu (GitHub arayüzünde merge/kapatma)
  çekirdeğe işler ve kendini `TP_CODEGEN_PR_SYNC_S` (60 sn) sonrasına yeniden planlar.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Connection
from sqlalchemy.orm import Session

from tp_core.db import get_engine
from tp_core.features.codegen import service
from tp_core.features.codegen.toolchain import varsayilan_check_timeout_s
from tp_core.features.otomasyon import otokod
from tp_core.workflow.jobs import JobContext, job_handler

# İş zaman aşımı, içindeki /check çağrılarının istemci zaman aşımından türetilir (CI şeridinin
# toolchain zinciri, `check_timeout_s()`); aksi halde en kötü durumda worker işi öldürür.
AJAN_BUTCESI_S = 900  # doğrulama ajanı (≤25 araç çağrısı, iki tur) + sembol tablosu + forge
URETIM_KONTROL_SAYISI = 2  # yerel kontrol + tek yeniden eşleme turunun kontrolü
KIRMA_KONTROL_SAYISI = 3  # başlangıç (yeşil) + kırık (kırmızı) + geri alınmış (yeşil)
URETIM_ZAMAN_ASIMI_S = int(AJAN_BUTCESI_S + URETIM_KONTROL_SAYISI * varsayilan_check_timeout_s())
KIRMA_ZAMAN_ASIMI_S = int(120 + KIRMA_KONTROL_SAYISI * varsayilan_check_timeout_s())


@job_handler(service.GEN_JOB, max_deneme=1, zaman_asimi_s=URETIM_ZAMAN_ASIMI_S)
def generate(ctx: JobContext) -> dict[str, Any]:
    return service.run_generation(ctx, get_engine())


@job_handler(service.BREAK_JOB, max_deneme=1, zaman_asimi_s=KIRMA_ZAMAN_ASIMI_S)
def break_verify(ctx: JobContext) -> dict[str, Any]:
    return service.run_break_verify(ctx, get_engine())


@job_handler(service.MERGE_JOB, max_deneme=1, zaman_asimi_s=120)
def merge(ctx: JobContext) -> dict[str, Any]:
    return service.run_merge(ctx, get_engine())


@job_handler(service.UPDATE_JOB, max_deneme=1, zaman_asimi_s=120)
def update_branch(ctx: JobContext) -> dict[str, Any]:
    return service.run_update_branch(ctx, get_engine())


@job_handler(service.PR_CLOSE_JOB, max_deneme=3, zaman_asimi_s=60)
def pr_close(ctx: JobContext) -> dict[str, Any]:
    return service.run_pr_close(ctx, get_engine())


@job_handler(otokod.JOB_OTOMATIK_KOD, max_deneme=3, backoff_s=10.0, zaman_asimi_s=600)
def otomatik(ctx: JobContext) -> dict[str, Any]:
    return otokod.toplu_uret(dict(ctx.yuk or {}), job_id=ctx.job_id, son_deneme=ctx.son_deneme)


@job_handler(service.PR_SYNC_JOB, max_deneme=1, zaman_asimi_s=300)
def pr_sync(ctx: JobContext) -> dict[str, Any]:
    return service.run_pr_sync(ctx, get_engine())


def on_worker_start(conn: Connection) -> None:
    """Worker açılışı: takılı script'ler / kırarak doğrulamalar temizlenir, eski ekran görüntüleri
    silinir (kapalı/başarısız script'ler, `TP_CODEGEN_SCREENSHOT_DAYS`), GitHub kipinde PR senkronu
    planlanır."""
    log = logging.getLogger(__name__)
    with Session(bind=conn, join_transaction_mode="rollback_only") as session:
        n = service.sweep_stuck(session)
        session.commit()
        try:
            silinen = service.prune_screenshots(session)
        except Exception:  # saklama temizliği açılışı durdurmaz
            log.warning("ekran görüntüsü temizliği yapılamadı", exc_info=True)
            silinen = 0
    if n:
        log.info("takılı %d kod üretimi kaydı temizlendi", n)
    if silinen:
        log.info("%d script'in ekran görüntüleri silindi (saklama süresi doldu)", silinen)
    service.plan_pr_sync(conn)
