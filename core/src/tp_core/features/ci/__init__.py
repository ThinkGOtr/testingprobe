"""Yerel CI, koşu sonuçları ve artefaktlar (TEKNIK-TASARIM §8.5, §8.11; MIMARI-SOZLESME §5).

Genel API (diğer şeritler):

    from tp_core.features.ci import enqueue_ci
    run_id = enqueue_ci(session, sha, "pr", pr_number=12)   # PR açıldı/güncellendi
    run_id = enqueue_ci(session, merge_sha, "push")          # merge sonrası main

Modüller: `service` (iş mantığı), `parse` (JUnit/JSON → test_result), `clients` (toolchain,
GitHub Actions), `artifacts` (artefakt sunumu), `jobs` (worker işleri), `api` (HTTP uçları),
`services` (dış bağımlılık fabrikaları; testler değiştirir).
"""

from tp_core.features.ci.service import (
    CiError,
    enqueue_ci,
    ingest_check_report,
    record_results,
)
from tp_core.models import ci_feature as ci_feature

__all__ = ["CiError", "enqueue_ci", "ingest_check_report", "record_results"]
