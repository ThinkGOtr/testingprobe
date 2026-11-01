"""Bug taslağı ve kaydı (TEKNIK-TASARIM §2 adım 12–14, §8.12).

Şeritlere açık arayüz:

- `create_draft_from_failure(session, failure_id) -> draft_id` — triage (gerçek defect).
- `adopt_draft(session, draft_id) -> bool` — tutarlılık bulgusu `code_defect` taslağını hatta alır.
- `publish_bug(draft_id)` — onaylı taslağı Jira'ya yazar (worker işi `bugs.publish`).
"""

from tp_core.features.bugs.service import (
    PREPARE_JOB,
    PUBLISH_JOB,
    adopt_draft,
    create_draft_from_failure,
    publish_bug,
)

__all__ = [
    "PREPARE_JOB",
    "PUBLISH_JOB",
    "adopt_draft",
    "create_draft_from_failure",
    "publish_bug",
]
