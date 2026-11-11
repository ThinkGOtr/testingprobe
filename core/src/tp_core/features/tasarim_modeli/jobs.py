"""`model.generate` işi (core-worker): iki turun ilk turu — test tasarım modeli üretimi."""

from __future__ import annotations

from typing import Any

from tp_core.db import get_engine
from tp_core.features.cases.model_service import MODEL_JOB, run_model_generation
from tp_core.workflow.jobs import JobContext, job_handler


@job_handler(MODEL_JOB, max_deneme=2, zaman_asimi_s=600)
def generate_design_model(ctx: JobContext) -> dict[str, Any]:
    return run_model_generation(ctx, get_engine())
