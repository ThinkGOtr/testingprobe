"""Dış bağımlılık fabrikaları: Jira, forge, model geçidi, demo veritabanı.

Üretimde gerçek fabrikalar kullanılır (`get_jira`, `get_forge`, `build_gateway`); testler
`override(...)` ile aynı arayüzü uygulayan süreç içi nesneler verir (jira-sim, geçici LocalForge,
FakeProvider'lı geçit). Kod yolu aynıdır: iş akışı yalnızca bu fonksiyonları çağırır.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any
from urllib.parse import quote

from sqlalchemy import Engine

from tp_core.features.requirements.datatools import DemoDb
from tp_core.features.requirements.settings import get_requirements_settings

_overrides: dict[str, Callable[..., Any]] = {}


def jira() -> Any:
    """`RestJira` (JiraPort + `po_approvals`/`issue_url`); süreç başına tek istemci."""
    f = _overrides.get("jira")
    if f is not None:
        return f()
    return _default_jira()


@lru_cache(maxsize=1)
def _default_jira() -> Any:
    from tp_core.integrations.jira import get_jira

    return get_jira()


def forge() -> Any:
    f = _overrides.get("forge")
    if f is not None:
        return f()
    from tp_core.integrations.forge import get_forge

    return get_forge()


def gateway(engine: Engine) -> Any:
    """`tp_core.gateway.Gateway` (kayıtçı Postgres; mod TP_MODEL_MODE'a göre)."""
    f = _overrides.get("gateway")
    if f is not None:
        return f(engine)
    from tp_core.audit import PgCallRecorder
    from tp_core.gateway import build_gateway

    return build_gateway(PgCallRecorder(engine), engine=engine)


def demo_db() -> DemoDb:
    f = _overrides.get("demo_db")
    if f is not None:
        return f()
    return DemoDb(get_requirements_settings().demoapp_ro_database_url)


def po_accounts() -> frozenset[str]:
    """PO onay izin listesi (MIMARI-SOZLESME §6 `JIRA_PO_ACCOUNT_IDS`; boş → jira-sim'de
    po@sim.local). Kimlikler e-posta ya da accountId'dir; karşılaştırma büyük/küçük harf ve
    boşluk duyarsızdır. Görünen ad (displayName) bilerek kullanılmaz: herkes kendi görünen adını
    PO'nunkiyle aynı yapabilir."""
    f = _overrides.get("po_accounts")
    if f is not None:
        return frozenset(f())
    from tp_core.integrations.jira import get_jira_settings

    return frozenset(normalize_identity(a) for a in get_jira_settings().po_accounts if a.strip())


def normalize_identity(value: str) -> str:
    v = value.strip()
    for onek in ("accountid:", "email:", "mailto:"):
        if v.casefold().startswith(onek):
            v = v[len(onek) :]
    return v.strip().casefold()


def jira_url(key: str | None) -> str | None:
    if not key:
        return None
    f = _overrides.get("jira_url")
    if f is not None:
        return f(key)
    from tp_core.integrations.jira import get_jira_settings

    s = get_jira_settings()
    return f"{(s.jira_browse_url or s.jira_base_url).rstrip('/')}/browse/{quote(key, safe='')}"


@contextmanager
def override(**factories: Callable[..., Any]) -> Iterator[None]:
    bilinmeyen = set(factories) - {"jira", "forge", "gateway", "demo_db", "po_accounts", "jira_url"}
    if bilinmeyen:
        raise ValueError(f"bilinmeyen servis: {sorted(bilinmeyen)}")
    onceki = dict(_overrides)
    _overrides.update(factories)
    try:
        yield
    finally:
        _overrides.clear()
        _overrides.update(onceki)
