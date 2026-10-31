"""Gereksinim özelliğinin worker işleri (`@job_handler`; worker `discover()` ile yükler).

- `requirements.review`           ön inceleme (model çağrısı + Jira yorumu/etiketi); ardından
                                   tutarlılık denetimini kuyruğa ekler. Yeniden denenebilir:
                                   model çağrısı `call_id` ile, Jira yazımı `external_ref` ile
                                   idempotenttir.
- `requirements.consistency`      tutarlılık denetimi ajanı + deterministik kanıt doğrulaması.
                                   Ajan işi: `max_deneme=1` (§8.1).
- `requirements.apply_doc_fixes`  onaylı düzeltmeleri Jira'ya/belgeye yazar, yeniden kontrol.
- `requirements.po_request`       belge son hal (Jira yolu): PO'ya soru yorumu + `tp-po-pending`;
                                   son halden önce konmuş `tp-po-approved` kaldırılır.
- `requirements.po_poll`          Jira PO etiketi sorgusu (pending_po … done: geri çekilme de
                                   izlenir), takılı iş süpürmesi (bağlı etkin işi olmayan
                                   in_review/generating → failed) ve eski sorgu satırlarının
                                   temizliği; izlenecek gereksinim varsa kendini `TP_PO_POLL_S`
                                   (15 sn) sonrasına yeniden planlar.

Kalıcı hata (son deneme, şema/replay hatası, akış kuralı) gereksinimi `in_review → failed`
yapar; bütçe aşımı iş akışını duraklatır (çekirdek kuralı) ve gereksinim de `failed` olur.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.engine import Connection

from tp_core.db import get_engine
from tp_core.features.requirements import flow
from tp_core.gateway import GatewayError, ReplayMiss, ReplayNoOutput, ReplayNotFound
from tp_core.gateway.errors import BudgetExceeded
from tp_core.workflow.jobs import JobContext, PermanentJobError, job_handler


def _kalici(exc: BaseException, ctx: JobContext) -> bool:
    if isinstance(exc, PermanentJobError | BudgetExceeded | flow.WorkflowError):
        return True
    if isinstance(exc, GatewayError) and not _gecici(exc):
        return True
    return ctx.son_deneme


def _gecici(exc: BaseException) -> bool:
    from tp_core.gateway import ProviderTransientError

    return isinstance(exc, ProviderTransientError)


def _hata_metni(exc: BaseException) -> str:
    if isinstance(exc, ReplayMiss):
        return (
            "Kayıtlı REPLAY bu girdiyle eşleşmiyor (TP_REPLAY_STRICT=1, prova kipi); canlı model "
            "olmadan işlem yapılmadı"
        )
    if isinstance(exc, ReplayNoOutput):
        return str(exc).strip() or type(exc).__name__
    if isinstance(exc, ReplayNotFound):
        return (
            "Bu girdi için kayıtlı REPLAY çıktısı yok ve canlı model yapılandırılmamış "
            "(ANTHROPIC_API_KEY); işlem yapılmadı"
        )
    metin = str(exc).strip()
    return f"{type(exc).__name__}: {metin}" if metin else type(exc).__name__


def _requirement_job(
    fn: Callable[[Any, uuid.UUID, dict[str, Any]], dict[str, Any]],
) -> Callable[[JobContext], dict[str, Any]]:
    def calistir(ctx: JobContext) -> dict[str, Any]:
        yuk = dict(ctx.yuk or {})
        if "workflow_id" not in yuk and ctx.workflow_id is not None:
            yuk["workflow_id"] = str(ctx.workflow_id)
        try:
            return fn(get_engine(), ctx.job_id, yuk)
        except Exception as exc:
            if _kalici(exc, ctx):
                flow.mark_failed(uuid.UUID(str(yuk["requirement_id"])), _hata_metni(exc))
                if isinstance(exc, BudgetExceeded | PermanentJobError):
                    raise
                raise PermanentJobError(_hata_metni(exc)) from exc
            raise

    calistir.__name__ = fn.__name__
    return calistir


job_handler(flow.JOB_REVIEW, max_deneme=3, backoff_s=5.0, zaman_asimi_s=600)(
    _requirement_job(flow.run_pre_review)
)
job_handler(flow.JOB_CONSISTENCY, max_deneme=1, zaman_asimi_s=900)(
    _requirement_job(flow.run_consistency)
)
job_handler(flow.JOB_APPLY, max_deneme=3, backoff_s=5.0, zaman_asimi_s=300)(
    _requirement_job(flow.run_apply)
)
# Gereksinim pending_po'dadır; `mark_failed` yalnızca in_review'a dokunur (onay kapısı etkilenmez).
job_handler(flow.JOB_PO_REQUEST, max_deneme=5, backoff_s=5.0, zaman_asimi_s=120)(
    _requirement_job(flow.run_po_request)
)


@job_handler(flow.JOB_PO_POLL, max_deneme=1, zaman_asimi_s=120)
def po_poll(_ctx: JobContext) -> dict[str, Any]:
    engine = get_engine()
    try:
        return flow.run_po_poll(engine)
    except Exception:
        # Sorgu zinciri kopmasın: hata olsa da bir sonraki tur planlanır (bekleyen varsa).
        flow.reschedule_po_poll(engine)
        raise


def on_worker_start(conn: Connection) -> None:
    """Worker açılışı: PO etiket sorgusu kuyrukta yoksa ekle (iş tablosu silinmiş olabilir).

    Sorgu hemen koşar ve önce takılı iş süpürmesini yapar: önceki worker sürecinden kalan
    (`release_orphans` ile `failed` olan) işin gereksinimi `in_review`/`generating`'de kalmaz.
    """
    flow.ensure_po_poll(conn)
