from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from tp_core.config import get_settings

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)


def run_migrations_online() -> None:
    engine = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("offline migrasyon desteklenmiyor")
run_migrations_online()
