"""Dış bağımlılık fabrikaları: Jira, forge, model geçidi, demo veritabanı.

Üretimde gerçek fabrikalar kullanılır (`get_jira`, `get_forge`, `build_gateway`); testler
`override(...)` ile aynı arayüzü uygulayan süreç içi nesneler verir (jira-sim, geçici LocalForge,
FakeProvider'lı geçit). Kod yolu aynıdır: iş akışı yalnızca bu fonksiyonları çağırır.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import quote

from sqlalchemy import Engine

from tp_core.features.requirements.datatools import DemoDb
from tp_core.features.requirements.settings import get_requirements_settings
from tp_core.proje import istemciler

_overrides: dict[str, Callable[..., Any]] = {}


def jira() -> Any:
    """`RestJira` (JiraPort + `po_approvals`/`issue_url`); bağlamdaki projenin istemcisi
    (`proje.istemciler`, proje + config sürümü başına tek)."""
    f = _overrides.get("jira")
    if f is not None:
        return f()
    return istemciler.jira()


def forge() -> Any:
    f = _overrides.get("forge")
    if f is not None:
        return f()
    from tp_core.features.requirements.approot import app_root_view

    return app_root_view(istemciler.forge())


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
    return demo_db_ayarlardan()


def demo_db_ayarlardan() -> DemoDb:
    """`DEMOAPP_RO_DATABASE_URL` doluysa ondan (bugünkü kurulumlar aynen), değilse `TP_RO_DB_*`
    ayrı alanlarından. Geçersiz yapılandırma veri aracında "yapılandırma hatası" olarak döner."""
    from tp_core.veri.ro_baglanti import BaglantiHatasi

    ayar = get_requirements_settings()
    if ayar.demoapp_ro_database_url:
        return DemoDb(ayar.demoapp_ro_database_url)
    try:
        tanim = ayar.ro_baglanti()
    except BaglantiHatasi as exc:
        return DemoDb.yapilandirma_hatasi(f"Veri erişimi yapılandırması geçersiz: {exc}")
    return DemoDb(tanim)


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
