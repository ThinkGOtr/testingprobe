"""Router kaydı: platform router'ları + özellik router'ları.

Özellik şeritleri `tp_core/features/<ad>/api.py` (veya `routes.py`) içinde `router = APIRouter()`
tanımlar; uygulama başlarken otomatik bulunur ve bağlanır. Alternatif: `register_router(router)`.
Aynı (yöntem, yol) iki kez tanımlanırsa uygulama başlamaz (sessiz gölgeleme yok). İçe aktarma
hatası da yutulmaz.
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from collections.abc import Iterable, Iterator

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

FEATURES_PACKAGE = "tp_core.features"
ROUTER_MODULES = ("api", "routes")

_registered: list[APIRouter] = []


def register_router(router: APIRouter) -> APIRouter:
    if router not in _registered:
        _registered.append(router)
    return router


def discover_feature_routers(package: str = FEATURES_PACKAGE) -> list[tuple[str, APIRouter]]:
    try:
        paket = importlib.import_module(package)
    except ModuleNotFoundError:
        return []
    bulunan: list[tuple[str, APIRouter]] = []
    for mod in sorted(pkgutil.iter_modules(getattr(paket, "__path__", [])), key=lambda m: m.name):
        if not mod.ispkg:
            continue
        for alt in ROUTER_MODULES:
            ad = f"{package}.{mod.name}.{alt}"
            if importlib.util.find_spec(ad) is None:
                continue
            router = getattr(importlib.import_module(ad), "router", None)
            if not isinstance(router, APIRouter):
                raise TypeError(f"{ad}: 'router' APIRouter olmalı")
            bulunan.append((ad, router))
    return bulunan


def _rotalar(routes: Iterable[BaseRoute], prefix: str = "") -> Iterator[tuple[str, str, str]]:
    for route in routes:
        if isinstance(route, APIRoute):
            for yontem in sorted(route.methods or ()):
                yield yontem, prefix + route.path, route.name
            continue
        # FastAPI ≥0.15x include_router'ı tembel sarmalar (_IncludedRouter): içine in.
        alt = getattr(route, "original_router", None)
        if alt is not None:
            ek = getattr(getattr(route, "include_context", None), "prefix", "") or ""
            yield from _rotalar(alt.routes, prefix + ek)


def route_table(app: FastAPI) -> list[tuple[str, str, str]]:
    """Uygulamadaki tüm API uçları: (yöntem, yol, ad)."""
    return list(_rotalar(app.router.routes))


def _cakisma_kontrolu(app: FastAPI) -> None:
    gorulen: dict[tuple[str, str], str] = {}
    for yontem, yol, ad in route_table(app):
        if (yontem, yol) in gorulen:
            raise RuntimeError(f"çakışan uç: {yontem} {yol} ({gorulen[(yontem, yol)]} ve {ad})")
        gorulen[(yontem, yol)] = ad


def mount_all(
    app: FastAPI, platform: list[APIRouter], package: str = FEATURES_PACKAGE
) -> list[str]:
    for r in platform:
        app.include_router(r)
    adlar: list[str] = []
    for ad, r in discover_feature_routers(package):
        app.include_router(r)
        adlar.append(ad)
    for r in _registered:
        app.include_router(r)
    _cakisma_kontrolu(app)
    return adlar
