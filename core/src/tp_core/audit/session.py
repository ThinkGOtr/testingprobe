"""ORM oturumu için ertelenmiş denetim yazımı: kayıtlar commit anında zincire eklenir.

Neden: zincir kilidi (advisory lock) işlem sonuna kadar tutulur. Kilit işlemin ortasında
alınırsa, ardından satır kilidi isteyen iki işlem birbirini bekleyebilir (deadlock). Kayıtlar
`before_commit` anında yazıldığında zincir kilidi her işlemde alınan SON kilittir.

Kayıt, `audit_on_commit` çağrıldığı andaki projenin zincirine yazılır (commit anında bağlam
değişmiş olsa da; bağlam yoksa `append_audit` kuralı: `'_kurulum'`).

İşlem geri alınırsa bekleyen kayıtlar da atılır. Ham `Connection` kullanan kod
`append_audit()`'i doğrudan çağırabilir (o işlemde sonradan satır kilidi almamak koşuluyla).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from tp_core.audit.canonical import normalize
from tp_core.audit.chain import append_audit
from tp_core.proje.baglam import varsa

_ANAHTAR = "tp_audit_pending"


def audit_on_commit(
    session: Session,
    aktor: str,
    eylem: str,
    nesne: str | None = None,
    ozet: Mapping[str, Any] | None = None,
    *,
    project_id: str | None = None,
) -> None:
    """Denetim kaydını oturumun commit'ine bağlar (sıra korunur). Proje: açık `project_id`,
    yoksa şu anki bağlam."""
    if not aktor or not eylem:
        raise ValueError("aktor ve eylem boş olamaz")
    # Değerler şimdi dondurulur: sonradan değişen nesne alanları kaydı etkilemez.
    if project_id is None and (b := varsa()) is not None:
        project_id = b.pid
    kayit = (aktor, eylem, nesne, None if ozet is None else normalize(dict(ozet)), project_id)
    session.info.setdefault(_ANAHTAR, []).append(kayit)


def pending_audit(session: Session) -> list[tuple[str, str, str | None, Any]]:
    """Bekleyen kayıtlar `(aktor, eylem, nesne, ozet)` (proje alanı dışarı verilmez)."""
    return [k[:4] for k in session.info.get(_ANAHTAR, ())]


def _yaz(session: Session) -> None:
    bekleyen = session.info.pop(_ANAHTAR, None)
    if not bekleyen:
        return
    session.flush()
    conn = session.connection()
    for aktor, eylem, nesne, ozet, pid in bekleyen:
        append_audit(conn, aktor, eylem, nesne, ozet, project_id=pid)


def _temizle(session: Session, previous_transaction: Any) -> None:
    # Yalnızca dış işlem geri alınınca; SAVEPOINT geri alımı bekleyen kayıtlara dokunmaz
    # (platform SAVEPOINT kullanmaz; kullanan kod kaydını SAVEPOINT dışında eklemeli).
    if getattr(previous_transaction, "parent", None) is None:
        session.info.pop(_ANAHTAR, None)


event.listen(Session, "before_commit", _yaz)
event.listen(Session, "after_soft_rollback", _temizle)
