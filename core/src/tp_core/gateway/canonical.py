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


# Her koşuda değişen değerler replay anahtarına girmeden önce sabit yer tutuculara indirgenir
# (yalnızca anahtar hesabı içindir; modele giden metin değişmez):
# - `<untrusted … id="…">` sınır kimliği: içerikten türetilir, içerikte zaman damgası/UUID varsa
#   koşudan koşuya değişir (içeriğin kendisi aşağıdaki kurallarla zaten normalize edilir);
# - ISO zaman damgaları (Jira `2026-10-01T09:00:00.000+0000` dahil), UUID'ler;
# - git sha'ları (40 hex), sha256 özetleri (64 hex) ve kısa sha'lar (7–12 hex, en az bir harf ve
#   bir rakam: forge her `make reset`'te yeni commit kimliği üretir);
# - Playwright snapshot ref'leri (ör. [ref=e12]).
# Sıra önemlidir: sınır kimliği ve uzun hex'ler kısa sha kuralından önce.
_NORMALIZERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r'(<\s*/?\s*untrusted\b[^>]*?\bid=")[0-9a-f]{8,64}(")'),
        r"\1<B>\2",
    ),
    (re.compile(r"\b[0-9a-f]{64}\b"), "<SHA>"),
    (re.compile(r"\b[0-9a-f]{40}\b"), "<SHA>"),
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
    (re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,12}\b"), "<SHA>"),
    (re.compile(r"\bref=e\d+\b"), "ref=<REF>"),
    (re.compile(r"\b(snapshot|evidence)[-_](?:ref[-_])?[0-9a-f]{6,}\b"), r"\1-<REF>"),
)


def normalize_text(text: str) -> str:
    """Tek metnin anahtar normu.

    >>> normalize_text('istek 2026-10-31T10:00:00Z, sha 1a2b3c4d5e, [ref=e12]')
    'istek <TS>, sha <SHA>, [ref=<REF>]'
    """
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
