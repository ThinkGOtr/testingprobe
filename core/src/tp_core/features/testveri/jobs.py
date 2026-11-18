"""Test verisi kataloğu işleri (specs/013-sprint-otomasyonu §3.3; kaynaklar: `kaynak`).

- `testveri.yenile`: projenin veritabanı kaynaklarını koşar, kataloğu idempotent günceller
  (`kaynak.yenile`; yalnız core-worker projenin salt okuma veritabanına bağlanır).
- `testveri.onizle`: kaydedilmemiş bir kaynak tanımının ilk satırları ve çıkacak kayıtlar
  (`kaynak.onizle`); katalog değişmez. Sonuç işin `sonuc` alanındadır (portal yoklar).
- `on_worker_start`: varsayılan projenin (Bayi Portalı) tohumu: ön tanımlı kaynaklar + sabitler;
  katalogda olmayan anahtarlar eklenir (idempotent, var olan değere dokunmaz).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import Connection
from sqlalchemy.orm import Session

from tp_core.features.testveri import kaynak
from tp_core.features.testveri.service import TestVerisiHatasi, tohumla
from tp_core.models import session_scope
from tp_core.proje import proje_icinde, varsa, varsayilan_pid
from tp_core.workflow.jobs import JobContext, job_handler

log = logging.getLogger(__name__)


def _aktor(ctx: JobContext) -> str:
    return str((ctx.yuk or {}).get("aktor") or "system")[:100]


@job_handler(kaynak.YENILE_JOB, max_deneme=1, zaman_asimi_s=300)
def yenile(ctx: JobContext) -> dict[str, Any]:
    ham = (ctx.yuk or {}).get("kaynak_id")
    kid = uuid.UUID(str(ham)) if ham else None
    with session_scope() as s:
        return kaynak.yenile(s, _aktor(ctx), kaynak_id=kid)


@job_handler(kaynak.ONIZLE_JOB, max_deneme=1, zaman_asimi_s=120)
def onizle(ctx: JobContext) -> dict[str, Any]:
    try:
        tanim = kaynak.tanim_dogrula((ctx.yuk or {}).get("tanim") or {})
        with session_scope() as s:
            return kaynak.onizle(s, tanim)
    except (kaynak.KaynakHatasi, TestVerisiHatasi) as exc:
        return {"hata": str(exc)[:500]}


def on_worker_start(conn: Connection) -> None:
    """Tohum kayıtları varsayılan projenin (bugünkü demo uygulaması) verisidir: yalnız o projeye
    eklenir (bağlamsız açılışta da), başka projenin kataloğuna sızmaz (TP-COK-PROJE-PLANI §3.3).
    Worker kancayı her proje için o projenin bağlamında çağırır; diğer projelerde etkisizdir
    (onların kataloğu tanımladıkları veritabanı kaynaklarının "Yenile" işiyle dolar)."""
    b = varsa()
    if b is None:
        with proje_icinde(varsayilan_pid(), kaynak="sistem"):
            return on_worker_start(conn)
    if b.pid != varsayilan_pid():
        return None
    with Session(bind=conn, join_transaction_mode="rollback_only") as session:
        n = tohumla(session)
        session.commit()
    if n:
        log.info("test verisi kataloğuna %d tohum kaydı eklendi", n)
