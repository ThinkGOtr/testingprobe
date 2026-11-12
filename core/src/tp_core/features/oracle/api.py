"""Oracle uçları (012 ANALIZ §6).

| Yöntem | Yol | Rol |
|---|---|---|
| GET  | `/cases/{id}/oracle?icerik_hash=` | herkes — güncel ya da önerilen içeriğin sonucu |
| POST | `/cases/{id}/oracle-check` `{icerik?}` | analyst — 202 `{job_id, icerik_hash}`) |

`POST` önerilen içeriği case içerik doğrulamasıyla (şema + AC atıfları) denetler; içerik case'e
yazılmaz. Sonuç `oracle.checked` olayıyla duyurulur, `GET` ile okunur. Önerilen içerik kapıyla
aynı biçimde saklı ∪ önerilen AC ref'leriyle kontrol edilir (V11). İş `(case, hash, tablo kümesi,
kayıt sürümü)` anahtarlıdır (aynı istek yeni model çağrısı açmaz); case başına dakikada
`DAKIKA_SINIRI` yeni iş (aşılırsa 429 `oracle_kontrol_siniri`; review 1 güvenlik 10).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from tp_core.audit import content_hash
from tp_core.auth.deps import CurrentUser, DbSession, require_role
from tp_core.features.cases import service as cases_service
from tp_core.features.cases.schema import content_errors
from tp_core.features.karar_tablosu.hatalar import OracleKontrolSiniri
from tp_core.features.oracle import service
from tp_core.features.oracle.tablolar import tablo_hashleri
from tp_core.workflow.service import Principal

router = APIRouter(tags=["oracle"])

DAKIKA_SINIRI = 10

Analyst = Annotated[Principal, Depends(require_role("analyst"))]


class KontrolIstegi(BaseModel):
    # Düzeltme formundaki önerilen içerik; verilmezse case'in güncel içeriği kontrol edilir.
    icerik: dict[str, Any] | None = None


class KontrolYaniti(BaseModel):
    job_id: uuid.UUID
    icerik_hash: str


@router.get("/cases/{case_id}/oracle")
def get_oracle(
    case_id: uuid.UUID, session: DbSession, _user: CurrentUser, icerik_hash: str | None = None
) -> dict[str, Any]:
    tc = cases_service.get_case(session, case_id)
    return service.case_oracle(session, tc, icerik_hash)


@router.post("/cases/{case_id}/oracle-check", response_model=KontrolYaniti, status_code=202)
def oracle_check(
    case_id: uuid.UUID, session: DbSession, _user: Analyst, body: KontrolIstegi | None = None
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
    ac_refs = service.ac_refleri(tc.icerik, gonderilen) if gonderilen is not None else None
    kapsayan = service.kapsayan_tablolar(session, tc, gonderilen, ac_refs=ac_refs)
    anahtar = service.kontrol_anahtari(
        "istek",
        tc.id,
        h,
        service.tablo_ozeti(tablo_hashleri(kapsayan)),
        service.kayit_damgasi(service.kayit_bul(session, tc.id, h)),
    )
    _hiz_siniri(session, tc.id, anahtar)
    job_id = service.kontrol_kuyruga_al(
        session, tc.id, h, gonderilen, ac_refs=ac_refs, idempotency_key=anahtar
    )
    return KontrolYaniti(job_id=job_id, icerik_hash=h)


def _hiz_siniri(session: DbSession, case_id: uuid.UUID, anahtar: str) -> None:
    """Var olan anahtarın işi yeniden döner (sınıra takılmaz); yeni iş için son bir dakikada aynı
    case'e açılmış `oracle.check_case` işleri sayılır."""
    conn = session.connection()
    if conn.execute(
        text(
            "SELECT 1 FROM job WHERE idempotency_key = :k AND durum NOT IN ('failed', 'cancelled')"
        ),
        {"k": anahtar},
    ).first():
        return
    son = conn.execute(
        text(
            "SELECT count(*) FROM job WHERE tur = :t AND yuk->>'case_id' = :c "
            "AND olusturma > now() - interval '1 minute'"
        ),
        {"t": service.CHECK_CASE_JOB, "c": str(case_id)},
    ).scalar_one()
    if son >= DAKIKA_SINIRI:
        raise OracleKontrolSiniri(
            f"Bu case için son bir dakikada {son} kontrol istendi; biraz bekleyip yeniden deneyin"
        )
