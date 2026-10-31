"""Ortak FastAPI yardımcıları: Türkçe `{"detail": "..."}` hata gövdesi."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        parts = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", ()) if x != "body")
            msg = str(err.get("msg", "")).removeprefix("Value error, ")
            parts.append(f"{loc}: {msg}" if loc else msg)
        return JSONResponse(
            {
                "detail": "Geçersiz istek: " + "; ".join(parts),
                "errors": [
                    {
                        "loc": list(e.get("loc", ())),
                        "msg": str(e.get("msg", "")),
                        "type": e.get("type"),
                    }
                    for e in exc.errors()
                ],
            },
            status_code=422,
        )
