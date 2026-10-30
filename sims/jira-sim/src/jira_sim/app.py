"""jira-sim uygulaması: Jira Cloud REST v3 + Xray Cloud alt kümesi + Türkçe arayüz.

Ortam değişkenleri:
- ``JIRA_SIM_DATA``: durum dosyası (JSON). Boşsa durum yalnızca bellekte tutulur.
- ``JIRA_SIM_BASE_URL``: yanıtlardaki ``self`` bağlantılarının kökü (boşsa isteğin adresi).
- ``JIRA_SIM_PO_PASSWORD``, ``JIRA_SIM_ADMIN_TOKEN``, ``JIRA_SIM_SECRET``,
  ``JIRA_SIM_ALLOWED_HOSTS``: bkz. ``jira_sim.security``.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from jira_sim import __version__, api, ui, xray
from jira_sim.ops import SimError
from jira_sim.security import ADMIN_HEADER, SimSecurity
from jira_sim.store import Store

SERVICE_NAME = "jira-sim"


class FaultMiddleware(BaseHTTPMiddleware):
    """``POST /sim/faults`` ile kurulan hata enjeksiyonu (429/5xx yeniden deneme provası)."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        store: Store = request.app.state.store
        path = request.url.path
        if not path.startswith("/sim/") and path != "/health":
            with store.lock:
                for fault in store.faults:
                    if fault["count"] <= 0 or not path.startswith(fault["path_prefix"]):
                        continue
                    if fault.get("method") and fault["method"].upper() != request.method:
                        continue
                    fault["count"] -= 1
                    headers = {}
                    if fault.get("retry_after") is not None:
                        headers["Retry-After"] = str(fault["retry_after"])
                    return JSONResponse(
                        {"errorMessages": [f"Simulated fault {fault['status']}"], "errors": {}},
                        status_code=fault["status"],
                        headers=headers,
                    )
        return await call_next(request)


def admin_guard(request: Request) -> None:
    """``/sim/*`` yazma uçları: tarayıcıdan başka kökenli istek ve yanlış yönetim belirteci → 403.

    ``Content-Type: application/json`` dışındaki gövdeler de reddedilir; böylece bir web sayfası
    "basit" (preflight'sız) form isteğiyle bu uçlara ulaşamaz.
    """
    sec: SimSecurity = request.app.state.security
    base = request.app.state.base_url
    if not sec.host_allowed(request, base) or not sec.same_origin(request, base):
        raise SimError(403, ["Cross-origin request to simulator admin endpoint refused."])
    if not sec.check_admin(request):
        raise SimError(403, [f"Missing or invalid {ADMIN_HEADER} header."])
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype and ctype != "application/json":
        raise SimError(415, ["Simulator admin endpoints accept application/json only."])


def create_app(
    data_path: str | None = None,
    base_url: str | None = None,
    *,
    po_password: str | None = None,
    admin_token: str | None = None,
) -> FastAPI:
    app = FastAPI(title="Jira Simülatörü", version=__version__, docs_url="/sim/docs")
    path = data_path if data_path is not None else os.environ.get("JIRA_SIM_DATA") or None
    app.state.store = Store(path)
    app.state.base_url = (
        base_url if base_url is not None else os.environ.get("JIRA_SIM_BASE_URL", "")
    ).rstrip("/")
    app.state.security = SimSecurity.from_env(po_password, admin_token)
    admin = [Depends(admin_guard)]

    @app.exception_handler(SimError)
    async def _sim_error(_: Request, exc: SimError) -> JSONResponse:
        return api.error_response(exc)

    app.add_exception_handler(ui.Refused, ui.refused_handler)

    @app.exception_handler(xray.XrayError)
    async def _xray_error(_: Request, exc: xray.XrayError) -> JSONResponse:
        return xray.xray_error_response(exc)

    @app.get("/health")
    def health() -> dict[str, Any]:
        store: Store = app.state.store
        with store.lock:
            count = len(store.state["issues"])
        return {
            "service": SERVICE_NAME,
            "status": "ok",
            "version": __version__,
            "checks": {"store": "ok", "issues": count},
        }

    @app.post("/sim/reset", dependencies=admin)
    def sim_reset() -> dict[str, Any]:
        app.state.store.reset()
        return {"status": "reset", "issues": len(app.state.store.state["issues"])}

    @app.get("/sim/config")
    def sim_config_get() -> dict[str, Any]:
        return app.state.store.state["config"]

    @app.post("/sim/config", dependencies=admin)
    async def sim_config(request: Request) -> dict[str, Any]:
        """Proje yapılandırmasını değiştirir (ör. Test türü/bağlantısı olmayan site provası)."""
        body = await api.json_body(request)
        store: Store = app.state.store
        with store.tx() as state:
            for key in ("issue_types", "link_types"):
                if key in body:
                    value = body[key]
                    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                        raise SimError(400, [f"'{key}' must be a list of names."])
                    state["config"][key] = value
            return state["config"]

    @app.post("/sim/faults", dependencies=admin)
    async def sim_faults(request: Request) -> dict[str, Any]:
        """``{"path_prefix", "status", "count", "retry_after"?, "method"?}``; boş liste temizler."""
        body = await api.json_body(request)
        faults = body if isinstance(body, list) else [body]
        store: Store = app.state.store
        with store.lock:
            store.faults.clear()
            for f in faults:
                if not f:
                    continue
                store.faults.append(
                    {
                        "path_prefix": str(f.get("path_prefix", "/")),
                        "status": int(f.get("status", 503)),
                        "count": int(f.get("count", 1)),
                        "retry_after": f.get("retry_after"),
                        "method": f.get("method"),
                    }
                )
            return {"faults": store.faults}

    app.include_router(api.router)
    app.include_router(xray.router)
    app.include_router(ui.router)
    app.add_middleware(FaultMiddleware)
    return app


app = create_app()
