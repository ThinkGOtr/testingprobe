"""Karar tablosu ve metamorfik ilişki uçları (012 ANALIZ §6). `registry` bu `router`'ı bağlar.

| Yöntem | Yol | Rol | Gövde → yanıt |
|---|---|---|---|
| GET  | `/requirements/{id}/decision-tables?tumu=` | herkes | → `{tablolar, iliskiler,
son_taslak}` |
| POST | `/requirements/{id}/decision-tables/draft` | analyst | → 202 `{job_id, workflow_id,
durum, mesaj, uretim_no}` |
| POST | `/requirements/{id}/decision-tables` | analyst | `{icerik?}` → 201 öğe (boş tablo) |
| PUT  | `/decision-tables/{id}` | analyst | `{icerik, icerik_hash}` → öğe |
| POST | `/decision-tables/{id}/submit` | analyst | `{icerik_hash?}` → öğe |
| POST | `/decision-tables/{id}/withdraw` · `/reopen` | analyst | → öğe |
| POST | `/decision-tables/{id}/approve` | po | `{icerik_hash, gerekce?}` → öğe |
| POST | `/decision-tables/{id}/request-changes` | po | `{icerik_hash, gerekce}` → öğe |
| POST | `/decision-tables/{id}/evaluate` | herkes | `{girdiler, icerik?}` → `{satir_id,
ciktilar, eksik_girdiler, hata}` |
| POST | `/requirements/{id}/relations` | analyst | `{icerik, karar_tablosu_id?}` → 201 öğe |
| PUT  | `/relations/{id}` | analyst | `{icerik, icerik_hash, karar_tablosu_id?}` → öğe |
| POST | `/relations/{id}/submit` · `/withdraw` · `/reopen` | analyst | tablo uçlarıyla aynı |
| POST | `/relations/{id}/approve` · `/request-changes` | po | tablo uçlarıyla aynı |

Öğe: `{id, tur, requirement_id, sira_no, durum, icerik, icerik_hash, onaylanan_hash,
ai_generated, uretim_modu, bayat, olusturma, guncelleme, onaylayan, onay_zamani, son_karar}`;
ilişkide ek olarak `karar_tablosu_id`. `son_karar` = `{karar, gerekce, kullanici, zaman} | null`
(PO'nun son kararı; "değişiklik iste" gerekçesi buradadır).

Hatalar `{detail, kod}`; içerik doğrulaması 422 `karar_tablosu_gecersiz` / `iliski_gecersiz` ve
ek olarak `hatalar: [metin]`. Görülen hash eskiyse 409 `onay_hash_uyusmuyor`; içerik taslakta
değilse ya da gereksinim PO onaylı değilse 409 `cakisma`; geçersiz geçiş 409 `gecersiz_gecis` /
`eszamanli_gecis`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.features.karar_tablosu import service
from tp_core.features.karar_tablosu.hatalar import IliskiGecersiz, KararTablosuGecersiz
from tp_core.workflow.service import Principal

router = APIRouter(tags=["karar_tablosu"])

Analyst = Annotated[Principal, Depends(require_role("analyst"))]
Po = Annotated[Principal, Depends(require_role("po"))]

HASH = Field(default=None, max_length=128)


class IsYaniti(BaseModel):
    job_id: uuid.UUID | None
    durum: str
    mesaj: str | None = None
    workflow_id: uuid.UUID | None = None
    uretim_no: int | None = None


class TabloOlustur(BaseModel):
    icerik: dict[str, Any] | None = None


class IcerikGuncelle(BaseModel):
    icerik: dict[str, Any]
    icerik_hash: str | None = HASH


class Gonder(BaseModel):
    icerik_hash: str | None = HASH


class PoKarari(BaseModel):
    icerik_hash: str | None = HASH
    gerekce: str | None = Field(default=None, max_length=2000)


class Degerlendir(BaseModel):
    girdiler: dict[str, Any] = Field(default_factory=dict)
    # Düzenleyicideki kaydedilmemiş içerik ("örnekle dene"); verilmezse kayıtlı içerik.
    icerik: dict[str, Any] | None = None


class IliskiOlustur(BaseModel):
    icerik: dict[str, Any]
    karar_tablosu_id: uuid.UUID | None = None


class IliskiGuncelle(BaseModel):
    icerik: dict[str, Any]
    icerik_hash: str | None = HASH
    # Alan gönderilmezse bağ korunur; `null` bağı kaldırır.
    karar_tablosu_id: uuid.UUID | None = None


def _gecersiz(session: DbSession, exc: KararTablosuGecersiz | IliskiGecersiz) -> JSONResponse:
    """Doğrulama hataları liste olarak da döner (`hatalar`); işlem geri alınır."""
    session.rollback()
    return JSONResponse(
        {"detail": str(exc), "kod": exc.kod, "hatalar": exc.hatalar}, status_code=422
    )


def _oge(session: DbSession, nesne: Any) -> dict[str, Any]:
    session.flush()
    return service.serialize(session, [nesne])[0]


# ---------------------------------------------------------------------- liste ve AI taslağı


@router.get("/requirements/{requirement_id}/decision-tables")
def list_tables(
    requirement_id: uuid.UUID, session: DbSession, _u: CurrentUser, tumu: bool = False
) -> dict[str, Any]:
    return service.listele(session, requirement_id, tumu=tumu)


@router.post(
    "/requirements/{requirement_id}/decision-tables/draft",
    response_model=IsYaniti,
    status_code=202,
)
def draft_tables(requirement_id: uuid.UUID, session: DbSession, user: Analyst) -> IsYaniti:
    sonuc = service.taslak_baslat(session, requirement_id, user)
    return IsYaniti(
        job_id=sonuc["job_id"],
        workflow_id=sonuc["workflow_id"],
        durum="started",
        mesaj=(
            "Karar tablosu taslağı başlatıldı."
            if sonuc["yeni"]
            else "Bu gereksinim için süren bir taslak işi var."
        ),
    )


# ---------------------------------------------------------------------- karar tablosu


@router.post("/requirements/{requirement_id}/decision-tables", status_code=201, response_model=None)
def create_table(
    requirement_id: uuid.UUID,
    session: DbSession,
    user: Analyst,
    body: TabloOlustur | None = None,
) -> dict[str, Any] | JSONResponse:
    try:
        t = service.tablo_olustur(session, requirement_id, user, body.icerik if body else None)
    except KararTablosuGecersiz as exc:
        return _gecersiz(session, exc)
    return _oge(session, t)


@router.put("/decision-tables/{tablo_id}", response_model=None)
def update_table(
    tablo_id: uuid.UUID, body: IcerikGuncelle, session: DbSession, user: Analyst
) -> dict[str, Any] | JSONResponse:
    try:
        t = service.tablo_guncelle(session, tablo_id, user, body.icerik, body.icerik_hash)
    except KararTablosuGecersiz as exc:
        return _gecersiz(session, exc)
    return _oge(session, t)


@router.post("/decision-tables/{tablo_id}/evaluate")
def evaluate_table(
    tablo_id: uuid.UUID, body: Degerlendir, session: DbSession, _u: CurrentUser
) -> dict[str, Any]:
    return service.tablo_degerlendir(session, tablo_id, body.girdiler, body.icerik)


# ---------------------------------------------------------------------- metamorfik ilişki


@router.post("/requirements/{requirement_id}/relations", status_code=201, response_model=None)
def create_relation(
    requirement_id: uuid.UUID, body: IliskiOlustur, session: DbSession, user: Analyst
) -> dict[str, Any] | JSONResponse:
    try:
        n = service.iliski_olustur(
            session, requirement_id, user, body.icerik, body.karar_tablosu_id
        )
    except IliskiGecersiz as exc:
        return _gecersiz(session, exc)
    return _oge(session, n)


@router.put("/relations/{iliski_id}", response_model=None)
def update_relation(
    iliski_id: uuid.UUID, body: IliskiGuncelle, session: DbSession, user: Analyst
) -> dict[str, Any] | JSONResponse:
    bag: Any = (
        body.karar_tablosu_id if "karar_tablosu_id" in body.model_fields_set else service.BAG_KORU
    )
    try:
        n = service.iliski_guncelle(session, iliski_id, user, body.icerik, body.icerik_hash, bag)
    except IliskiGecersiz as exc:
        return _gecersiz(session, exc)
    return _oge(session, n)


# ---------------------------------------------------------------------- durum geçişleri (iki tür)


def _gecis_uclari(onek: str, tur: str, ad: str) -> None:
    """`/<onek>/{id}/submit|withdraw|reopen|approve|request-changes` uçlarını kaydeder."""

    @router.post(f"/{onek}/{{nesne_id}}/submit", name=f"{ad}_submit", response_model=None)
    def submit(
        nesne_id: uuid.UUID, session: DbSession, user: Analyst, body: Gonder | None = None
    ) -> dict[str, Any] | JSONResponse:
        try:
            n = service.gonder(session, tur, nesne_id, user, body.icerik_hash if body else None)
        except (KararTablosuGecersiz, IliskiGecersiz) as exc:
            return _gecersiz(session, exc)
        return _oge(session, n)

    @router.post(f"/{onek}/{{nesne_id}}/withdraw", name=f"{ad}_withdraw")
    def withdraw(nesne_id: uuid.UUID, session: DbSession, user: Analyst) -> dict[str, Any]:
        return _oge(session, service.geri_cek(session, tur, nesne_id, user))

    @router.post(f"/{onek}/{{nesne_id}}/reopen", name=f"{ad}_reopen")
    def reopen(nesne_id: uuid.UUID, session: DbSession, user: Analyst) -> dict[str, Any]:
        return _oge(session, service.yeniden_ac(session, tur, nesne_id, user))

    @router.post(f"/{onek}/{{nesne_id}}/approve", name=f"{ad}_approve")
    def approve(
        nesne_id: uuid.UUID, body: PoKarari, session: DbSession, user: Po
    ) -> dict[str, Any]:
        return _oge(session, service.onayla(session, tur, nesne_id, user, body.icerik_hash))

    @router.post(f"/{onek}/{{nesne_id}}/request-changes", name=f"{ad}_request_changes")
    def request_changes(
        nesne_id: uuid.UUID, body: PoKarari, session: DbSession, user: Po
    ) -> dict[str, Any]:
        n = service.degisiklik_iste(session, tur, nesne_id, user, body.icerik_hash, body.gerekce)
        return _oge(session, n)


_gecis_uclari("decision-tables", service.TABLO, "decision_table")
_gecis_uclari("relations", service.ILISKI, "relation")
