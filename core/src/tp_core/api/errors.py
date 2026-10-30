"""Hata biçimi sözleşmesi: her hata ``{"detail": "<Türkçe metin>"}`` (MIMARI-SOZLESME §5)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from tp_core.workflow.budget import BudgetExceeded
from tp_core.workflow.service import WorkflowError


def _dogrulama_metni(exc: RequestValidationError) -> str:
    parcalar = []
    for hata in exc.errors()[:5]:
        yer = ".".join(str(p) for p in hata.get("loc", ()) if p not in ("body", "query", "path"))
        parcalar.append(f"{yer}: {hata.get('msg', 'geçersiz')}" if yer else hata.get("msg", ""))
    return "Geçersiz istek — " + "; ".join(parcalar)


def install(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _dogrulama(_r: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse({"detail": _dogrulama_metni(exc)}, status_code=422)

    @app.exception_handler(WorkflowError)
    async def _akis(_r: Request, exc: WorkflowError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)

    @app.exception_handler(BudgetExceeded)
    async def _butce(_r: Request, exc: BudgetExceeded) -> JSONResponse:
        return JSONResponse(
            {"detail": str(exc), "budget": exc.status.as_dict()}, status_code=exc.status_code
        )
