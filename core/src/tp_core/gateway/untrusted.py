"""Güvenilmeyen içerik sarmalayıcısı (TEKNIK-TASARIM §5, constitution güvenlik kısıtları).

Jira/Confluence metni, kod, veri sorgu sonuçları, sayfa snapshot'ları ve CI log'ları prompt'a
yalnızca `<untrusted>` bloğu içinde girer. Sistem prompt'undaki ortak kural (rules/prompts/
_guardrails.md) bu bloklardaki talimatların uygulanmamasını söyler.

İçerik bloğu kapatıp dışarı "kaçamaz"; iki katmanlı savunma:

1. **Sınır kimliği:** her blok `id="<sınır>"` taşır ve yalnızca `</untrusted id="<sınır>">` ile
   kapanır. Sınır, (kind, source, içerik) özetinden türetilir: deterministiktir (replay anahtarı
   aynı girdide aynı kalır) ama içerik kendi özetini içeremeyeceği için önceden tahmin edilemez.
2. **Etiket nötrleştirme:** içerikteki `<untrusted` / `</untrusted` benzeri her dizinin `<`
   karakteri `&lt;` olur. Eşleme, biçim karakterleri (Unicode Cf: sıfır genişlikli boşluk, ZWJ,
   yön işaretleri, yumuşak tire …) atılmış ve NFKC ile katlanmış (tam genişlikli `＜/untrusted＞`,
   küçük `﹤`, matematik harfleri …) bir gölge metin üzerinde yapılır; değişiklik özgün metne
   uygulanır. Böylece görünmez veya benzer karakterlerle yazılmış kapanış etiketleri de yakalanır.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Literal

UntrustedKind = Literal["jira", "confluence", "code", "data", "snapshot", "ci_log", "text"]

_TAG_RE = re.compile(r"<\s*/?\s*untrusted", re.IGNORECASE)
_ATTR_RE = re.compile(r"[^A-Za-z0-9_.:/#@ -]")
# NFKC'nin `<`'ye katlamadığı ama modelin açılı ayraç olarak okuyabileceği benzerler.
_ANGLE_LOOKALIKES = frozenset("‹〈〈⟨❬❮⧼˂ᐸ")
BOUNDARY_LEN = 16


def _fold(ch: str) -> str:
    """Tek karakterin eşleme için gölge karşılığı ('' = yok sayılır)."""
    if unicodedata.category(ch) == "Cf":
        return ""
    if ch in _ANGLE_LOOKALIKES:
        return "<"
    return unicodedata.normalize("NFKC", ch)


def _escape_content(content: str) -> str:
    if content.isascii():
        return _TAG_RE.sub(lambda m: "&lt;" + m.group(0)[1:], content)
    shadow: list[str] = []
    origin: list[int] = []  # gölge karakter → özgün indeks
    for i, ch in enumerate(content):
        for folded in _fold(ch):
            shadow.append(folded)
            origin.append(i)
    starts = {origin[m.start()] for m in _TAG_RE.finditer("".join(shadow))}
    if not starts:
        return content
    return "".join("&lt;" if i in starts else ch for i, ch in enumerate(content))


def _escape_attr(value: str) -> str:
    return _ATTR_RE.sub("_", value)[:200]


def block_boundary(content: str, *, source: str, kind: str) -> str:
    """Bloğun sınır kimliği: içerikten türetilir; içerik onu önceden bilemez."""
    digest = hashlib.sha256(f"{kind}\x00{source}\x00{content}".encode()).hexdigest()
    return digest[:BOUNDARY_LEN]


def wrap_untrusted(content: str, *, source: str, kind: UntrustedKind = "text") -> str:
    """İçeriği etiketli, sınır kimlikli veri bloğuna sarar.

    >>> out = wrap_untrusted("AC1: ...", source="jira:TPD-1", kind="jira")
    >>> out.startswith('<untrusted kind="jira" source="jira:TPD-1" id="')
    True
    >>> out.endswith('">')
    True
    """
    safe_source = _escape_attr(source)
    body = _escape_content(content)
    boundary = block_boundary(body, source=safe_source, kind=kind)
    return (
        f'<untrusted kind="{kind}" source="{safe_source}" id="{boundary}">\n'
        f"{body}\n"
        f'</untrusted id="{boundary}">'
    )
