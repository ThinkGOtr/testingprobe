"""Periyodik iş ve açılış kancalarının proje döngüsü (TP-COK-PROJE-PLANI §5.2).

Worker açılış kancaları (`on_worker_start`) ve kurulum geneli zamanlayıcılar bağlamsız çağrılır;
kendini yeniden planlayan proje işleri (Jira tetiği, PO sorgusu, asistan temizliği) ise her aktif
proje için ayrı planlanmalıdır. `projelerde(conn, fn)`:

- bağlam varsa (iş içinden yeniden planlama, API, test) `fn` yalnız o projede koşar;
- yoksa `kurulu_projeler(conn)` (`tp_proje WHERE aktif`) her biri için `proje_icinde(pid,
  kaynak="sistem")` içinde koşar. Böylece kancayı projeler üzerinde döndüren çağıran (worker) da
  bağlamsız çağıran da aynı sonucu alır; pasif projeye yeni iş planlanmaz.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Connection

from tp_core.proje import kurulu_projeler, proje_icinde, varsa


def projelerde[R](conn: Connection, fn: Callable[[], R]) -> list[R]:
    """`fn`'i bağlamdaki projede ya da (bağlam yoksa) her aktif projede çağırır; sonuçlar
    proje sırasıyla."""
    if varsa() is not None:
        return [fn()]
    sonuclar: list[R] = []
    for pid in kurulu_projeler(conn):
        with proje_icinde(pid, kaynak="sistem"):
            sonuclar.append(fn())
    return sonuclar
