"""Maliyet tavanı (TEKNIK-TASARIM §8.8): günlük ve iş akışı başına USD, `ai_call.maliyet`'ten.

Model geçidi tavanları kendisi uygular (`gateway.store.PgSpendLedger`, aynı SQL) ve aşımda
`tp_core.gateway.BudgetExceeded` fırlatır; iş yürütücüsü (`workflow.jobs.process_one`) bunu yakalar,
işi yeniden denemeden `failed` yazar ve iş akışını `pause_for_budget()` ile `paused` yapar.
`assert_budget()` / `enforce_budget()` API tarafının (ör. iş başlatmadan önce) kontrolüdür; buradaki
`BudgetExceeded` geçidinkinin alt sınıfıdır, iki yol da tek `except` ile yakalanır.
Gün sınırı UTC'dir. REPLAY çağrılarının maliyeti 0 yazılır, bütçeyi tüketmez.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from tp_core.config import get_settings
from tp_core.gateway.errors import BudgetExceeded as GatewayBudgetExceeded


class BudgetExceeded(GatewayBudgetExceeded):
    status_code = 402

    def __init__(self, status: BudgetStatus) -> None:
        Exception.__init__(self, status.reason or "bütçe aşıldı")
        self.status = status
        akis = status.workflow_spent is not None and status.workflow_spent > status.workflow_limit
        self.scope = "workflow" if akis else "daily"
        harcanan = status.workflow_spent if akis else status.daily_spent
        self.spent_usd = float(harcanan or 0)
        self.cap_usd = float(status.workflow_limit if akis else status.daily_limit)


@dataclass(frozen=True)
class BudgetStatus:
    daily_spent: Decimal
    daily_limit: Decimal
    workflow_spent: Decimal | None
    workflow_limit: Decimal
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.reason is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "daily_spent_usd": str(self.daily_spent),
            "daily_limit_usd": str(self.daily_limit),
            "workflow_spent_usd": None if self.workflow_spent is None else str(self.workflow_spent),
            "workflow_limit_usd": str(self.workflow_limit),
            "reason": self.reason,
        }


def daily_spend_usd(conn: Connection, gun: date | None = None) -> Decimal:
    gun = gun or datetime.now(UTC).date()
    bas = datetime.combine(gun, time.min, tzinfo=UTC)
    return Decimal(
        conn.execute(
            text(
                "SELECT COALESCE(SUM(maliyet), 0) FROM ai_call "
                "WHERE olusturma >= :bas AND olusturma < :bit"
            ),
            {"bas": bas, "bit": bas + timedelta(days=1)},
        ).scalar_one()
    )


def workflow_spend_usd(conn: Connection, workflow_id: uuid.UUID) -> Decimal:
    return Decimal(
        conn.execute(
            text("SELECT COALESCE(SUM(maliyet), 0) FROM ai_call WHERE workflow_id = :w"),
            {"w": workflow_id},
        ).scalar_one()
    )


def budget_status(
    conn: Connection,
    workflow_id: uuid.UUID | None = None,
    *,
    daily_limit: float | None = None,
    workflow_limit: float | None = None,
    planned_usd: float = 0.0,
) -> BudgetStatus:
    """Sınır aşıldı mı? Harcama ≥ sınır veya harcama + planlanan > sınır ise aşım."""

    def _d(deger: float | None, varsayilan: float) -> Decimal:
        return Decimal(str(deger if deger is not None else varsayilan))

    gunluk_sinir = _d(daily_limit, get_settings().daily_budget_usd if daily_limit is None else 0)
    akis_sinir = _d(
        workflow_limit, get_settings().workflow_budget_usd if workflow_limit is None else 0
    )
    plan = Decimal(str(planned_usd))
    gunluk = daily_spend_usd(conn)
    akis = workflow_spend_usd(conn, workflow_id) if workflow_id is not None else None
    neden = None
    if gunluk >= gunluk_sinir or gunluk + plan > gunluk_sinir:
        neden = f"günlük AI bütçesi aşıldı ({gunluk} / {gunluk_sinir} USD)"
    elif akis is not None and (akis >= akis_sinir or akis + plan > akis_sinir):
        neden = f"iş akışı AI bütçesi aşıldı ({akis} / {akis_sinir} USD)"
    return BudgetStatus(gunluk, gunluk_sinir, akis, akis_sinir, neden)


def assert_budget(
    conn: Connection, workflow_id: uuid.UUID | None = None, **kw: Any
) -> BudgetStatus:
    durum = budget_status(conn, workflow_id, **kw)
    if not durum.ok:
        raise BudgetExceeded(durum)
    return durum


def pause_for_budget(
    session: Session, workflow_id: uuid.UUID, reason: str, actor: str = "system"
) -> bool:
    """Koşan iş akışını bütçe aşımıyla `paused` yapar (denetimli). Duraklattıysa True.

    Çağıran işlemi commit eder. Zaten duraklamış/bitmiş akışa dokunmaz (idempotent).
    """
    from tp_core.models import WorkflowInstance
    from tp_core.workflow.service import transition

    wf = session.get(WorkflowInstance, workflow_id)
    if wf is None or wf.durum != "running":
        return False
    transition(session, wf, "paused", actor, "running", sebep=reason)
    return True


def enforce_budget(
    session: Session, workflow_id: uuid.UUID, actor: str = "system", **kw: Any
) -> BudgetStatus:
    """Aşım varsa iş akışını `paused` yapar (aynı işlemde, denetimli) ve `BudgetExceeded` fırlatır.

    Çağıran, istisnayı yakaladıktan sonra işlemi commit etmelidir ki duraklatma kalıcı olsun.
    """
    durum = budget_status(session.connection(), workflow_id, **kw)
    if durum.ok:
        return durum
    pause_for_budget(session, workflow_id, durum.reason or "bütçe aşıldı", actor)
    raise BudgetExceeded(durum)
