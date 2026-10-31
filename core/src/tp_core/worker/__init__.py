"""core-worker: Postgres kuyruğundan (`job`, FOR UPDATE SKIP LOCKED) iş alır ve kayıtlı
işleyicilere dağıtır. İşleyiciler `@tp_core.workflow.jobs.job_handler` ile kaydolur;
`tp_core.features.<ad>.jobs` modülleri başlangıçta otomatik yüklenir.

Yeniden deneme/geri çekilme, zaman aşımı ve idempotency kuralları `tp_core.workflow.jobs`'tadır.

Açılışta (ilk turda) aynı konteynerin önceki sürecinden kalan `running` işler bırakılır
(`release_orphans`). Bir iş `zaman_asimi_s` içinde bitmezse iş `retry`/`failed` yazılır ve süreç
`ZAMAN_ASIMI_CIKIS_KODU` ile çıkar (asılı iş parçacığı öldürülemez; compose yeniden başlatır).

Canlılık: ana döngü (ve iş beklerken yürütücü) `TP_WORKER_LIVENESS_FILE` dosyasının zamanını
tazeler; `tp_core.worker.healthcheck` dosya `CANLILIK_ESIGI_S`'den eskiyse sağlıksız der.

Veritabanına ulaşılamazken tek satırlık uyarı yazılır ve bekleme üstel artar
(1 → 2 → 4 … ≤ `DB_BEKLEME_UST_S` sn); bağlantı dönünce bir kez bilgi yazılır.
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import psycopg
from sqlalchemy.exc import InterfaceError, OperationalError

from tp_core.db import get_engine
from tp_core.workflow import jobs
from tp_core.workflow.jobs import (
    REGISTRY,
    ClaimedJob,
    HandlerSpec,
    JobContext,
    Sonuc,
    discover,
    process_one,
    reap_stale,
    release_orphans,
)

log = logging.getLogger("tp_core.worker")

GECISLER: dict[str, frozenset[str]] = jobs.JOB_GECISLERI
HANDLERS: Mapping[str, HandlerSpec] = REGISTRY
REAP_ARALIGI_S = 30.0
DB_BEKLEME_UST_S = 30.0
ZAMAN_ASIMI_CIKIS_KODU = 70
CANLILIK_ESIGI_S = 120.0


def canlilik_dosyasi() -> Path:
    return Path(
        os.environ.get("TP_WORKER_LIVENESS_FILE")
        or os.path.join(tempfile.gettempdir(), "tp-worker-canli")
    )


def canli() -> None:
    """Canlılık işaretini tazeler (yazılamazsa sessiz: sağlık kontrolü DB'ye düşer)."""
    with contextlib.suppress(OSError):
        canlilik_dosyasi().write_text(f"{time.time():.3f}\n")


class ZamanAsimiCikisi(RuntimeError):
    """Bir iş süresini aştı; işleyici iş parçacığı asılı — süreç yeniden başlamalı."""


DB_HATALARI: tuple[type[BaseException], ...] = (
    OperationalError,
    InterfaceError,
    psycopg.OperationalError,
    psycopg.InterfaceError,
)

Handler = Callable[[JobContext], Any]

__all__ = ["GECISLER", "HANDLERS", "GecersizGecis", "Sonuc", "calistir", "gecis", "main", "run"]


class GecersizGecis(ValueError):
    pass


def gecis(mevcut: str, hedef: str) -> str:
    if hedef not in GECISLER.get(mevcut, frozenset()):
        raise GecersizGecis(f"{mevcut} -> {hedef}")
    return hedef


def calistir(
    tur: str,
    yuk: Mapping[str, Any] | None,
    handlers: Mapping[str, Handler] | None = None,
    *,
    deneme: int = 1,
) -> Sonuc:
    """Tek bir denemeyi DB'siz yürütür (test ve teşhis için). `handlers` verilirse düz
    çağrılabilirler tek denemelik işleyici sayılır; verilmezse kayıtlı işleyiciler kullanılır."""
    kayit: Mapping[str, HandlerSpec] = (
        REGISTRY
        if handlers is None
        else {t: HandlerSpec(t, fn, max_deneme=1) for t, fn in handlers.items()}
    )
    return jobs.execute(ClaimedJob(uuid.uuid4(), tur, yuk, deneme, None, None), kayit)


_son_reap = 0.0
_sahipsizler_birakildi = False


def tek_tur() -> bool:
    """İlk turda önceki süreçten kalan işleri bırakır; gerekirse zaman aşımına uğramış işleri
    toplar, sonra bir iş işler; iş yoksa False."""
    global _son_reap, _sahipsizler_birakildi
    engine = get_engine()
    if not _sahipsizler_birakildi:
        with engine.begin() as conn:
            n = release_orphans(conn)
        _sahipsizler_birakildi = True
        if n:
            log.warning("önceki worker sürecinden kalan %d iş bırakıldı (retry/failed)", n)
    if time.monotonic() - _son_reap >= REAP_ARALIGI_S:
        with engine.begin() as conn:
            n = reap_stale(conn)
        _son_reap = time.monotonic()
        if n:
            log.warning("%d zaman aşımına uğramış iş yeniden kuyruğa alındı", n)
    sonuc = process_one(engine, canli=canli)
    if sonuc is not None and sonuc.zaman_asimi:
        raise ZamanAsimiCikisi(sonuc.hata or "iş zaman aşımına uğradı")
    return sonuc is not None


def _kisa_hata(exc: BaseException) -> str:
    kok = getattr(exc, "orig", None) or exc
    satirlar = str(kok).strip().splitlines()
    return (satirlar[0] if satirlar else type(kok).__name__)[:200]


def run(dur: threading.Event, aralik: float = 1.0) -> int:
    """Kuyruk döngüsü; çıkış kodu döndürür (0 = durduruldu, `ZAMAN_ASIMI_CIKIS_KODU`)."""
    log.info("worker başladı; işleyiciler: %s", ", ".join(sorted(REGISTRY)))
    db_bekleme: float | None = None  # None = bağlantı sağlıklı
    while not dur.is_set():
        canli()
        try:
            calisti = tek_tur()
        except ZamanAsimiCikisi as exc:
            log.error("worker yeniden başlatılmak üzere çıkıyor: %s", exc)
            return ZAMAN_ASIMI_CIKIS_KODU
        except DB_HATALARI as exc:
            db_bekleme = aralik if db_bekleme is None else min(db_bekleme * 2, DB_BEKLEME_UST_S)
            db_bekleme = max(db_bekleme, aralik)
            log.warning("DB erişilemiyor: %s; %.0f sn sonra tekrar", _kisa_hata(exc), db_bekleme)
            dur.wait(db_bekleme)
            continue
        except Exception:
            log.exception("kuyruk turu başarısız; yeniden denenecek")
            dur.wait(aralik)
            continue
        if db_bekleme is not None:
            log.info("DB bağlantısı yeniden kuruldu")
            db_bekleme = None
        if not calisti:
            dur.wait(aralik)
    log.info("worker durdu")
    return 0


def acilis_kancalari(moduller: list[str]) -> list[str]:
    """Özellik `jobs` modüllerindeki `on_worker_start(conn)` kancalarını bir kez çağırır.

    Ör. kendini yeniden planlayan periyodik işler (PO etiket sorgusu) kuyruk silinse de worker
    açılışında yeniden başlar. Kanca hatası worker'ı düşürmez (loglanır); her kanca kendi
    işleminde koşar.
    """
    import importlib

    calisan: list[str] = []
    for ad in moduller:
        kanca = getattr(importlib.import_module(ad), "on_worker_start", None)
        if not callable(kanca):
            continue
        try:
            with get_engine().begin() as conn:
                kanca(conn)
            calisan.append(ad)
        except Exception:
            log.exception("%s.on_worker_start başarısız", ad)
    return calisan


def main() -> None:
    from tp_core.config import get_settings

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    yuklenen = discover()
    if yuklenen:
        log.info("özellik işleyici modülleri: %s", ", ".join(yuklenen))
    acilis_kancalari(yuklenen)
    dur = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: dur.set())
    kod = run(dur, get_settings().worker_poll_interval_s)
    if kod:
        # Asılı işleyici iş parçacığı normal çıkışı bekletebilir; süreç hemen sonlanır.
        logging.shutdown()
        os._exit(kod)
