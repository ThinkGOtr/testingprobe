"""Kendini yeniden kuyruğa koyan zamanlanmış işler pasif projede (`tp_proje.aktif=false`) koşmaz
ve zincir kendini yeniden kurmaz (pasife alınan EKRAN-TESTI projeleri her dakika Home'dan 404
alıyordu)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Engine, text

import tp_core.features.assistant.temizlik
import tp_core.features.ci.jobs
import tp_core.features.requirements.jobs
import tp_core.features.triage.jobs  # noqa: F401
from tp_core.workflow.jobs import (
    REGISTRY,
    ClaimedJob,
    HandlerSpec,
    JobContext,
    execute,
    job_handler,
)


def test_zamanlanmis_isler_periyodik_isaretli() -> None:
    for tur in (
        "requirements.jira_tetik",
        "requirements.po_poll",
        "triage.sweep",
        "ci.zaman_asimi",
        "ci.nightly",
        "assistant.cleanup",
    ):
        assert REGISTRY[tur].periyodik, tur


def test_pasif_projede_periyodik_is_atlanir(engine: Engine, iki_proje: tuple[str, str]) -> None:
    a, b = iki_proje
    cagri: list[str | None] = []
    kayit: dict[str, HandlerSpec] = {}

    @job_handler("test.periyodik", max_deneme=1, registry=kayit, periyodik=True)
    def _p(ctx: JobContext) -> dict[str, Any]:
        cagri.append(ctx.project_id)
        return {"yeniden": "kuruldu"}

    @job_handler("test.normal", max_deneme=1, registry=kayit)
    def _n(ctx: JobContext) -> None:
        cagri.append(f"normal:{ctx.project_id}")

    with engine.begin() as c:
        c.execute(text("UPDATE tp_proje SET aktif = false WHERE pid = :p"), {"p": b})

    def is_(tur: str, pid: str) -> ClaimedJob:
        return ClaimedJob(uuid.uuid4(), tur, {}, 1, 1, None, None, pid)

    s = execute(is_("test.periyodik", b), kayit)
    assert s.durum == "done" and s.deger == {"durum": "atlandi", "neden": "proje pasif"}
    assert cagri == []
    assert execute(is_("test.periyodik", a), kayit).deger == {"yeniden": "kuruldu"}
    assert cagri == [a]
    execute(is_("test.normal", b), kayit)  # periyodik olmayan iş pasif projede de koşar
    assert cagri == [a, f"normal:{b}"]
