"""Proje bağlamı (TP-COK-PROJE-PLANI §2.1): `contextvars` tabanlı, istek/iş/CLI başına.

Bağlamı API'de istek bağımlılığı (`oturum`, `token`), worker'da iş satırı (`is`), periyodik
planlayıcıda (`sistem`) ve CLI'da (`cli`) açık `proje_icinde(pid)` kurar. Bağlamsız proje-kapsamlı
erişim **hata** verir (`ProjeBaglamiYok`); sessizce varsayılan projeye düşülmez.

`threading.Thread` bağlamı miras almaz: hedefi `baglamla(fn)` ile sarın ya da iş parçacığında
`proje_icinde` kurun.
"""

from __future__ import annotations

import contextvars
import functools
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final, Literal

from sqlalchemy import Connection, text

KURULUM: Final = "_kurulum"
VARSAYILAN: Final = "varsayilan"
PROJE_ENV: Final = "TP_HOME_PROJECT"
PID_UZUNLUK: Final = 64

Kaynak = Literal["oturum", "token", "is", "sistem", "cli", "test"]


@dataclass(frozen=True, slots=True)
class ProjeBaglami:
    pid: str
    kaynak: Kaynak


class ProjeBaglamiYok(RuntimeError):
    """Proje kapsamlı erişim bağlamsız yapıldı."""


class ProjeIhlali(RuntimeError):
    """Yanlış projeden satır yüklendi ya da yanlış `project_id` ile yazılmak istendi."""


_BAGLAM: contextvars.ContextVar[ProjeBaglami | None] = contextvars.ContextVar(
    "tp_proje_baglami", default=None
)


def _dogrula(pid: str) -> str:
    if not isinstance(pid, str) or not pid.strip() or len(pid) > PID_UZUNLUK:
        raise ValueError(f"geçersiz proje kimliği: {pid!r}")
    if pid != pid.strip():
        raise ValueError(f"proje kimliğinde baş/son boşluk: {pid!r}")
    return pid


def varsa() -> ProjeBaglami | None:
    return _BAGLAM.get()


def mevcut() -> ProjeBaglami:
    b = _BAGLAM.get()
    if b is None:
        raise ProjeBaglamiYok(
            "proje bağlamı yok: proje kapsamlı erişim `proje_icinde(pid)` içinde yapılmalı"
        )
    return b


def mevcut_pid() -> str:
    return mevcut().pid


def pid_param(**ek: Any) -> dict[str, Any]:
    """Ham SQL parametreleri: `{"pid": mevcut_pid(), **ek}` (`... WHERE project_id = :pid`)."""
    return {"pid": mevcut_pid(), **ek}


@contextmanager
def proje_icinde(pid: str, *, kaynak: Kaynak = "sistem") -> Iterator[ProjeBaglami]:
    """`pid` projesinin bağlamını kurar; çıkışta önceki bağlam (iç içe dahil) geri gelir."""
    b = ProjeBaglami(_dogrula(pid), kaynak)
    jeton = _BAGLAM.set(b)
    try:
        yield b
    finally:
        _BAGLAM.reset(jeton)


def baglamla[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """Çağrı anındaki bağlamı yakalayıp `fn`'i onun kopyasında koşturur (thread hedefi için).

    Her çağrı kendi kopyasını kullanır; aynı sarmalayıcı birden çok iş parçacığında güvenle
    kullanılabilir.
    """
    ctx = contextvars.copy_context()

    @functools.wraps(fn)
    def _sarili(*args: P.args, **kwargs: P.kwargs) -> R:
        return ctx.copy().run(fn, *args, **kwargs)

    return _sarili


def varsayilan_pid() -> str:
    """`TP_HOME_PROJECT` (Home kipinde bugünkü proje), yoksa `"varsayilan"` (yerel/on-prem)."""
    deger = (os.environ.get(PROJE_ENV) or "").strip()
    return _dogrula(deger) if deger else VARSAYILAN


def kurulu_projeler(conn: Connection) -> list[str]:
    """Arka plan işi planlanacak projeler: `tp_proje WHERE aktif ORDER BY pid`."""
    return list(conn.execute(text("SELECT pid FROM tp_proje WHERE aktif ORDER BY pid")).scalars())


def proje_kaydet(
    conn: Connection,
    pid: str,
    *,
    kod: str | None,
    ad: str | None,
    kaynak: Literal["env", "kesif"],
) -> bool:
    """Projeyi `tp_proje`'ye ekler; zaten varsa yalnız boş olmayan `kod`/`ad`'ı tazeler.

    `aktif` ve `kaynak` mevcut satırda değişmez (pasifleştirilmiş proje kendiliğinden açılmaz).
    Yeni satır eklendiyse True.
    """
    if kaynak not in ("env", "kesif"):
        raise ValueError(f"geçersiz kaynak: {kaynak!r}")
    return bool(
        conn.execute(
            text(
                "INSERT INTO tp_proje (pid, kod, ad, kaynak) VALUES (:pid, :kod, :ad, :kaynak) "
                "ON CONFLICT (pid) DO UPDATE SET "
                "kod = COALESCE(EXCLUDED.kod, tp_proje.kod), "
                "ad = COALESCE(EXCLUDED.ad, tp_proje.ad), "
                "guncelleme = CASE WHEN tp_proje.kod IS DISTINCT FROM "
                "COALESCE(EXCLUDED.kod, tp_proje.kod) OR tp_proje.ad IS DISTINCT FROM "
                "COALESCE(EXCLUDED.ad, tp_proje.ad) THEN now() ELSE tp_proje.guncelleme END "
                "RETURNING (xmax = 0) AS yeni"
            ),
            {"pid": _dogrula(pid), "kod": kod, "ad": ad, "kaynak": kaynak},
        ).scalar_one()
    )
