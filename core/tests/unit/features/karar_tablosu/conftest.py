"""Karar tablosu (Ş1) fikstürleri: gerçek Postgres, API istemcisi, PO onaylı gereksinim ve model
geçidi (FakeProvider ya da REPLAY golden'ları; canlı model yok)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine

import tp_core.features.karar_tablosu.jobs  # noqa: F401  (karar_tablosu.draft işleyicisi)
from tests.unit.features.cases.helpers import api, make_requirement  # noqa: F401
from tp_core.audit import PgCallRecorder
from tp_core.features.karar_tablosu import service
from tp_core.gateway import build_gateway
from tp_core.gateway.config import GatewaySettings
from tp_core.gateway.testing import FakeProvider


@pytest.fixture
def replay_gateway(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """TP_MODEL_MODE=replay: rules/replay golden'ları (anahtar yok)."""
    monkeypatch.setenv("TP_MODEL_MODE", "replay")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TP_REPLAY_STRICT", raising=False)
    monkeypatch.delenv("TP_RULES_DIR", raising=False)
    gw = build_gateway(PgCallRecorder(engine), settings=GatewaySettings(), engine=engine)
    service.set_gateway_factory(lambda _e: gw)
    yield gw
    service.set_gateway_factory(None)


@pytest.fixture
def fake_gateway(engine: Engine, monkeypatch: pytest.MonkeyPatch):
    """Senaryolu sahte sağlayıcı (geçidin canlı kod yolu; Postgres kayıtçısıyla)."""
    monkeypatch.setenv("TP_MODEL_MODE", "live")
    monkeypatch.delenv("TP_RULES_DIR", raising=False)

    def _kur(script: list[Any]) -> FakeProvider:
        provider = FakeProvider(script)
        gw = build_gateway(
            PgCallRecorder(engine), settings=GatewaySettings(), engine=engine, provider=provider
        )
        service.set_gateway_factory(lambda _e: gw)
        return provider

    yield _kur
    service.set_gateway_factory(None)
