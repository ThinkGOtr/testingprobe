"""Maliyet tavanları: iş akışı başına (varsayılan 2 USD) ve günlük (varsayılan 30 USD).

Harcama defteri (`SpendLedger`) arayüzdür: varsayılanı süreç içi; kalıcı uygulama `ai_call`
tablosundaki maliyet toplamından okur (platform şeridi). Tavan aşılırsa `BudgetExceeded` —
iş akışı duraklar ve insana sorulur (TEKNIK-TASARIM §8.8).
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from tp_core.gateway.errors import BudgetExceeded


@runtime_checkable
class SpendLedger(Protocol):
    def spent_workflow(self, workflow_id: UUID) -> float: ...
    def spent_today(self) -> float: ...
    def add(self, workflow_id: UUID | None, cost_usd: float) -> None: ...


class InMemorySpendLedger:
    def __init__(self, today: Callable[[], date] | None = None) -> None:
        self._today = today or (lambda: datetime.now(UTC).date())
        self._lock = threading.Lock()
        self._workflow: dict[UUID, float] = defaultdict(float)
        self._daily: dict[date, float] = defaultdict(float)

    def spent_workflow(self, workflow_id: UUID) -> float:
        with self._lock:
            return self._workflow.get(workflow_id, 0.0)

    def spent_today(self) -> float:
        with self._lock:
            return self._daily.get(self._today(), 0.0)

    def add(self, workflow_id: UUID | None, cost_usd: float) -> None:
        with self._lock:
            if workflow_id is not None:
                self._workflow[workflow_id] += cost_usd
            self._daily[self._today()] += cost_usd


class Budget:
    def __init__(
        self,
        *,
        workflow_cap_usd: float = 2.0,
        daily_cap_usd: float = 30.0,
        ledger: SpendLedger | None = None,
    ) -> None:
        self.workflow_cap_usd = workflow_cap_usd
        self.daily_cap_usd = daily_cap_usd
        self.ledger: SpendLedger = ledger or InMemorySpendLedger()

    def check(self, workflow_id: UUID | None, estimate_usd: float = 0.0) -> None:
        """Çağrıdan önce: harcanan + tahmini girdi maliyeti tavana ulaşıyorsa durdur."""
        today = self.ledger.spent_today()
        if today + estimate_usd >= self.daily_cap_usd:
            raise BudgetExceeded("günlük", today, self.daily_cap_usd)
        if workflow_id is not None:
            spent = self.ledger.spent_workflow(workflow_id)
            if spent + estimate_usd >= self.workflow_cap_usd:
                raise BudgetExceeded("iş akışı", spent, self.workflow_cap_usd)

    def charge(self, workflow_id: UUID | None, cost_usd: float) -> None:
        if cost_usd > 0:
            self.ledger.add(workflow_id, cost_usd)
