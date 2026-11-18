"""Test verisi kataloğu uçları (specs/013-sprint-otomasyonu §3.3).

| Yöntem | Yol | İzin |
|---|---|---|
| GET | `/test-data` | `case.read` |
| POST | `/test-data` | `testdata.manage` |
| PUT | `/test-data/{id}` | `testdata.manage` — `beklenen_surum` zorunlu (iyimser kilit, 409) |
| DELETE | `/test-data/{id}?beklenen_surum=` | `testdata.manage` — atıf yapan etkin case varsa 409 |
| GET | `/test-data/{id}/history` | `case.read` |
| GET | `/test-data-sources` | `case.read` — veritabanı kaynakları (`kaynak`) |
| POST | `/test-data-sources` | `testdata.manage` |
| PUT | `/test-data-sources/{id}` | `testdata.manage` — `beklenen_surum` zorunlu (409) |
| DELETE | `/test-data-sources/{id}?beklenen_surum=` | `testdata.manage` (kayıtlar kalır) |
| POST | `/test-data-sources/preview` | `testdata.manage` — 202 `{job_id}` (ilk 20 satır; worker) |
| POST | `/test-data-sources/refresh` | `testdata.manage` — 202 `{job_id}`; gövde `{kaynak_id?}` |
| GET | `/test-data-sources/jobs/{job_id}` | `testdata.manage` — `{id, tur, durum, sonuc, hata}` |

Gizli kayıtta değer hiçbir yanıtta dönmez; `sir_tanimli` döner. PUT'ta `aciklama: ""` (ya da
açıkça `null`) açıklamayı temizler. DELETE 409 gövdesi: `{detail, kod: "cakisma", kullanan:
[{case_id, case_ref, requirement_id, baslik, durum}]}`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from tp_core.auth.deps import DbSession
from tp_core.auth.yetki import izin
from tp_core.features.testveri import kaynak, service
from tp_core.workflow.service import Principal

router = APIRouter(tags=["test-data"])

Okur = Annotated[Principal, Depends(izin("case.read"))]
Duzenleyen = Annotated[Principal, Depends(izin("testdata.manage"))]


class TestVerisiGirdisi(BaseModel):
    __test__ = False
    anahtar: str = Field(max_length=200)
    grup: str | None = Field(default=None, max_length=100)
    aciklama: str | None = Field(default=None, max_length=500)
    deger: str | None = Field(default=None, max_length=service.MAX_DEGER)
    gizli: bool = False
    sir_adi: str | None = Field(default=None, max_length=100)


class TestVerisiGuncelleme(BaseModel):
    __test__ = False
    deger: str | None = Field(default=None, max_length=service.MAX_DEGER)
    aciklama: str | None = Field(default=None, max_length=500)
    grup: str | None = Field(default=None, max_length=100)
    sir_adi: str | None = Field(default=None, max_length=100)
    beklenen_surum: int


@router.get("/test-data")
def listele(session: DbSession, _user: Okur) -> list[dict[str, Any]]:
    return service.listele(session)


@router.post("/test-data", status_code=201)
def olustur(body: TestVerisiGirdisi, session: DbSession, user: Duzenleyen) -> dict[str, Any]:
    k = service.olustur(session, body.model_dump(), user.kullanici_adi)
    return service.serialize(k)


@router.put("/test-data/{kid}")
def guncelle(
    kid: uuid.UUID, body: TestVerisiGuncelleme, session: DbSession, user: Duzenleyen
) -> dict[str, Any]:
    girdi = body.model_dump(exclude={"beklenen_surum"}, exclude_unset=True)
    k = service.guncelle(session, kid, girdi, body.beklenen_surum, user.kullanici_adi)
    return service.serialize(k)


@router.delete("/test-data/{kid}", response_model=None)
def sil(
    kid: uuid.UUID,
    session: DbSession,
    user: Duzenleyen,
    beklenen_surum: Annotated[int, Query()],
) -> dict[str, Any] | JSONResponse:
    try:
        k = service.sil(session, kid, beklenen_surum, user.kullanici_adi)
    except service.TestVerisiKullanimda as exc:
        return JSONResponse(
            {"detail": str(exc), "kod": "cakisma", "kullanan": exc.kullanan}, status_code=409
        )
    return {"id": str(k.id), "anahtar": k.anahtar, "silindi": True, "surum": k.surum}


@router.get("/test-data/{kid}/history")
def gecmis(kid: uuid.UUID, session: DbSession, _user: Okur) -> list[dict[str, Any]]:
    return service.gecmis(session, kid)


# --------------------------------------------------------------------------- veritabanı kaynakları


class KolonGirdisi(BaseModel):
    kolon: str = Field(max_length=64)
    alan: str | None = Field(default=None, max_length=40)
    bicim: str = Field(default="metin", max_length=10)
    aciklama: str | None = Field(default=None, max_length=500)


class KaynakGirdisi(BaseModel):
    grup: str = Field(max_length=40)
    sorgu: str = Field(max_length=kaynak.MAX_SORGU)
    anahtar_kolonu: str = Field(max_length=64)
    deger_kolonlari: list[KolonGirdisi] = Field(min_length=1, max_length=kaynak.MAX_KOLON)
    aciklama: str | None = Field(default=None, max_length=500)


class KaynakGuncelleme(BaseModel):
    sorgu: str | None = Field(default=None, max_length=kaynak.MAX_SORGU)
    anahtar_kolonu: str | None = Field(default=None, max_length=64)
    deger_kolonlari: list[KolonGirdisi] | None = Field(default=None, max_length=kaynak.MAX_KOLON)
    aciklama: str | None = Field(default=None, max_length=500)
    beklenen_surum: int


class YenileGirdisi(BaseModel):
    kaynak_id: uuid.UUID | None = None


@router.get("/test-data-sources")
def kaynaklar(session: DbSession, _user: Okur) -> list[dict[str, Any]]:
    return kaynak.listele(session)


@router.post("/test-data-sources", status_code=201)
def kaynak_olustur(body: KaynakGirdisi, session: DbSession, user: Duzenleyen) -> dict[str, Any]:
    k = kaynak.olustur(session, body.model_dump(), user.kullanici_adi)
    return kaynak.serialize(k)


@router.put("/test-data-sources/{kid}")
def kaynak_guncelle(
    kid: uuid.UUID, body: KaynakGuncelleme, session: DbSession, user: Duzenleyen
) -> dict[str, Any]:
    girdi = body.model_dump(exclude={"beklenen_surum"}, exclude_unset=True)
    k = kaynak.guncelle(session, kid, girdi, body.beklenen_surum, user.kullanici_adi)
    return kaynak.serialize(k)


@router.delete("/test-data-sources/{kid}")
def kaynak_sil(
    kid: uuid.UUID,
    session: DbSession,
    user: Duzenleyen,
    beklenen_surum: Annotated[int, Query()],
) -> dict[str, Any]:
    k = kaynak.sil(session, kid, beklenen_surum, user.kullanici_adi)
    return {"id": str(k.id), "grup": k.grup, "silindi": True, "surum": k.surum}


@router.post("/test-data-sources/preview", status_code=202)
def kaynak_onizle(body: KaynakGirdisi, session: DbSession, user: Duzenleyen) -> dict[str, Any]:
    tanim = kaynak.tanim_dogrula(body.model_dump())
    return {"job_id": str(kaynak.onizle_kuyruga(session, user.kullanici_adi, tanim))}


@router.post("/test-data-sources/refresh", status_code=202)
def kaynak_yenile(body: YenileGirdisi, session: DbSession, user: Duzenleyen) -> dict[str, Any]:
    return {"job_id": str(kaynak.yenile_kuyruga(session, user.kullanici_adi, body.kaynak_id))}


@router.get("/test-data-sources/jobs/{job_id}")
def kaynak_isi(job_id: uuid.UUID, session: DbSession, _user: Duzenleyen) -> dict[str, Any]:
    return kaynak.is_durumu(session, job_id)
