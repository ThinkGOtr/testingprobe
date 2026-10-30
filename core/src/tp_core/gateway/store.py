"""Postgres'e bağlı geçit yardımcıları: kalıcı harcama defteri ve çağrı ailesi okuyucusu.

- `PgSpendLedger` (`budget.SpendLedger`): harcama `ai_call.maliyet` toplamından okunur — iş akışı
  başına ve UTC günü başına. Kaynak tek: `tp_core.workflow.budget` ile aynı sorgular. Süreç yeniden
  başlasa da (core-worker çökme/yeniden başlatma döngüsü dahil) tavanlar korunur. `add()` bir şey
  yazmaz: maliyet, geçidin `CallRecorder` ile yazdığı `ai_call` satırındadır.
- `PgCallLookup` (`core.CallLookup`): `call_id` idempotency'si için çağrı ailesinin satırları.

Uygulama rolü (`tp_app`) `ai_call` üzerinde yalnızca INSERT/SELECT'e sahiptir; burada yalnızca
SELECT kullanılır.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from tp_core.workflow.budget import daily_spend_usd, workflow_spend_usd

_FAMILY_SQL = text(
    "SELECT id, parent_call_id, amac, mod, cikti, sema_gecerli, hata, girdi_token, cikti_token, "
    "maliyet FROM ai_call WHERE id = :root OR parent_call_id = :root "
    "ORDER BY olusturma, deneme NULLS FIRST, id"
)


class PgSpendLedger:
    def __init__(self, engine: Engine, today: Callable[[], date] | None = None) -> None:
        self._engine = engine
        self._today = today or (lambda: datetime.now(UTC).date())

    def spent_workflow(self, workflow_id: UUID) -> float:
        with self._engine.connect() as conn:
            return float(workflow_spend_usd(conn, workflow_id))

    def spent_today(self) -> float:
        with self._engine.connect() as conn:
            return float(daily_spend_usd(conn, self._today()))

    def add(self, workflow_id: UUID | None, cost_usd: float) -> None:
        """Bilerek boş: maliyet `ai_call.maliyet`e satırla birlikte yazılır."""


class PgCallLookup:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def find_ai_calls(self, root_id: UUID) -> list[Mapping[str, Any]]:
        with self._engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(_FAMILY_SQL, {"root": root_id})]
