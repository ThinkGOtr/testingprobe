"""Merkezî ORM proje filtresi (TP-COK-PROJE-PLANI §2.3).

`kur(Session)` üç olay bağlar (idempotent; `tp_core.models` içe aktarılırken bir kez çağrılır ve
`Session` sınıfına bağlandığından `Session(engine)` ile kurulan her oturumu kapsar):

- `do_orm_execute`: ORM SELECT/UPDATE/DELETE'e `ProjeKapsamli` için
  `project_id == <bağlamdaki pid>` ölçütü (`with_loader_criteria`, takma adlar dahil). Bağlam
  yokken kapsamlı varlığa dokunan sorgu `ProjeBaglamiYok`. Kaçış:
  `.execution_options(tum_projeler=True)` (yalnız worker/kurulum kodu; statik testte izinli liste).
- `load` (mixin, `propagate=True`): yüklenen satırın projesi bağlamdakinden farklıysa `ProjeIhlali`
  (sızıntı sessiz yanlış veri yerine 500 olur); bağlam yoksa `ProjeBaglamiYok`.
- `before_flush`: yeni kapsamlı nesnede `project_id` boşsa bağlamdan doldurur; doluysa ve bağlamla
  ya da ilişkili (many-to-one) ebeveynin projesiyle uyuşmazsa `ProjeIhlali`. Var olan satırın
  projesi değiştirilemez.

Ham SQL (`text(...)`) ve Core ifadeleri (`select(Model.__table__)`) bu filtreye girmez: açık
`project_id = :pid` + `pid_param()` gerekir (statik/dinamik testler denetler).
"""

from __future__ import annotations

from typing import Any, Final

from sqlalchemy import event, inspect
from sqlalchemy.orm import (
    ORMExecuteState,
    QueryContext,
    Session,
    UOWTransaction,
    sessionmaker,
    with_loader_criteria,
)
from sqlalchemy.orm.base import NO_VALUE
from sqlalchemy.orm.interfaces import MANYTOONE

from tp_core.proje.baglam import ProjeBaglamiYok, ProjeIhlali, mevcut_pid, varsa

TUM_PROJELER: Final = "tum_projeler"


def _mixin() -> type:
    from tp_core.models.base import ProjeKapsamli

    return ProjeKapsamli


def _kapsamli_nesne(obj: Any) -> bool:
    return isinstance(obj, _mixin())


def _orm_execute(state: ORMExecuteState) -> None:
    if not (state.is_select or state.is_update or state.is_delete):
        return
    if state.is_column_load or state.execution_options.get(TUM_PROJELER):
        return
    mixin = _mixin()
    b = varsa()
    if b is None:
        if any(issubclass(m.class_, mixin) for m in state.all_mappers):
            raise ProjeBaglamiYok(
                "proje kapsamlı sorgu bağlamsız çalıştırıldı (proje_icinde ya da "
                "execution_options(tum_projeler=True))"
            )
        return
    pid = b.pid
    state.statement = state.statement.options(
        with_loader_criteria(mixin, lambda c: c.project_id == pid, include_aliases=True)
    )


def _kacis(context: QueryContext) -> bool:
    """`tum_projeler` ifadede (`stmt.execution_options`) ya da `session.execute(...,
    execution_options=...)` çağrısında verilmiş olabilir."""
    ifade = getattr(context.query, "_execution_options", None) or {}
    return bool(context.execution_options.get(TUM_PROJELER) or ifade.get(TUM_PROJELER))


def _yuklendi(target: Any, context: QueryContext) -> None:
    if _kacis(context):
        return
    b = varsa()
    if b is None:
        raise ProjeBaglamiYok(f"{type(target).__name__} bağlamsız yüklendi (proje_icinde gerekli)")
    if target.project_id != b.pid:
        raise ProjeIhlali(
            f"{type(target).__name__} başka projeden yüklendi: "
            f"{target.project_id!r} ≠ bağlam {b.pid!r}"
        )


def _ebeveyn_denetimi(obj: Any) -> None:
    durum = inspect(obj)
    for rel in durum.mapper.relationships:
        if rel.direction is not MANYTOONE:
            continue
        ebeveyn = durum.attrs[rel.key].loaded_value
        if ebeveyn is NO_VALUE or ebeveyn is None or not _kapsamli_nesne(ebeveyn):
            continue
        if ebeveyn.project_id is not None and ebeveyn.project_id != obj.project_id:
            raise ProjeIhlali(
                f"{type(obj).__name__}.{rel.key}: çocuk {obj.project_id!r} ≠ "
                f"ebeveyn {ebeveyn.project_id!r}"
            )


def _flush_oncesi(session: Session, _ctx: UOWTransaction, _instances: Any) -> None:
    for obj in session.new:
        if not _kapsamli_nesne(obj):
            continue
        if obj.project_id is None:
            obj.project_id = mevcut_pid()
        else:
            b = varsa()
            if b is not None and obj.project_id != b.pid:
                raise ProjeIhlali(
                    f"{type(obj).__name__} yanlış projeye yazılıyor: "
                    f"{obj.project_id!r} ≠ bağlam {b.pid!r}"
                )
        _ebeveyn_denetimi(obj)
    for obj in session.dirty:
        if not _kapsamli_nesne(obj):
            continue
        gecmis = inspect(obj).attrs.project_id.history
        if gecmis.deleted and gecmis.added and gecmis.deleted[0] is not None:
            raise ProjeIhlali(f"{type(obj).__name__}.project_id değiştirilemez")


def kur(session_cls: type[Session] | sessionmaker[Any]) -> None:
    """Olayları bağlar; tekrar çağrı etkisizdir."""
    mixin = _mixin()
    if not event.contains(mixin, "load", _yuklendi):
        event.listen(mixin, "load", _yuklendi, propagate=True)
    if not event.contains(session_cls, "do_orm_execute", _orm_execute):
        event.listen(session_cls, "do_orm_execute", _orm_execute)
    if not event.contains(session_cls, "before_flush", _flush_oncesi):
        event.listen(session_cls, "before_flush", _flush_oncesi)


def kapsamli_tablolar() -> frozenset[str]:
    """`ProjeKapsamli` mixin'li modellerin tablo adları (`tp_core.models` kayıt defterinden)."""
    from tp_core.models import Base

    mixin = _mixin()
    return frozenset(
        m.local_table.name  # type: ignore[attr-defined]
        for m in Base.registry.mappers
        if issubclass(m.class_, mixin)
    )
