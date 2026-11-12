"""Oracle işleri (core-worker; 012 ANALIZ §4.3 "Ne zaman koşar").

- `oracle.check_case` `yuk={case_id, icerik_hash, icerik?}`: tek içeriğin kontrolü (`icerik`
  önerilen düzeltme içeriğidir; case'e yazılmaz).
- `oracle.check_requirement` `yuk={requirement_id, neden}`: gereksinimin `draft` / `approved`
  case'leri için `oracle.check_case` açar. Case üretimi sonunda ve (Ş1) tablo onaylanınca /
  değişince kuyruğa alınır.
"""

from __future__ import annotations

from typing import Any

from tp_core.db import get_engine
from tp_core.features.oracle.service import (
    CHECK_CASE_JOB,
    CHECK_REQUIREMENT_JOB,
    run_check_case,
    run_check_requirement,
)
from tp_core.workflow.jobs import JobContext, job_handler


@job_handler(CHECK_CASE_JOB, max_deneme=3, zaman_asimi_s=300)
def check_case(ctx: JobContext) -> dict[str, Any]:
    return run_check_case(ctx, get_engine())


@job_handler(CHECK_REQUIREMENT_JOB, max_deneme=3, zaman_asimi_s=120)
def check_requirement(ctx: JobContext) -> dict[str, Any]:
    return run_check_requirement(ctx)
