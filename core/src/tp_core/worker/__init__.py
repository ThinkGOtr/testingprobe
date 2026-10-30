"""Postgres kuyruğu worker iskeleti: `job` tablosundan FOR UPDATE SKIP LOCKED ile iş alır."""

import logging
import signal
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from tp_core.db import get_engine

log = logging.getLogger("tp_core.worker")

GECISLER: dict[str, frozenset[str]] = {
    "queued": frozenset({"running"}),
    "running": frozenset({"done", "failed"}),
    "done": frozenset(),
    "failed": frozenset(),
}

Handler = Callable[[Mapping[str, Any] | None], None]


def noop(_yuk: Mapping[str, Any] | None) -> None:
    return None


HANDLERS: dict[str, Handler] = {"noop": noop}


class GecersizGecis(ValueError):
    pass


def gecis(mevcut: str, hedef: str) -> str:
    if hedef not in GECISLER.get(mevcut, frozenset()):
        raise GecersizGecis(f"{mevcut} -> {hedef}")
    return hedef


@dataclass(frozen=True)
class Sonuc:
    durum: str
    deneme_artisi: int
    hata: str | None = None


def calistir(
    tur: str, yuk: Mapping[str, Any] | None, handlers: Mapping[str, Handler] = HANDLERS
) -> Sonuc:
    """running durumundaki işi yürütür; sonuç durumunu döndürür (DB'ye dokunmaz)."""
    handler = handlers.get(tur)
    try:
        if handler is None:
            raise LookupError(f"bilinmeyen iş türü: {tur}")
        handler(yuk)
    except Exception as exc:
        return Sonuc(gecis("running", "failed"), 1, str(exc))
    return Sonuc(gecis("running", "done"), 0)


def _sahiplen(conn: Connection) -> tuple[uuid.UUID, str, Any] | None:
    row = conn.execute(
        text(
            "SELECT id, tur, yuk FROM job WHERE durum = 'queued' "
            "ORDER BY olusturma LIMIT 1 FOR UPDATE SKIP LOCKED"
        )
    ).first()
    if row is None:
        return None
    conn.execute(
        text("UPDATE job SET durum = :d, guncelleme = now() WHERE id = :id"),
        {"d": gecis("queued", "running"), "id": row.id},
    )
    return row.id, row.tur, row.yuk


def tek_tur() -> bool:
    """Bir iş işler; iş yoksa False."""
    engine = get_engine()
    with engine.begin() as conn:
        is_ = _sahiplen(conn)
    if is_ is None:
        return False
    job_id, tur, yuk = is_
    sonuc = calistir(tur, yuk)
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE job SET durum = :d, deneme = deneme + :n, guncelleme = now() "
                "WHERE id = :id AND durum = 'running'"
            ),
            {"d": sonuc.durum, "n": sonuc.deneme_artisi, "id": job_id},
        )
    if sonuc.hata:
        log.warning("iş %s (%s) başarısız: %s", job_id, tur, sonuc.hata)
    else:
        log.info("iş %s (%s) tamamlandı", job_id, tur)
    return True


def run(dur: threading.Event, aralik: float = 1.0) -> None:
    log.info("worker başladı")
    while not dur.is_set():
        try:
            if tek_tur():
                continue
        except Exception:
            log.exception("kuyruk turu başarısız; yeniden denenecek")
        dur.wait(aralik)
    log.info("worker durdu")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    dur = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: dur.set())
    run(dur)
