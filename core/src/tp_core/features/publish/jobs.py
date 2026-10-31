"""`publish.cases` işi (core-worker): Jira/Xray yazma kimlikleri yalnızca burada."""

from __future__ import annotations

from typing import Any

from tp_core.db import get_engine
from tp_core.features.publish.service import PUBLISH_JOB, run_publish
from tp_core.workflow.jobs import JobContext, job_handler


@job_handler(PUBLISH_JOB, max_deneme=3, zaman_asimi_s=600)
def publish_cases(ctx: JobContext) -> dict[str, Any]:
    return run_publish(ctx, get_engine())
