"""Oracle uçları (012 ANALIZ §6).

| Yöntem | Yol | İzin (auth/yetki.py) |
|---|---|---|
| GET  | `/cases/{id}/oracle?icerik_hash=` | `case.oracle_read` — güncel/önerilen içerik sonucu |
| POST | `/cases/{id}/oracle-check` `{icerik?}` | `case.oracle_check` → 202 `{job_id,icerik_hash}` |

`POST` önerilen içeriği case içerik doğrulamasıyla (şema + AC atıfları) denetler; içerik case'e
yazılmaz. Sonuç `oracle.checked` olayıyla duyurulur, `GET` ile okunur. Önerilen içerik kapıyla
aynı biçimde saklı ∪ önerilen AC ref'leriyle kontrol edilir (V11). İş `(case, hash, tablo kümesi,
kayıt sürümü)` anahtarlıdır (aynı istek yeni model çağrısı açmaz). Hız sınırı her kaynak için
`service.kontrol_kuyruga_al`'dadır: case, gereksinim ve kullanıcı başına dakikalık yeni iş
(aşılırsa 429 `oracle_kontrol_siniri`; review 1 güvenlik 10, review 2 g2 Y6).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from tp_core.audit import content_hash
from tp_core.auth.deps import DbSession
from tp_core.auth.yetki import izin
from tp_core.features.cases import service as cases_service
from tp_core.features.cases.schema import content_errors
from tp_core.features.oracle import service
from tp_core.features.oracle.tablolar import tablo_hashleri
from tp_core.workflow.service import Principal

router = APIRouter(tags=["oracle"])

# İzinler tek katalogdan (auth/yetki.py). Kontrol sonucu ve istisna gerekçesi karar geçmişidir:
# developer (kısıtlı case görünümü), auditor ve viewer okumaz.
Kontrolcu = Annotated[Principal, Depends(izin("case.oracle_check"))]
Okuyucu = Annotated[Principal, Depends(izin("case.oracle_read"))]


class KontrolIstegi(BaseModel):
    # Düzeltme formundaki önerilen içerik; verilmezse case'in güncel içeriği kontrol edilir.
    icerik: dict[str, Any] | None = None


class KontrolYaniti(BaseModel):
    job_id: uuid.UUID
    icerik_hash: str


@router.get("/cases/{case_id}/oracle")
def get_oracle(
    case_id: uuid.UUID, session: DbSession, _user: Okuyucu, icerik_hash: str | None = None
) -> dict[str, Any]:
    tc = cases_service.get_case(session, case_id)
    return service.case_oracle(session, tc, icerik_hash)


@router.post("/cases/{case_id}/oracle-check", response_model=KontrolYaniti, status_code=202)
def oracle_check(
    case_id: uuid.UUID, session: DbSession, user: Kontrolcu, body: KontrolIstegi | None = None
) -> KontrolYaniti:
    tc = cases_service.get_case(session, case_id)
    icerik = body.icerik if body is not None else None
    if icerik is not None:
        req = cases_service.get_requirement(session, tc.requirement_id)
        hatalar = content_errors(icerik, req.kabul_kriterleri)
        if hatalar:
            raise cases_service.InvalidCaseContent("Önerilen case içeriği şemaya uymuyor", hatalar)
        h = content_hash(dict(icerik))
    else:
        h = tc.icerik_hash
    gonderilen = icerik if h != tc.icerik_hash else None
    taban = service.tabanlar(session, [tc])[tc.id]
    kapsayan = service.kapsayan_tablolar(session, tc, gonderilen, taban=taban)
    anahtar = service.kontrol_anahtari(
        "istek",
        tc.id,
        h,
        service.tablo_ozeti(tablo_hashleri(kapsayan)),
        service.kayit_damgasi(service.kayit_bul(session, tc.id, h)),
    )
    job_id = service.kontrol_kuyruga_al(
        session,
        tc.id,
        h,
        gonderilen,
        ac_refs=service.kontrol_refleri(taban, gonderilen) if gonderilen is not None else None,
        idempotency_key=anahtar,
        isteyen_id=user.id,
    )
    assert job_id is not None  # sinir_hatasi=True: sınır aşımı 429 fırlatır
    return KontrolYaniti(job_id=job_id, icerik_hash=h)
