"""Postgres LISTEN/NOTIFY olay yolu (core-worker → core-api → portal SSE).

Kanal: `tp_events`. Yük: ``{"event": str, "data": {...}, "ts": ISO-8601, "project_id": str|null}``
(kanonik JSON). `project_id` (TP-COK-PROJE-PLANI §5.1) olayın projesidir: açık değer, yoksa
yayınlayanın bağlamındaki proje, bağlam yoksa `null` (kurulum geneli olay). Dinleyici abonenin
projesine göre süzer (`listener.Broadcaster.subscribe(project_id)`).
NOTIFY yükü 8000 baytla sınırlıdır; aşan veri gönderilmez, yerine yalnızca kimlik alanları ve
``"truncated": true`` gider (istemci ayrıntıyı API'den çeker).

`publish_tx(conn, ...)` çağıranın işlemine katılır: olay yalnızca işlem commit edilirse yayılır
(durum geçişi geri alınırsa olay da gitmez). `PgEventBus.publish` kendi işlemini açar.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, Engine, text

from tp_core.audit.canonical import canonical_json, normalize
from tp_core.proje.baglam import varsa

CHANNEL = "tp_events"
MAX_PAYLOAD = 7900  # Postgres sınırı 8000 bayt
EVENT_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
# Kırpılmış yükte korunan alanlar. `mesaj_id` ve `kullanici_id` asistan olayları içindir: SSE akışı
# `assistant.*` olayını yalnız `kullanici_id`'si oturum kullanıcısı olana teslim eder (fail-closed),
# kırpmada düşerse olay kimseye gitmez.
KIMLIK_ALANLARI = (
    "id",
    "requirement_id",
    "case_id",
    "script_id",
    "run_id",
    "job_id",
    "durum",
    "mesaj_id",
    "kullanici_id",
)


def _olay_projesi(project_id: str | None) -> str | None:
    if project_id is not None:
        return project_id
    b = varsa()
    return b.pid if b is not None else None


def build_payload(event: str, data: Mapping[str, Any], *, project_id: str | None = None) -> str:
    """Olay yükü; `project_id` verilmezse bağlamdaki proje (yoksa `null`). Kırpılmış yükte de
    proje korunur (süzme ona dayanır)."""
    if not EVENT_RE.match(event):
        raise ValueError(f"geçersiz olay adı: {event!r} (ör. 'case.generated')")
    ts = datetime.now(UTC).isoformat(timespec="milliseconds")
    pid = _olay_projesi(project_id)
    yuk = canonical_json(
        {"event": event, "data": normalize(dict(data)), "ts": ts, "project_id": pid}
    )
    if len(yuk.encode("utf-8")) <= MAX_PAYLOAD:
        return yuk
    kisa = {k: data[k] for k in KIMLIK_ALANLARI if k in data}
    kisa["truncated"] = True
    return canonical_json({"event": event, "data": normalize(kisa), "ts": ts, "project_id": pid})


def parse_payload(payload: str) -> dict[str, Any]:
    obj = json.loads(payload)
    if not isinstance(obj, dict) or "event" not in obj:
        raise ValueError("geçersiz olay yükü")
    return obj


def publish_tx(
    conn: Connection, event: str, data: Mapping[str, Any], *, project_id: str | None = None
) -> None:
    conn.execute(
        text("SELECT pg_notify(:c, :p)"),
        {"c": CHANNEL, "p": build_payload(event, data, project_id=project_id)},
    )


class PgEventBus:
    """`ports.EventBus` uygulaması."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def publish(self, event: str, data: Mapping[str, Any]) -> None:
        with self._engine.begin() as conn:
            publish_tx(conn, event, data)
