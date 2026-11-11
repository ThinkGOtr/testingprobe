"""core-api uygulaması: /health + platform router'ları + özellik router'ları (registry)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from tp_core import __version__, db
from tp_core.api import errors, registry
from tp_core.api.csrf import OriginGuard, parse_origins
from tp_core.api.kimlik_kipi import KimlikKipiBasligi
from tp_core.api.routers import admin_kimlik, aiprobe, audit, auth, events, tokens
from tp_core.config import Settings, baslangic_denetimi, get_settings

SERVICE = "core-api"


class Health(BaseModel):
    service: str = SERVICE
    status: Literal["ok", "degraded"]
    version: str = __version__
    checks: dict[str, str]


def check_db() -> str:
    try:
        db.ping()
    except Exception as exc:
        return f"error: {_kisa_hata(exc)}"
    return "ok"


def _kisa_hata(exc: BaseException) -> str:
    kok = getattr(exc, "orig", None) or exc
    satir = str(kok).strip().splitlines()
    return satir[0] if satir else type(kok).__name__


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Üretimde demo kipi açıksa başlamaz (specs/012-rol-yetki §2).
    baslangic_denetimi()
    yield
    b = getattr(app.state, "broadcaster", None)
    if b is not None:
        await b.stop()


def _izinli_kaynaklar() -> frozenset[str]:
    # create_app TP_DATABASE_URL olmadan da (ör. rota tablosu) kurulabilmeli.
    try:
        return parse_origins(get_settings().allowed_origins)
    except ValidationError:
        return parse_origins(Settings.model_fields["allowed_origins"].default)


PLATFORM_ROUTERS = [
    auth.router,
    aiprobe.router,
    admin_kimlik.router,
    audit.router,
    events.router,
    tokens.router,
]


def create_app() -> FastAPI:
    app = FastAPI(title="Testing Probe Core", version=__version__, lifespan=lifespan)
    errors.install(app)
    # CSRF: başka kaynaktan (aynı sitedeki diğer yerel portlar dahil) gelen güvensiz istekler 403.
    app.add_middleware(OriginGuard, allowed_origins=_izinli_kaynaklar())
    # AI Probe kipinde her yanıta `X-TP-Kimlik` (portal kipi öğrenir); `local`'de başlık yok.
    app.add_middleware(KimlikKipiBasligi)

    @app.get("/health", response_model=Health)
    def health(db_durum: Annotated[str, Depends(check_db)]) -> JSONResponse:
        checks = {"db": db_durum}
        ok = all(v == "ok" for v in checks.values())
        body = Health(status="ok" if ok else "degraded", checks=checks)
        return JSONResponse(body.model_dump(), status_code=200 if ok else 503)

    app.state.feature_routers = registry.mount_all(app, PLATFORM_ROUTERS)
    return app


app = create_app()
