"""Alembic environment — configurado para licitaciones-sap.

Este entorno utiliza la URL de la BD definida en config.settings.DB_PATH,
con fallback al alembic.ini.

NOTA: El sistema de migraciones casero (db/migrations.py) gestiona las
versiones 1-13. Alembic se usa para migraciones nuevas (v14+).
Antes de usar Alembic, asegúrate de que el sistema casero haya aplicado
todas sus migraciones (`db.migrations.apply_pending`).
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

# Sobreescribir la URL con la de config.settings si está disponible
try:
    from config import settings

    db_url = f"sqlite:///{settings.DB_PATH}"
    config.set_main_option("sqlalchemy.url", db_url)
except Exception:
    pass  # fallback a alembic.ini

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
