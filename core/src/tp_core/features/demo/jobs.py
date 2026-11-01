"""Demo işleri (core-worker; forge yazma kimliği yalnızca burada).

- `demo.break_locator`: kırılma PR'ı demo-admin bypass'ıyla merge + uygulama yenileme isteği.
- `demo.reset`: main → demo-baseline, PR kapatma, uygulama yenileme, jira-sim sıfırlama.
- `demo.await_web`: çalışan uygulama main'i yansıtınca push CI (kendini yeniden planlar).
"""

from __future__ import annotations

from typing import Any

from tp_core.db import get_engine
from tp_core.features.demo import service
from tp_core.workflow.jobs import JobContext, job_handler


@job_handler(service.BREAK_JOB, max_deneme=1, zaman_asimi_s=300)
def break_locator(ctx: JobContext) -> dict[str, Any]:
    return service.run_break(ctx, get_engine())


@job_handler(service.RESET_JOB, max_deneme=1, zaman_asimi_s=300)
def reset(ctx: JobContext) -> dict[str, Any]:
    return service.run_reset(ctx, get_engine())


@job_handler(service.AWAIT_JOB, max_deneme=1, zaman_asimi_s=60)
def await_web(ctx: JobContext) -> dict[str, Any]:
    return service.run_await_web(ctx, get_engine())
