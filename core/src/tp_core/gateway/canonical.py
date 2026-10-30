"""Kanonik JSON, hash ve girdi normalizasyonu.

Replay anahtarları deterministiktir (constitution XI).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


# Zaman damgaları, UUID'ler ve Playwright snapshot ref'leri (ör. [ref=e12]) her koşuda değişir;
# replay anahtarına girmeden önce sabit yer tutuculara indirgenir.
_NORMALIZERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?\b"
        ),
        "<TS>",
    ),
    (
        re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
        "<UUID>",
    ),
    (re.compile(r"\bref=e\d+\b"), "ref=<REF>"),
    (re.compile(r"\b(snapshot|evidence)[-_](?:ref[-_])?[0-9a-f]{6,}\b"), r"\1-<REF>"),
)


def normalize_text(text: str) -> str:
    for pattern, repl in _NORMALIZERS:
        text = pattern.sub(repl, text)
    return text


def normalize(obj: Any) -> Any:
    if isinstance(obj, str):
        return normalize_text(obj)
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [normalize(v) for v in obj]
    return obj


def input_hash(messages: Any) -> str:
    return sha256_hex(canonical_json(normalize(messages)))
