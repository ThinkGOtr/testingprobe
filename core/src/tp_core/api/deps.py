"""Özellik router'larının kullanacağı ortak bağımlılıklar (tek içe aktarma noktası).

Örnek::

    from fastapi import APIRouter, Depends
    from tp_core.api.deps import CurrentUser, DbSession, require_role

    router = APIRouter(tags=["requirements"])

    @router.post("/requirements/sync")
    def sync(session: DbSession, user=Depends(require_role("analyst"))): ...
"""

from tp_core.auth.deps import (
    CurrentUser,
    DbSession,
    current_user,
    require_role,
    require_token,
)
from tp_core.workflow.service import Principal

__all__ = ["CurrentUser", "DbSession", "Principal", "current_user", "require_role", "require_token"]
