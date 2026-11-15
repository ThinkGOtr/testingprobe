"""core-api tarafı: tek bir LISTEN bağlantısı, olayları SSE abonelerine dağıtır.

Bağlantı koparsa üstel geri çekilmeyle (≤ 10 sn) yeniden bağlanır. Her abone sınırlı bir kuyruğa
sahiptir; yavaş abonede en eski olay düşürülür (diğer aboneler etkilenmez).

Proje süzgeci (TP-COK-PROJE-PLANI §5.1): `subscribe(project_id)` ile açılan abone yalnız o
projenin olaylarını ve kurulum geneli (`project_id` null) olayları alır; başka projenin olayı
kuyruğuna hiç girmez. `subscribe()` (proje yok) tüm olayları alır — yalnız proje bağlamı olmayan
iç tüketiciler içindir; SSE akışı oturumun projesini vermelidir.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import psycopg
from sqlalchemy.engine import make_url

from tp_core.events.bus import CHANNEL, parse_payload

log = logging.getLogger("tp_core.events")


def libpq_dsn(sqlalchemy_url: str) -> str:
    return (
        make_url(sqlalchemy_url).set(drivername="postgresql").render_as_string(hide_password=False)
    )


class Broadcaster:
    def __init__(self, dsn: str, channel: str = CHANNEL, queue_size: int = 100) -> None:
        self._dsn = dsn
        self._channel = channel
        self._queue_size = queue_size
        # abone kuyruğu → süzgeç projesi (None = tüm olaylar)
        self._subs: dict[asyncio.Queue[dict[str, Any]], str | None] = {}
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    async def ensure_started(self, timeout: float = 5.0) -> None:
        if self._task is None or self._task.done():
            self._ready.clear()
            self._task = asyncio.create_task(self._run(), name="tp-events-listener")
        await asyncio.wait_for(self._ready.wait(), timeout)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        self._ready.clear()

    def subscribe(self, project_id: str | None = None) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self._queue_size)
        self._subs[q] = project_id
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs.pop(q, None)

    def fanout(self, payload: str) -> None:
        try:
            olay = parse_payload(payload)
        except ValueError:
            log.warning("geçersiz olay yükü atlandı")
            return
        olay_projesi = olay.get("project_id")
        for q, proje in list(self._subs.items()):
            if proje is not None and olay_projesi is not None and olay_projesi != proje:
                continue
            if q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait(olay)

    async def _run(self) -> None:
        bekleme = 0.5
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    self._dsn, autocommit=True
                ) as conn:
                    await conn.execute(f'LISTEN "{self._channel}"')
                    self._ready.set()
                    bekleme = 0.5
                    async for n in conn.notifies():
                        self.fanout(n.payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._ready.clear()
                log.warning("olay dinleyicisi koptu (%s); %.1f sn sonra yeniden", exc, bekleme)
                await asyncio.sleep(bekleme)
                bekleme = min(bekleme * 2, 10.0)
