"""Veritabanı bağlantısı. Engine tembel oluşturulur; DB yokken uygulama yine açılır."""

import os
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    url = os.environ.get("DEMOAPP_DATABASE_URL")
    if not url:
        raise RuntimeError("DEMOAPP_DATABASE_URL tanımlı değil")
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
        connect_args={"connect_timeout": 2},
    )


def check_db() -> str:
    """'ok' ya da 'error: <neden>' döner; asla istisna fırlatmaz."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001 — sağlık kontrolü her hatayı raporlar
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        return f"error: {reason[:200]}"
