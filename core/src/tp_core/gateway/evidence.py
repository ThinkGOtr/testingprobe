"""Veri kanıtı özeti (TEKNIK-TASARIM §8.2b adım 4; constitution XI).

Tutarlılık ajanının veri kanıtı `{kind: "data", query, result_digest}` biçimindedir. Bulgu
gösterilmeden önce doğrulayıcı (requirements şeridi) sorguyu salt okuma rolüyle YENİDEN çalıştırır
ve `result_digest(rows)` sonucunu modelin yazdığı özetle karşılaştırır. Golden kayıtlar, ajanın
`db_query` aracı ve doğrulayıcı aynı fonksiyonu kullandığı için özet tek yerde tanımlıdır.

Kanonik biçim (insan ve model tarafından okunabilir, deterministik):

- Hücre: `None` → `NULL`; `bool` → `true`/`false`; `Decimal` → ölçek korunarak sabit noktalı
  (`Decimal("750.00")` → `750.00`, üstel gösterim yok); `float` → `repr`; tarih/saat → ISO 8601;
  `bytes` → onaltılık; diğerleri `str`. Hücre içindeki `\\`, `=` ve `;` ters bölüyle kaçırılır.
- Satır: hücreler SELECT sırasıyla `=` ile birleşir (`anahtar=deger`).
- Sonuç: satırlar sıralanır (sorguda ORDER BY olmasa da aynı özet) ve `; ` ile birleşir.
  Boş sonuç `(sonuç yok)`.
- Büyük sonuç (`MAX_DIGEST_ROWS` satırdan veya `MAX_DIGEST_CHARS` karakterden fazla):
  `sha256:<ilk 16 hex> (<n> satır)`. Model bunu hesaplayamaz; prompt bu yüzden kanıt sorgusunun
  küçük olmasını ister (tek satır/az kolon). Doğrulayıcı yine eşitlikle karşılaştırır.

Örnek: `SELECT anahtar, deger FROM ayar WHERE anahtar = 'min_siparis_tutari'` →
`min_siparis_tutari=750.00`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

MAX_DIGEST_ROWS = 10
MAX_DIGEST_CHARS = 200
EMPTY_DIGEST = "(sonuç yok)"
ROW_SEP = "; "
CELL_SEP = "="


def canonical_cell(value: Any) -> str:
    """Tek hücrenin kanonik metni (kaçırma uygulanmamış)."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).hex()
    return str(value)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(CELL_SEP, "\\=").replace(";", "\\;")


def _row_cells(row: Any) -> list[str]:
    if isinstance(row, Mapping):
        values: Iterable[Any] = row.values()
    elif hasattr(row, "_mapping"):  # sqlalchemy Row
        values = row._mapping.values()
    elif isinstance(row, Sequence) and not isinstance(row, str | bytes):
        values = row
    else:
        values = [row]
    return [canonical_cell(v) for v in values]


def result_digest(rows: Iterable[Any]) -> str:
    """Sorgu sonucunun kanonik özeti (yukarıdaki kural). Satır: mapping, sıra veya sqlalchemy Row.

    >>> result_digest([{"anahtar": "min_siparis_tutari", "deger": "750.00"}])
    'min_siparis_tutari=750.00'
    >>> result_digest([("P-002", Decimal("15.00")), ("P-001", Decimal("25.00"))])
    'P-001=25.00; P-002=15.00'
    >>> result_digest([])
    '(sonuç yok)'
    """
    cells = [_row_cells(r) for r in rows]
    if not cells:
        return EMPTY_DIGEST
    rendered = sorted(CELL_SEP.join(_escape(c) for c in row) for row in cells)
    text = ROW_SEP.join(rendered)
    if len(rendered) <= MAX_DIGEST_ROWS and len(text) <= MAX_DIGEST_CHARS:
        return text
    canon = json.dumps(sorted(cells), ensure_ascii=False, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canon.encode()).hexdigest()[:16]} ({len(cells)} satır)"


def digest_matches(claimed: str, rows: Iterable[Any]) -> bool:
    """Modelin özeti, yeniden çalıştırılan sorgunun özetine eşit mi (baş/son boşluk hariç)."""
    return claimed.strip() == result_digest(rows)
