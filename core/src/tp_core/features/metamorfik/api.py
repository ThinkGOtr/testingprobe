"""Metamorfik türetme uçları (ANALIZ §6).

| Yöntem | Yol | İzin (auth/yetki.py) |
|---|---|---|
| POST | `/requirements/{id}/metamorphic-cases` `{iliski_id, case_ids?}` | `case.generate` |
| GET  | `/requirements/{id}/metamorphic-derivations` | `case.oracle_read` |

POST yanıtı: `{turetilen: [{case_id, kaynak_case_id, baslik}], atlanan: [{kaynak_case_id, sonuc,
neden}]}`. `atlanan[].sonuc`: `iliski_gecersiz | belirsiz_alinti | olgu_yok | zaten_turetildi`
(`tutarsiz_kalan_deger` değer kümesine eklenene dek `belirsiz_alinti` + `neden`
"tutarsiz_kalan_deger: …"). İlişki bulunamazsa 404 `iliski_bulunamadi`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from tp_core.auth.deps import DbSession
from tp_core.auth.yetki import izin
from tp_core.features.metamorfik import service
from tp_core.workflow.service import Principal

router = APIRouter(tags=["metamorfik"])

# İzinler tek katalogdan (auth/yetki.py): ilişkiden ek case türetmek case üretimidir (Testçi);
# türetme kayıtları case kontrol sonuçlarıyla aynı okuyucuya açıktır.
Uretici = Annotated[Principal, Depends(izin("case.generate"))]
Okuyucu = Annotated[Principal, Depends(izin("case.oracle_read"))]


class TuretmeGirdisi(BaseModel):
    iliski_id: uuid.UUID
    # Verilmezse ilişkinin AC'lerine atıf yapan bütün güncel case'ler kaynak olur.
    case_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=200)


class Turetilen(BaseModel):
    case_id: str
    kaynak_case_id: str
    baslik: str


class Atlanan(BaseModel):
    kaynak_case_id: str
    sonuc: str
    neden: str | None


class TuretmeYaniti(BaseModel):
    turetilen: list[Turetilen]
    atlanan: list[Atlanan]


@router.post("/requirements/{requirement_id}/metamorphic-cases", response_model=TuretmeYaniti)
def metamorphic_cases(
    requirement_id: uuid.UUID, body: TuretmeGirdisi, session: DbSession, user: Uretici
) -> dict[str, Any]:
    return service.turet(session, requirement_id, body.iliski_id, body.case_ids, user)


@router.get("/requirements/{requirement_id}/metamorphic-derivations")
def metamorphic_derivations(
    requirement_id: uuid.UUID, session: DbSession, _user: Okuyucu
) -> list[dict[str, Any]]:
    return service.turetmeler(session, requirement_id)
