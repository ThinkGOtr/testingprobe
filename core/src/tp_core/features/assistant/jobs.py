"""Asistanın worker işleri (`@job_handler`; worker `discover()` ile yükler; AI-ASISTAN-PLANI §10.1).

- `assistant.answer`  bir asistan mesajını cevaplar: `flow.cevapla` (sözlük → şablon → kapalı kip →
                      canlı geçit). Asistan şeridinde (`serit="asistan"`) birkaç iş parçacığıyla
                      koşar; tek deneme (`max_deneme=1`; yeniden denemek aynı soruyu ikinci kez
                      ücretlendirir), `zaman_asimi_s=120` yalnız emniyettir (süre geçitte, 75 sn).
                      Yük her zaman `{mesaj_id, kullanici_id, tetik}` (API POST ve otomatik
                      yükseltme). Geçit `gateway_factory` ile enjekte edilir; iş `None` verir
                      (akış gerçek fabrikayı kurar), testler ve eval sahte sağlayıcı verir.

`flow.cevapla` kendi hatalarını mesaja (`error` + `hata_kodu`) yazar; buraya yine de bir istisna
ulaşırsa mesaj `error` yapılır (`butce_asildi` / `model_hatasi`), iş kalıcı hatayla biter ve
kayda yalnız istisna sınıfının adı yazılır (`str(exc)` soru/araç metni taşıyabilir). Şerit çökmez.

`on_worker_start`: asistan şeridi açıksa (`TP_WORKER_ASISTAN_SERIT`) `asistan_durum` ilk kez
yazılır; sonrasını worker'ın kalp atışı zamanlayıcısı sürdürür.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Final

from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker

from tp_core.db import get_engine
from tp_core.features.assistant import durum, flow, temizlik
from tp_core.features.assistant.budget import ASISTAN_IS_TURU
from tp_core.gateway.errors import BudgetExceeded
from tp_core.workflow.jobs import ASISTAN_SERIT, JobContext, PermanentJobError, job_handler

log = logging.getLogger("tp_core.worker")

# API'nin satıra yazdığı politika ile aynı (`api.IS_ZAMAN_ASIMI_S`); süre sınırı geçitte (75 sn).
IS_ZAMAN_ASIMI_S: Final = 120


def _mesaj_id(yuk: Any) -> uuid.UUID:
    ham = yuk.get("mesaj_id") if isinstance(yuk, dict) else None
    try:
        return uuid.UUID(str(ham))
    except (TypeError, ValueError):
        raise PermanentJobError("assistant.answer: yükte geçerli mesaj_id yok") from None


def oturum_fabrikasi() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


@job_handler(ASISTAN_IS_TURU, max_deneme=1, zaman_asimi_s=IS_ZAMAN_ASIMI_S, serit=ASISTAN_SERIT)
def answer(ctx: JobContext) -> dict[str, Any]:
    mesaj_id = _mesaj_id(ctx.yuk)
    try:
        flow.cevapla(oturum_fabrikasi(), mesaj_id, gateway_factory=None)
    except PermanentJobError:
        _hata_isaretle(mesaj_id, durum.HATA_MODEL)
        raise
    except Exception as exc:
        kod = durum.HATA_BUTCE if isinstance(exc, BudgetExceeded) else durum.HATA_MODEL
        sinif = type(exc).__name__
        log.warning("assistant.answer %s: %s (%s)", mesaj_id, kod, sinif)
        _hata_isaretle(mesaj_id, kod)
        raise PermanentJobError(f"asistan cevabı başarısız: {kod} ({sinif})") from None
    return {"mesaj_id": str(mesaj_id)}


def _hata_isaretle(mesaj_id: uuid.UUID, kod: str) -> None:
    try:
        with get_engine().begin() as conn:
            durum.hata_yaz(conn, mesaj_id, kod)
    except Exception as exc:  # işaretleme başarısızsa uzlaştırma kapatır
        log.warning(
            "asistan mesajı %s hata olarak işaretlenemedi (%s)", mesaj_id, type(exc).__name__
        )


def on_worker_start(conn: Connection) -> None:
    """Asistan şeridi açıksa ilk durum satırı/kalp atışı (sonrası worker zamanlayıcısında)."""
    temizlik.planla(conn)  # saklama temizliği (§8): şeritten bağımsız, genel şeritte koşar
    if durum.asistan_serit_acik():
        durum.durum_yaz(conn)
