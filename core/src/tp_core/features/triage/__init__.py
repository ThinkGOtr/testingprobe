"""Triage — FailureToFix sınıflandırması (TEKNIK-TASARIM §8.6; MIMARI-SOZLESME §5 `/failures`).

Genel API (diğer şeritler):

    from tp_core.features.triage import on_run_finished, enqueue_classify
    on_run_finished(session, run)          # ci / codegen: koşu bittiğinde (kırmızıysa iş ekler)
    enqueue_classify(conn, run_id)         # doğrudan kuyruğa ekleme (idempotent)

    from tp_core.features.triage import get_failure, locator_proposal
    locator_proposal(session, failure_id)  # repair: {locator_key, old_testid, new_testid, …}

Modüller: `rules` (deterministik kurallar, saf), `evidence` (güvenli kanıt okuma: run.json,
error-context, trace.zip), `service` (iş akışı, LLM yedeği, kayıt, görünüm), `services` (dış
bağımlılık fabrikaları), `jobs` (worker işleri), `api` (HTTP uçları).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from tp_core.features.triage.service import (
    JOB_CLASSIFY,
    JOB_SWEEP,
    classify_run,
    enqueue_classify,
    get_failure,
    list_failures,
    on_run_finished,
)
from tp_core.models import triage_feature as triage_feature


def locator_proposal(session: Session, failure_id: uuid.UUID) -> dict[str, Any] | None:
    """Repair şeridi için saklanan locator onarım önerisi (yoksa None).

    Anahtarlar: `locator_key` (ör. `catalog.addToCart`), `old_testid`, `new_testid`, `dosya`
    (e2e köküne göre `pages/catalog/locators.ts`), `rol`, `ad`, `within`, `scope_test_id`,
    `url_path`, `sha` (koşulan commit), `probe` (locator yoklamasının dört sha alanı dahil),
    `aria_satirlari`, `son_yesil_run_id`, `trace_dom` (trace DOM değerlendirmesi; `destekliyor`
    false ise eşleşen sinyal değildir).
    """
    from tp_core.models import Failure

    f = session.get(Failure, failure_id)
    if f is None or f.sinif != "test_maintenance" or f.alt_tur != "locator":
        return None
    ek = session.get(triage_feature.FailureEk, failure_id)
    return dict(ek.oneri) if ek is not None and ek.oneri else None


__all__ = [
    "JOB_CLASSIFY",
    "JOB_SWEEP",
    "classify_run",
    "enqueue_classify",
    "get_failure",
    "list_failures",
    "locator_proposal",
    "on_run_finished",
]
