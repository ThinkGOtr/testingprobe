"""Test tasarım modeli uçları (specs/011 F3, §4.4).

| Yöntem | Yol | Rol |
|---|---|---|
| GET  | `/requirements/{id}/design-model` | herkes — son model + geçmiş özeti |
| POST | `/requirements/{id}/design-model` | analyst — modeli (yeniden) üret (202) |
| POST | `/design-models/{id}/decision` (`ModelKararGirdisi`) | analyst — approve/edit/reject; K20 |

İki turun başlangıcı ve onaylı modelden case üretimi `POST /requirements/{id}/generate-cases`
(`{kip: "iki_tur"}`) ucundadır (`features.cases.api`).
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator

from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.features.cases import model_service
from tp_core.features.cases.api import IsYaniti
from tp_core.workflow.service import Principal

router = APIRouter(tags=["design-model"])

Analyst = Annotated[Principal, Depends(require_role("analyst"))]


# Düzenlenen modelin JSON boyutu üst sınırı (karakter). Golden modeller ~20K; büyük gövde
# doğrulama/hash/kayıt maliyetini şişirmesin (422).
MODEL_ICERIK_SINIRI = 200_000


class ModelKararGirdisi(BaseModel):
    """Tasarım modeli kararı. Bilinmeyen alan reddedilir (422); ret nedenleri modele özgüdür
    (`workflow.states.MODEL_RET_NEDENLERI`; case taksonomisinin kopyası değil)."""

    model_config = ConfigDict(extra="forbid")

    karar: Literal["approve", "edit", "reject"]
    # Ekranda görülen modelin hash'i (edit'te düzeltme ÖNCESİ). Zorunlu.
    icerik_hash: str | None = Field(default=None, max_length=128)
    icerik: dict[str, Any] | None = None
    ret_nedeni: (
        Literal[
            "wrong_technique",
            "missing_condition",
            "wrong_coverage_item",
            "wrong_boundary",
            "invented_rule",
            "missing_ac",
            "out_of_scope",
        ]
        | None
    ) = None
    gerekce: str | None = Field(default=None, max_length=2000)

    @field_validator("icerik")
    @classmethod
    def _boyut(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and len(json.dumps(v, ensure_ascii=False)) > MODEL_ICERIK_SINIRI:
            raise ValueError(f"model içeriği en fazla {MODEL_ICERIK_SINIRI} karakter olabilir")
        return v


@router.get("/requirements/{requirement_id}/design-model")
def get_design_model(
    requirement_id: uuid.UUID, session: DbSession, _user: CurrentUser
) -> dict[str, Any]:
    return model_service.design_model_view(session, requirement_id)


@router.post(
    "/requirements/{requirement_id}/design-model", response_model=IsYaniti, status_code=202
)
def regenerate_design_model(
    requirement_id: uuid.UUID, session: DbSession, user: Analyst
) -> IsYaniti:
    sonuc = model_service.start_model_generation(session, requirement_id, user)
    return IsYaniti(
        job_id=sonuc["job_id"],
        workflow_id=sonuc["workflow_id"],
        durum="started",
        mesaj="Test tasarım modeli üretimi başlatıldı (iki tur).",
        kip="iki_tur",
        asama="model",
    )


@router.post("/design-models/{model_id}/decision")
def decide_design_model(
    model_id: uuid.UUID, body: ModelKararGirdisi, session: DbSession, user: Analyst
) -> dict[str, Any]:
    """Karar; onayda (approve | edit) tur 2 aynı işlemde başlar (011 K20): yanıt model
    görünümüne ek `tur2_baslatildi`, `tur2` (iş bilgisi) ve `tur2_engeli` taşır."""
    return model_service.decide_and_continue(
        session,
        model_id,
        user,
        karar=body.karar,
        icerik_hash=body.icerik_hash,
        icerik=body.icerik,
        ret_nedeni=body.ret_nedeni,
        gerekce=body.gerekce,
    )
