"""Karar tablosu worker işleri (`@job_handler`; worker `discover()` ile yükler).

- `karar_tablosu.draft`  AI taslağı: PO onaylı gereksinim bloğu + PO cevapları → model
                         (`decision_table_draft`) → doğrulanmış tablolar ve ilişkiler `draft`.
                         Model çağrısı `deterministic_call_id` ile yeniden denemede tekrarlanmaz;
                         yazım tek işlemdedir (iş akışı `done` olunca yeniden deneme atlanır).

Hata metni: işin `son_hata`'sı portalda görünür (`son_taslak`). Ham istisna metni iç ayrıntı
taşıyabileceği için işleyici ayrıntıyı denetime (`karar_tablosu.draft_failed`) yazar ve işi
sınıflandırılmış metinle (`service.TASLAK_HATALARI`) bitirir; istisna türü (kalıcı / bütçe /
yeniden denenebilir) korunur.

Bu şerit `oracle.check_requirement` işini yalnız kuyruğa ekler (tablo onaylanınca / onaylı tablo
yeniden açılınca ya da geçersiz kılınınca); işleyicisi oracle şeridindedir.
"""

from __future__ import annotations

import logging
from typing import Any

from tp_core.audit import audit_on_commit
from tp_core.db import get_engine
from tp_core.features.karar_tablosu.service import DRAFT_JOB, TASLAK_HATALARI, taslak_calistir
from tp_core.gateway.errors import BudgetExceeded as GecitButcesiAsildi
from tp_core.models import session_scope
from tp_core.workflow.budget import BudgetExceeded
from tp_core.workflow.jobs import JobContext, PermanentJobError, job_handler

log = logging.getLogger(__name__)

_MODEL_MODULLERI = ("tp_core.gateway", "anthropic", "httpx", "jsonschema")


def hata_kodu(exc: BaseException) -> str:
    """İstisna → `TASLAK_HATALARI` anahtarı."""
    if isinstance(exc, PermanentJobError):
        return "gereksinim_degisti"
    if isinstance(exc, GecitButcesiAsildi):  # iş akışı bütçesi de bunun alt sınıfıdır
        return "butce_asildi"
    modul = type(exc).__module__ or ""
    if modul.startswith(_MODEL_MODULLERI):
        return "model_hatasi"
    return "ic_hata"


def _hatayi_denetle(ctx: JobContext, exc: BaseException, kod: str) -> None:
    yuk = ctx.yuk or {}
    try:
        with session_scope() as s:
            audit_on_commit(
                s,
                "system",
                "karar_tablosu.draft_failed",
                f"requirement:{yuk.get('requirement_id')}",
                {
                    "job_id": str(ctx.job_id),
                    "deneme": ctx.deneme,
                    "kod": kod,
                    "tur": type(exc).__name__,
                    "hata": str(exc)[:2000],
                },
            )
    except Exception:  # denetim yazılamazsa iş yine sınıflandırılmış hatayla biter
        log.exception("karar_tablosu.draft hata denetimi yazılamadı (iş %s)", ctx.job_id)


@job_handler(DRAFT_JOB, max_deneme=2, zaman_asimi_s=600)
def karar_tablosu_taslagi(ctx: JobContext) -> dict[str, Any]:
    try:
        return taslak_calistir(ctx, get_engine())
    except BudgetExceeded as exc:
        # Bütçe istisnası olduğu gibi kalır: çalıştırıcı iş akışını duraklatır (yeniden denemez).
        _hatayi_denetle(ctx, exc, "butce_asildi")
        raise
    except Exception as exc:
        kod = hata_kodu(exc)
        _hatayi_denetle(ctx, exc, kod)
        mesaj = TASLAK_HATALARI[kod]
        if isinstance(exc, (PermanentJobError, GecitButcesiAsildi)):  # bütçe: yeniden deneme boşuna
            raise PermanentJobError(mesaj) from exc
        raise RuntimeError(mesaj) from exc
