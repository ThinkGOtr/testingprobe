"""Locator onarımı uçları (MIMARI-SOZLESME §5).

| Yöntem | Yol | Rol |
|---|---|---|
| POST | `/failures/{id}/fix` | engineer — locator onarım PR'ı (202; iş `repair.fix`) |
| GET  | `/failures/{id}/fix` | herkes — onarım durumu ve kaydı (kanıt, AST, kontrol, PR) |

Merge `/prs/{number}/merge` üzerinden yapılır (codegen ucu, PR onarıma aitse
`repair.service.request_merge`'e yönlendirir; entegrasyon isteği). Ortam (`environment`) sınıfı
ve sağlık kontrolü başarısız koşular 409 ile reddedilir (Constitution XI).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.features.repair import service, views
from tp_core.workflow.service import Principal

router = APIRouter(tags=["repair"])

Engineer = Annotated[Principal, Depends(require_role("engineer"))]


@router.post("/failures/{failure_id}/fix", status_code=202)
def fix(failure_id: uuid.UUID, session: DbSession, user: Engineer) -> dict[str, Any]:
    return service.request_fix(session, failure_id, user)


@router.get("/failures/{failure_id}/fix")
def fix_status(failure_id: uuid.UUID, session: DbSession, _user: CurrentUser) -> dict[str, Any]:
    blok = views.oneri_blogu(session, failure_id)
    if blok is None:
        raise HTTPException(404, "Bu hata için onarım başlatılmadı")
    return blok
