"""Karar tablosu worker işleri (`@job_handler`; worker `discover()` ile yükler).

- `karar_tablosu.draft`  AI taslağı: PO onaylı gereksinim bloğu + PO cevapları → model
                         (`decision_table_draft`) → doğrulanmış tablolar ve ilişkiler `draft`.
                         Model çağrısı `deterministic_call_id` ile yeniden denemede tekrarlanmaz;
                         yazım tek işlemdedir (iş akışı `done` olunca yeniden deneme atlanır).

Bu şerit `oracle.check_requirement` işini yalnız kuyruğa ekler (tablo onaylanınca / onaylı tablo
yeniden açılınca ya da geçersiz kılınınca); işleyicisi oracle şeridindedir.
"""

from __future__ import annotations

from typing import Any

from tp_core.db import get_engine
from tp_core.features.karar_tablosu.service import DRAFT_JOB, taslak_calistir
from tp_core.workflow.jobs import JobContext, job_handler


@job_handler(DRAFT_JOB, max_deneme=2, zaman_asimi_s=600)
def karar_tablosu_taslagi(ctx: JobContext) -> dict[str, Any]:
    return taslak_calistir(ctx, get_engine())
