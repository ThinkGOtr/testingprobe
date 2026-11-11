"""Case uçları (MIMARI-SOZLESME §5; TEKNIK-TASARIM §9; specs/012-rol-yetki/ANALIZ.md §4–§5).

| Yöntem | Yol | İzin |
|---|---|---|
| POST | `/requirements/{id}/generate-cases` | `case.generate` — yalnızca PO onaylı gereksinim |
| GET  | `/cases?requirement_id=` | `case.read` (developer: yalnız approved/published, geçmiş yok) |
| GET  | `/cases/{id}` | `case.read` (developer: aynı süzgeç; görünmeyen case 404) |
| POST | `/cases/{id}/viewed` | `case.decide` — ilk görüntüleme (review süresinin başlangıcı) |
| POST | `/cases/{id}/decision` (aşağıda `CaseKararGirdisi`) | karar başına: `case.decide` (accept, edit, reject, reopen) / `case.approve` (approve, send_back) |
| GET  | `/requirements/{id}/case-metrics` | `case.read` — kabul oranı ve süreler (§12); developer: yalnız durum sayıları |
| POST | `/requirements/{id}/review-complete` | `case.approve` |
"""  # noqa: E501

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from tp_core.auth.deps import CurrentUser, DbSession
from tp_core.auth.yetki import izin, izinli, reddet
from tp_core.features.cases import service
from tp_core.workflow.service import Principal
from tp_core.workflow.states import TEST_CASE_KARAR_IZNI

router = APIRouter(tags=["cases"])

Uretici = Annotated[Principal, Depends(izin("case.generate"))]
Okuyucu = Annotated[Principal, Depends(izin("case.read"))]
Karar = Annotated[Principal, Depends(izin("case.decide"))]
SonOnay = Annotated[Principal, Depends(izin("case.approve"))]


class IsYaniti(BaseModel):
    job_id: uuid.UUID | None
    durum: str
    mesaj: str | None = None
    workflow_id: uuid.UUID | None = None
    uretim_no: int | None = None


class CaseKararGirdisi(BaseModel):
    # Testçi: accept | edit | reject | reopen · Analist (son onay): approve | send_back.
    karar: Literal["accept", "edit", "reject", "reopen", "approve", "send_back"]
    # Kullanıcının ekranda gördüğü içeriğin hash'i (edit'te düzeltme ÖNCESİ). Portalda zorunlu.
    icerik_hash: str | None = None
    icerik: dict[str, Any] | None = None
    ret_nedeni: (
        Literal[
            "hallucinated_step",
            "missing_ac",
            "wrong_test_data",
            "out_of_scope",
            "duplicate",
            "wrong_element",
        ]
        | None
    ) = None
    # `send_back`'te zorunlu; `reject`/`reopen`'da isteğe bağlı not.
    gerekce: str | None = Field(default=None, max_length=2000)
    # §12 "beklenen sonuç anlamca değişmedi" insan yargısı (verilmezse metin karşılaştırması).
    beklenen_anlam_degisti: bool | None = None


@router.post(
    "/requirements/{requirement_id}/generate-cases", response_model=IsYaniti, status_code=202
)
def generate_cases(requirement_id: uuid.UUID, session: DbSession, user: Uretici) -> IsYaniti:
    sonuc = service.start_generation(session, requirement_id, user)
    return IsYaniti(
        job_id=sonuc["job_id"],
        workflow_id=sonuc["workflow_id"],
        uretim_no=sonuc["uretim_no"],
        durum="started",
        mesaj="Case üretimi başlatıldı.",
    )


@router.get("/cases")
def list_cases(
    session: DbSession, user: Okuyucu, requirement_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    return service.list_cases(session, requirement_id, user)


@router.get("/cases/{case_id}")
def get_case(case_id: uuid.UUID, session: DbSession, user: Okuyucu) -> dict[str, Any]:
    return service.get_case_view(session, case_id, user)


@router.post("/cases/{case_id}/viewed")
def mark_viewed(case_id: uuid.UUID, session: DbSession, user: Karar) -> dict[str, Any]:
    return service.mark_viewed(session, case_id, user)


@router.post("/cases/{case_id}/decision")
def decide(
    case_id: uuid.UUID,
    body: CaseKararGirdisi,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> dict[str, Any]:
    # İzin karara göre: Testçi kararları `case.decide`, son onay `case.approve` (ANALIZ §4.1).
    izin_adi = TEST_CASE_KARAR_IZNI[body.karar]
    if not izinli(user.rol, izin_adi):
        raise reddet(session, user, izin_adi, "rol", request.url.path)
    tc = service.decide(
        session,
        case_id,
        user,
        karar=body.karar,
        icerik_hash=body.icerik_hash,
        icerik=body.icerik,
        ret_nedeni=body.ret_nedeni,
        gerekce=body.gerekce,
        beklenen_anlam_degisti=body.beklenen_anlam_degisti,
    )
    session.flush()
    return service.serialize_cases(session, [tc], user)[0]


@router.get("/requirements/{requirement_id}/case-metrics")
def case_metrics(requirement_id: uuid.UUID, session: DbSession, user: Okuyucu) -> dict[str, Any]:
    if service.kisitli_gorunum(user):
        return service.requirement_metrics_kisitli(session, requirement_id)
    return service.requirement_metrics(session, requirement_id)


@router.post("/requirements/{requirement_id}/review-complete")
def review_complete(requirement_id: uuid.UUID, session: DbSession, user: SonOnay) -> dict[str, Any]:
    return service.review_complete(session, requirement_id, user)
