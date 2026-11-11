"""Agent Probe adaptörü (011 §4.5; ``AgentProbePort``).

Seçim ``TP_AGENT_PROBE``: ``tp`` (varsayılan; denetim ve asistan puanı Testing Probe geçidinde ayrı
model çağrısıyla, ajan ürünleri/testleri simülatörle) | ``sim`` (her şey deterministik simülatör;
model çağrısı yok) | ``http`` (gerçek Agent Probe servisi; bu sürümde yok, ayrılmıştır).

Yöntemler ayrı modüllerdedir ve ayrı şeritlerce yazılır:
- ``denetim.py``: ``audit_case_set`` (P9) — D şeridi.
- ``asistan.py``: ``score_message`` — A şeridi.
- ``sim.py``: ``list_products``, ``start_agent_test``, ``get_agent_test`` ve ``sim`` kipindeki
  deterministik denetim/puan — A şeridi.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any, Literal
from uuid import UUID

from tp_core.ports import (
    AgentProbePort,
    AgentProduct,
    AgentTestTicket,
    CaseSetAuditRequest,
    CaseSetAuditResult,
    MessageScore,
)


class AgentProbeUnavailable(Exception):
    """Agent Probe'a erişilemiyor / kip desteklenmiyor (çağıran fail-closed davranır)."""


class TpAgentProbe:
    """Varsayılan (``tp``): denetim ve puan Testing Probe geçidinde, ajan testleri simülatörde."""

    name = "tp"

    def audit_case_set(self, istek: CaseSetAuditRequest) -> CaseSetAuditResult:
        from tp_core.integrations.agent_probe import denetim

        return denetim.audit_case_set(istek)

    def score_message(
        self, metin: str, yon: Literal["soru", "cevap"], baglam: Mapping[str, Any]
    ) -> MessageScore:
        from tp_core.integrations.agent_probe import asistan

        return asistan.score_message(metin, yon, baglam)

    def list_products(self) -> list[AgentProduct]:
        from tp_core.integrations.agent_probe import sim

        return sim.list_products()

    def start_agent_test(
        self, urun_kodu: str, requirement_id: UUID, gereksinim: Mapping[str, Any]
    ) -> AgentTestTicket:
        from tp_core.integrations.agent_probe import sim

        return sim.start_agent_test(urun_kodu, requirement_id, gereksinim)

    def get_agent_test(self, talep_no: str) -> AgentTestTicket:
        from tp_core.integrations.agent_probe import sim

        return sim.get_agent_test(talep_no)


def _default_factory() -> AgentProbePort:
    kip = (os.environ.get("TP_AGENT_PROBE") or "tp").strip().lower()
    if kip == "tp":
        return TpAgentProbe()
    if kip == "sim":
        from tp_core.integrations.agent_probe import sim

        return sim.SimAgentProbe()
    raise AgentProbeUnavailable(f"TP_AGENT_PROBE={kip!r} desteklenmiyor (tp | sim)")


_factory: Callable[[], AgentProbePort] = _default_factory


def set_agent_probe_factory(factory: Callable[[], AgentProbePort] | None) -> None:
    """Testler için (None → ``TP_AGENT_PROBE``)."""
    global _factory
    _factory = factory or _default_factory


def get_agent_probe() -> AgentProbePort:
    return _factory()
