"""FastAPI uygulaması. F0: yalnızca GET /health (contracts/health.md). İş mantığı F1'de."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from demoapp_api import __version__, db

SERVICE_NAME = "demo-app-api"

app = FastAPI(title="Bayi Sipariş Portalı API", version=__version__)


@app.get("/health")
def health() -> JSONResponse:
    checks = {"db": db.check_db()}
    healthy = all(v == "ok" for v in checks.values())
    body = {
        "service": SERVICE_NAME,
        "status": "ok" if healthy else "degraded",
        "version": __version__,
        "checks": checks,
    }
    return JSONResponse(body, status_code=200 if healthy else 503)
