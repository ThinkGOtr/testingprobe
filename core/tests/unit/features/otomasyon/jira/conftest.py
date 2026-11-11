"""Otomasyon testleri gereksinim fikstürlerini (gerçek Postgres, süreç içi jira-sim, REPLAY geçidi,
worker iş yürütücüsü) kullanır."""

from __future__ import annotations

from tests.unit.features.requirements.conftest import (  # noqa: F401
    _baz_dosyasi_yok,
    api,
    demo_db,
    demo_forge_repo,
    demoapp_ro_url,
    forge,
    jira,
    po,
    replay_gateway,
    req_settings,
    sim,
    wired,
)
