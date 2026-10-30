from functools import lru_cache

from sqlalchemy import Engine, create_engine, text

from tp_core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        pool_size=5,
        connect_args={"connect_timeout": 3},
    )


def ping(sql: str = "SELECT 1") -> None:
    with get_engine().connect() as conn:
        conn.execute(text(sql))
