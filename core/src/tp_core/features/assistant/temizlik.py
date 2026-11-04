"""Asistan verisinin saklama temizliği (AI-ASISTAN-PLANI §8, Şerit KK).

Kalıcı bir bakım zamanlayıcısı yok; periyodik işler kendini yeniden planlayan kuyruk işleridir
(`triage.sweep`, `requirements.po_poll` deseni). `assistant.cleanup` da öyle: worker açılışında
(`features.assistant.jobs.on_worker_start` → `planla`) kuyrukta bekleyen yoksa hemen eklenir, her
koşunun sonunda (hata olsa da) `TP_ASISTAN_TEMIZLIK_S` (varsayılan 6 saat; 0 = kapalı) sonrasına
yeniden planlanır. Genel şeritte koşar (asistan şeridini meşgul etmez).

Saklama süresi `TP_ASISTAN_SAKLAMA_GUN` (varsayılan 90; geçersiz değer varsayılana döner, en az 1):

- **Sohbet:** son etkinliği (`guncelleme`, `silinme`, en yeni mesajın `olusturma`'sı) süreden eski
  sohbet fiziksel olarak silinir; **yumuşak silinenler dahil** (`silindi` fark etmez). Bekleyen
  (`pending`/`running`) mesajı olan sohbete dokunulmaz. Mesajlar `ON DELETE CASCADE` ile gider.
- **Mesaj:** tek tek silinmez. Saklama sohbet düzeyindedir (K4, panel: "sohbet 90 gün saklanır"):
  kullanılan bir sohbetin eski soruları ve onlara bağlı "Daha ayrıntılı" cevapları (`ust_mesaj_id`
  CASCADE) yarım kalmaz; sohbet son etkinliğinden süre kadar sonra bütünüyle gider.
- **Öneri geri bildirimi** (`asistan_oneri_geri_bildirim`): süreden eski satırlar silinir; "Gizle"
  bastırması da bu süre sonunda kalkar.
- **Hız sayacı** (`asistan_hiz`): 1 günden eski pencereler (`hiz.hiz_temizle`).
- `ai_call` ve `tool_call` append-only denetim kayıtlarıdır, **dokunulmaz** (kişi bağı
  `ai_call.ek` ile kalır; Kontrol Kulesi maliyeti bu yüzden saklama süresinden etkilenmez).

Silinen satır sayıları iş sonucuna yazılır; içerik (soru/cevap metni) hiçbir yere yazılmaz.
Temizlik işinin kendi bitmiş kayıtları 1 günden sonra `job` tablosundan silinir.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from tp_core.db import get_engine
from tp_core.features.assistant import hiz
from tp_core.workflow import jobs as jobq
from tp_core.workflow.jobs import JobContext, job_handler

log = logging.getLogger("tp_core.worker")

TEMIZLIK_IS_TURU: Final = "assistant.cleanup"
VARSAYILAN_SAKLAMA_GUN: Final = 90
VARSAYILAN_ARALIK_S: Final = 6 * 3600
# Temizlik işinin bitmiş kendi `job` kayıtlarının saklama süresi.
IS_KAYDI_SAKLAMA: Final = timedelta(days=1)


def saklama_gun(ortam: Mapping[str, str] | None = None) -> int:
    """`TP_ASISTAN_SAKLAMA_GUN` (varsayılan 90; geçersiz → varsayılan; en az 1)."""
    ham = ((ortam if ortam is not None else os.environ).get("TP_ASISTAN_SAKLAMA_GUN") or "").strip()
    if not ham:
        return VARSAYILAN_SAKLAMA_GUN
    try:
        return max(int(ham), 1)
    except ValueError:
        return VARSAYILAN_SAKLAMA_GUN


def aralik_s(ortam: Mapping[str, str] | None = None) -> float:
    """`TP_ASISTAN_TEMIZLIK_S` (varsayılan 6 saat; 0 = periyodik temizlik kapalı)."""
    ham = ((ortam if ortam is not None else os.environ).get("TP_ASISTAN_TEMIZLIK_S") or "").strip()
    if not ham:
        return float(VARSAYILAN_ARALIK_S)
    try:
        return max(float(ham), 0.0)
    except ValueError:
        return float(VARSAYILAN_ARALIK_S)


_SOHBET_SIL = text(
    """
    DELETE FROM asistan_sohbet s
    -- GREATEST NULL'ları yok sayar: silinmemiş ya da mesajsız sohbette `guncelleme` belirler.
    WHERE GREATEST(
            s.guncelleme,
            s.silinme,
            (SELECT max(m.olusturma) FROM asistan_mesaj m WHERE m.sohbet_id = s.id)
          ) < now() - make_interval(days => :g)
      AND NOT EXISTS (
            SELECT 1 FROM asistan_mesaj m
            WHERE m.sohbet_id = s.id AND m.durum IN ('pending', 'running')
          )
    """
)

_GERI_BILDIRIM_SIL = text(
    "DELETE FROM asistan_oneri_geri_bildirim WHERE olusturma < now() - make_interval(days => :g)"
)


def temizle(session: Session, *, gun: int | None = None) -> dict[str, int]:
    """Saklama süresini aşan asistan verisini çağıranın işleminde siler; tablo başına sayılar.

    Mesajlar yalnız sohbetleriyle (CASCADE) gider; sayıları `sohbet`'in içindedir.
    """
    g = saklama_gun() if gun is None else max(int(gun), 1)
    sohbet = session.execute(_SOHBET_SIL, {"g": g}).rowcount or 0
    geri_bildirim = session.execute(_GERI_BILDIRIM_SIL, {"g": g}).rowcount or 0
    hiz_sayisi = hiz.hiz_temizle(session)
    return {
        "saklama_gun": g,
        "sohbet": int(sohbet),
        "oneri_geri_bildirim": int(geri_bildirim),
        "hiz": int(hiz_sayisi),
    }


def planla(conn: Connection, *, gecikme_s: float = 0.0) -> Any:
    """Temizlik işi kuyrukta bekleyen yoksa ekler (tek bekleyen iş); kapalıysa None."""
    if aralik_s() <= 0:
        return None
    jobq.idempotency_lock(conn, TEMIZLIK_IS_TURU)
    bekleyen = conn.execute(
        text("SELECT id FROM job WHERE tur = :t AND durum IN ('queued', 'retry') LIMIT 1"),
        {"t": TEMIZLIK_IS_TURU},
    ).scalar_one_or_none()
    if bekleyen is not None:
        return None
    zaman = datetime.now(UTC) + timedelta(seconds=gecikme_s) if gecikme_s > 0 else None
    return jobq.enqueue(conn, TEMIZLIK_IS_TURU, {}, run_after=zaman)


def is_kayitlarini_sil(engine: Engine, saklama: timedelta = IS_KAYDI_SAKLAMA) -> int:
    """Temizlik işinin bitmiş eski `job` kayıtları (kuyruk şişmesin)."""
    with engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    "DELETE FROM job WHERE tur = :t AND durum IN ('done', 'failed', 'cancelled') "
                    "AND COALESCE(bitis, guncelleme) < now() - make_interval(secs => :sn)"
                ),
                {"t": TEMIZLIK_IS_TURU, "sn": saklama.total_seconds()},
            ).rowcount
            or 0
        )


@job_handler(TEMIZLIK_IS_TURU, max_deneme=1, zaman_asimi_s=300)
def temizlik(_ctx: JobContext) -> dict[str, Any]:
    engine = get_engine()
    try:
        with Session(engine) as session, session.begin():
            sonuc = temizle(session)
        sonuc["is_kaydi"] = is_kayitlarini_sil(engine)
        if any(sonuc[k] for k in ("sohbet", "oneri_geri_bildirim")):
            log.info(
                "asistan saklama temizliği (%d gün): %d sohbet, %d öneri geri bildirimi",
                sonuc["saklama_gun"],
                sonuc["sohbet"],
                sonuc["oneri_geri_bildirim"],
            )
        return sonuc
    finally:
        # Zincir kopmasın: hata olsa da bir sonraki temizlik planlanır.
        with engine.begin() as conn:
            planla(conn, gecikme_s=aralik_s())
