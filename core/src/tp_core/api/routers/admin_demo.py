"""`/admin/demo-sifirla` — AI Probe Home "Sıfırla" düğmesinin TP uçları (demo tam sıfırlaması).

Yalnız `aiprobe-home` servis kimliği çağırır (`admin_kimlik.home_servisi` ile aynı doğrulama:
Google ID token imzası, `aud` = `AIPROBE_TP_AUDIENCE`, `email` = `AIPROBE_HOME_SA`; `local` kipte
404). Kişi yetkisi (org yöneticisi, demo bayrağı, proje adını yazma) Home'da denetlenir; TP ayrıca
yalnız demo projesini (varsayılan proje + `TP_DEMO_MODE=1`) kabul eder.

- `GET  /admin/demo-sifirla/onizleme?project_id=` → silinecek sayımlar ve hedef değerler
- `POST /admin/demo-sifirla {project_id, aktor}` → 202 `{islem}`; 409 `suruyor` (+ `islem`),
  `demo_isi_suruyor`, `demo_proje_degil`; 404 `proje_yok`
- `GET  /admin/demo-sifirla?project_id=` → `{islem}` (son işlem ya da null)
- `GET  /admin/demo-sifirla/{id}` → `{islem}` (`islem.yeniden_kontrol`: son yeniden kontrol | null)
- `POST /admin/demo-sifirla/{id}/kontrol` → 202 `{islem}`: "Demoya hazır" listesini şu anki durumla
  yeniden hesaplayan salt okuma işi; 409 `suruyor` / `eski_islem`, 404 `bulunamadi`
"""

from __future__ import annotations

import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from tp_core.api.errors import KodluHata
from tp_core.api.routers.admin_kimlik import HomeServisi
from tp_core.db import get_engine
from tp_core.features.demo import tam_sifirlama

router = APIRouter(prefix="/admin/demo-sifirla", tags=["admin"])
_PID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def _pid(deger: str) -> str:
    if not _PID.fullmatch(deger or ""):
        raise KodluHata(400, "gecersiz_istek", "Geçersiz proje kimliği")
    return deger


class Aktor(BaseModel):
    uid: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=320)
    ad: str | None = Field(default=None, max_length=200)


class Istek(BaseModel):
    project_id: str = Field(min_length=1, max_length=64)
    aktor: Aktor = Field(default_factory=Aktor)


def _red(exc: tam_sifirlama.IstekReddi) -> KodluHata:
    return KodluHata(exc.status, exc.kod, exc.mesaj, ek={"islem": exc.islem} if exc.islem else None)


@router.get("/onizleme")
def onizleme(
    _home: HomeServisi, project_id: Annotated[str, Query(max_length=64)]
) -> dict[str, Any]:
    try:
        return tam_sifirlama.onizleme(get_engine(), _pid(project_id))
    except tam_sifirlama.IstekReddi as exc:
        raise _red(exc) from exc


@router.post("", status_code=202)
def baslat(body: Istek, _home: HomeServisi) -> JSONResponse:
    try:
        islem = tam_sifirlama.istek(get_engine(), _pid(body.project_id), body.aktor.model_dump())
    except tam_sifirlama.IstekReddi as exc:
        raise _red(exc) from exc
    return JSONResponse({"islem": islem}, status_code=202)


@router.get("")
def son(_home: HomeServisi, project_id: Annotated[str, Query(max_length=64)]) -> dict[str, Any]:
    return {"islem": tam_sifirlama.son(get_engine(), _pid(project_id))}


def _kimlik(islem_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(islem_id)
    except ValueError as exc:
        raise KodluHata(404, "bulunamadi", "İşlem bulunamadı") from exc


class KontrolIstegi(BaseModel):
    project_id: str | None = Field(default=None, max_length=64)


@router.post("/{islem_id}/kontrol", status_code=202)
def yeniden_kontrol(
    islem_id: str, _home: HomeServisi, body: KontrolIstegi | None = None
) -> JSONResponse:
    pid = _pid(body.project_id) if body and body.project_id is not None else None
    try:
        islem = tam_sifirlama.kontrol_istek(get_engine(), _kimlik(islem_id), pid)
    except tam_sifirlama.IstekReddi as exc:
        raise _red(exc) from exc
    return JSONResponse({"islem": islem}, status_code=202)


@router.get("/{islem_id}")
def oku(islem_id: str, _home: HomeServisi) -> dict[str, Any]:
    islem = tam_sifirlama.oku(get_engine(), _kimlik(islem_id))
    if islem is None:
        raise KodluHata(404, "bulunamadi", "İşlem bulunamadı")
    return {"islem": islem}
