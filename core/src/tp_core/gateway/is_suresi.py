"""İşin kalan süresi (bağlam değişkeni): geçidin isteğe bağlı yeniden istemeleri iş zaman aşımını
aşmasın.

İş kuyruğu (`workflow.jobs.execute_with_timeout`) işleyiciyi `is_suresi(zaman_asimi_s)` içinde
koşar. Geçit (`Gateway.call`) kural/şema yeniden istemesinden önce `kalan_sure()`'ye bakar: kalan
süre bir çağrının en kötü süresine (timeout × (1 + zaman aşımı yeniden denemesi)) ve paya
yetmiyorsa yeniden istemez, eldeki şemaya uyan çıktıyı uyarıyla döndürür. Böylece iş zaman aşımına
düşüp worker sürecini çıkartmaz (inceleme tur 2, güvenlik #1 / test mimarı #3).

İş dışı çağrılarda (eval, betikler) süre tanımsızdır (None): davranış değişmez.
Ağır bağımlılığı yoktur; `workflow.jobs` içe aktarır.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_BITIS: ContextVar[float | None] = ContextVar("tp_is_bitisi", default=None)


@contextmanager
def is_suresi(saniye: float) -> Iterator[None]:
    """Bu blok içindeki geçit çağrıları için iş bitiş anı (`time.monotonic()` + saniye)."""
    token = _BITIS.set(time.monotonic() + float(saniye))
    try:
        yield
    finally:
        _BITIS.reset(token)


def kalan_sure() -> float | None:
    """İşin kalan süresi (sn); iş dışında None."""
    bitis = _BITIS.get()
    if bitis is None:
        return None
    return bitis - time.monotonic()
