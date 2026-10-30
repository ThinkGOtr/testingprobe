"""Kanonik JSON ve içerik hash'i: denetim zinciri ve onay kapıları aynı tanımı kullanır.

Kanonik biçim: anahtarlar sıralı, ayırıcılar boşluksuz (``,`` ``:``), UTF-8 (ASCII kaçışı yok),
NaN/Infinity yasak. UUID → metin, datetime → UTC ISO-8601 (mikrosaniye), Decimal → metin.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

GENESIS_HASH = "0" * 64


def normalize(value: Any) -> Any:
    """JSON'a dönüşebilir sade Python değerine çevirir (dict/list/str/int/float/bool/None)."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("kanonik JSON NaN/Infinity içeremez")
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return iso_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise TypeError(f"JSON anahtarı metin olmalı: {k!r}")
            out[k] = normalize(v)
        return out
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [normalize(v) for v in value]
    raise TypeError(f"kanonik JSON'a çevrilemeyen tür: {type(value).__name__}")


def iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("saat dilimi olmayan datetime kanonikleştirilemez")
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def canonical_json(value: Any) -> str:
    return json.dumps(
        normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(value: Any) -> str:
    """Onay kapılarında kullanılan içerik hash'i: sha256(kanonik JSON)."""
    return sha256_hex(canonical_json(value))


def chain_hash(prev_hash: str, row: Mapping[str, Any]) -> str:
    """Denetim zinciri: sha256(prev_hash + kanonik JSON(satır))."""
    return sha256_hex(prev_hash + canonical_json(row))
