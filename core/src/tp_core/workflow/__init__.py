"""İş akışı: durum makinesi servisi, onay kapıları, iş kuyruğu, bütçe.

Alt modüller (`states` saf veridir ve `tp_core.models` tarafından içe aktarılır; döngüsel içe
aktarmayı önlemek için bu paket dışa aktarımları tembel yükler):

- `tp_core.workflow.states`   — durum makineleri ve kapı tabloları (belgesi orada)
- `tp_core.workflow.service`  — `transition()`, `record_approval()`, `approved_hash_matches()`
- `tp_core.workflow.jobs`     — `@job_handler`, `enqueue()`, kuyruk işlemleri
- `tp_core.workflow.budget`   — günlük / iş akışı başına USD bütçesi
"""

from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    "transition": "service",
    "record_approval": "service",
    "approved_hash_matches": "service",
    "content_hash_of": "service",
    "Principal": "service",
    "WorkflowError": "service",
    "InvalidTransition": "service",
    "ConcurrentTransition": "service",
    "GateClosed": "service",
    "GuardFailed": "service",
    "job_handler": "jobs",
    "enqueue": "jobs",
    "JobContext": "jobs",
    "PermanentJobError": "jobs",
    "budget_status": "budget",
    "assert_budget": "budget",
    "BudgetExceeded": "budget",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    modul = _EXPORTS.get(name)
    if modul is None:
        raise AttributeError(name)
    return getattr(importlib.import_module(f"tp_core.workflow.{modul}"), name)
