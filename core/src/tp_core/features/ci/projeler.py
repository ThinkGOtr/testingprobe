"""Açılış kancalarının proje döngüsü (TP-COK-PROJE-PLANI §5.2).

Periyodik işler (gece koşusu, PR senkronu, triage/bug/hata koşusu taramaları) ve takılı kayıt
temizlikleri proje başınadır: kanca bağlamsız çağrılırsa (worker açılışı) her aktif projede
(`tp_proje WHERE aktif`) ayrı bağlam kurulur; bağlam zaten varsa (worker kancayı proje başına
çağırıyorsa) yalnız o projede koşar. Böylece kuyruğa giren iş `project_id`'yi bağlamdan alır ve
işleyici kendi projesinde çalışır (K3).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import Connection

from tp_core.proje import kurulu_projeler, proje_icinde, varsa, varsayilan_pid


def acilis_projeleri(conn: Connection) -> list[str]:
    """Bağlam varsa yalnız o proje; yoksa aktif projeler (kayıt yoksa varsayılan proje)."""
    b = varsa()
    if b is not None:
        return [b.pid]
    return kurulu_projeler(conn) or [varsayilan_pid()]


def her_projede(conn: Connection, fn: Callable[[Connection], None]) -> None:
    """`fn(conn)`'u her açılış projesinin bağlamında sırayla çağırır."""
    if varsa() is not None:
        fn(conn)
        return
    for pid in acilis_projeleri(conn):
        with proje_icinde(pid, kaynak="sistem"):
            fn(conn)


def toolchain_projesi(body: dict[str, Any]) -> dict[str, Any]:
    """Toolchain istek gövdesine `proje` bloğunu ekler (TP-COK-PROJE-PLANI §4.4) ve gövdeyi döner.

    Varsayılan projede (ve bağlamsız çağrıda) blok eklenmez: toolchain süreç ortamı varsayılan
    projeninkidir ve gövde baytları eski toolchain'lerle (`extra="forbid"`) aynı kalır.
    """
    b = varsa()
    if b is not None and b.pid != varsayilan_pid():
        from tp_core.proje import istemciler

        body["proje"] = istemciler.toolchain_proje_blogu()
    return body
