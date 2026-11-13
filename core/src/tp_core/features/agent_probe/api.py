"""Agent Probe uçları (specs/011 §4.4, A şeridi; F6).

| Yöntem | Yol | Rol |
|---|---|---|
| GET | `/agent-probe/products` | herkes — Agent Probe'da hazır ajan ürünleri (simülasyon) |
| PUT | `/requirements/{id}/agent-product` (`{urun_kodu: str \\| null}`) | analyst — bağla/kaldır |
| POST | `/requirements/{id}/agent-test` | analyst — Agent Probe'da test başlat (202) |
| POST | `/requirements/{id}/agent-test/refresh` | analyst — durumu Agent Probe'dan oku, işle |
| GET | `/requirements/{id}/agent-test` | herkes — bağlantı + talep (yan etkisiz; yalnız okur) |

GET yan etkisizdir (güvenlik #8, backend #11): durum geçişi ve sonuç işleme yalnız POST
`…/refresh` ile (analist, CSRF korumalı) yapılır. Portal görünümdeki `yenilenebilir` true iken
(bitmemiş ya da işlenmemiş talep) analist oturumunda `refresh`'i yoklar.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from tp_core.auth.deps import DbSession
from tp_core.auth.yetki import izin
from tp_core.features.agent_probe import service
from tp_core.workflow.service import Principal

router = APIRouter(tags=["agent-probe"])

# 012 rol modeli (dev birleştirmesi): ürün bağlama gereksinim kapsamı kararıdır (Analist,
# `requirement.review`); ajan testini başlatma/sorgulama Testçinin (`agent_test.run`).
Baglayici = Annotated[Principal, Depends(izin("requirement.review"))]
Testci = Annotated[Principal, Depends(izin("agent_test.run"))]
Okur = Annotated[Principal, Depends(izin("requirement.read"))]


class UrunBaglamaGirdisi(BaseModel):
    urun_kodu: str | None = Field(default=None, max_length=100)


@router.get("/agent-probe/products")
def urunler(user: Okur) -> dict[str, Any]:
    kip, liste = service.urunler()
    return {"kip": kip, "simulasyon": True, "urunler": [u.model_dump() for u in liste]}


@router.put("/requirements/{requirement_id}/agent-product")
def urun_bagla(
    requirement_id: uuid.UUID, girdi: UrunBaglamaGirdisi, session: DbSession, user: Baglayici
) -> dict[str, Any]:
    service.urun_bagla(session, requirement_id, girdi.urun_kodu, user)
    return service.gorunum(session, requirement_id)


@router.post("/requirements/{requirement_id}/agent-test", status_code=202)
def test_baslat(requirement_id: uuid.UUID, session: DbSession, user: Testci) -> dict[str, Any]:
    service.test_baslat(session, requirement_id, user)
    return service.gorunum(session, requirement_id)


@router.post("/requirements/{requirement_id}/agent-test/refresh")
def test_yenile(requirement_id: uuid.UUID, session: DbSession, user: Testci) -> dict[str, Any]:
    service.yenile(session, requirement_id)
    return service.gorunum(session, requirement_id)


@router.get("/requirements/{requirement_id}/agent-test")
def ajan_testi(requirement_id: uuid.UUID, session: DbSession, user: Okur) -> dict[str, Any]:
    return service.gorunum(session, requirement_id)
