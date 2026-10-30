"""ORM yazma koruması: durum makinesi olan tablolarda `durum` ve `onaylanan_hash` yalnızca
`tp_core.workflow.service.transition()` içinden değişebilir.

Yeni satır başlangıç durumuyla (ya da `durum` boş bırakılarak) ve `onaylanan_hash` boş eklenir.
Koruma ORM flush'ında çalışır; ham SQL `UPDATE` bu korumayı atlar ve kod incelemesinde reddedilir.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, UOWTransaction

from tp_core.workflow.states import MACHINES

KORUNAN_ALANLAR = ("durum", "onaylanan_hash")

_izinli: ContextVar[bool] = ContextVar("tp_state_write_allowed", default=False)


class StateWriteForbidden(RuntimeError):
    """`durum`/`onaylanan_hash` transition() dışından değiştirilmeye çalışıldı."""


@contextmanager
def allow_state_write() -> Iterator[None]:
    token = _izinli.set(True)
    try:
        yield
    finally:
        _izinli.reset(token)


def _tablo(obj: Any) -> str | None:
    return getattr(type(obj), "__tablename__", None)


def _denetle(session: Session, _flush_context: UOWTransaction, _instances: Any) -> None:
    if _izinli.get():
        return
    for obj in session.new:
        tablo = _tablo(obj)
        machine = MACHINES.get(tablo or "")
        if machine is None:
            continue
        durum = getattr(obj, "durum", None)
        if durum is not None and durum != machine.initial:
            raise StateWriteForbidden(
                f"{tablo}: yeni satır yalnızca '{machine.initial}' durumuyla eklenebilir "
                f"(verilen: {durum!r})"
            )
        if getattr(obj, "onaylanan_hash", None) is not None:
            raise StateWriteForbidden(f"{tablo}: onaylanan_hash yalnızca onay geçişiyle yazılır")
    for obj in session.dirty:
        tablo = _tablo(obj)
        if tablo not in MACHINES:
            continue
        durum_bilgisi = inspect(obj)
        for alan in KORUNAN_ALANLAR:
            if alan in durum_bilgisi.attrs and durum_bilgisi.attrs[alan].history.has_changes():
                raise StateWriteForbidden(
                    f"{tablo}.{alan} yalnızca tp_core.workflow.transition() ile değişir"
                )


event.listen(Session, "before_flush", _denetle)
