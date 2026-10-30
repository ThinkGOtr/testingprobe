from typing import Annotated, Literal

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from tp_core import __version__, db

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


app = FastAPI(title="Testing Probe Core", version=__version__)


@app.get("/health", response_model=Health)
def health(db_durum: Annotated[str, Depends(check_db)]) -> JSONResponse:
    checks = {"db": db_durum}
    ok = all(v == "ok" for v in checks.values())
    body = Health(status="ok" if ok else "degraded", checks=checks)
    return JSONResponse(body.model_dump(), status_code=200 if ok else 503)
