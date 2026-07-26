"""Alembic environment — configurado para TenderFlow.

Este entorno lee DATABASE_URL si está disponible (Postgres/Supabase, ADR-016);
en caso contrario usa settings.DB_PATH (SQLite legacy).

Precedencia: DATABASE_URL > settings.DB_PATH > alembic.ini.

NOTA: El sistema de migraciones casero (db/migrations.py) gestiona las
versiones 1-13. Alembic se usa para migraciones nuevas (v14+).
Antes de usar Alembic, asegúrate de que el sistema casero haya aplicado
todas sus migraciones (`db.migrations.apply_pending`).
"""

import logging
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, engine_from_config, pool

from db.models import metadata

config = context.config

# Leer DATABASE_URL directamente del entorno (evita ConfigParser que interpola %).
# Si pydantic la obtuvo de `.env`, úsala también: Alembic debe migrar el mismo
# destino que la aplicación, no caer por error en SQLite local.
_database_url = os.environ.get("DATABASE_URL", "")
if not _database_url:
    try:
        from config import settings

        configured_url = settings.DATABASE_URL.get_secret_value()
        # A mocked/malformed configuration must never become an SQLAlchemy URL.
        _database_url = configured_url if isinstance(configured_url, str) else ""
    except Exception:
        logging.getLogger(__name__).warning(
            "Could not load DATABASE_URL from config.settings; falling back to SQLite",
            exc_info=True,
        )
_is_postgres = bool(_database_url and _database_url.startswith(("postgresql://", "postgres://")))

# Solo configurar via set_main_option para SQLite (sin caracteres especiales)
if not _is_postgres:
    try:
        from config import settings

        db_url = f"sqlite:///{settings.DB_PATH}"
        config.set_main_option("sqlalchemy.url", db_url)
    except Exception:
        logging.getLogger(__name__).warning(
            "Could not import config.settings; falling back to alembic.ini URL",
            exc_info=True,
        )

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# SQLAlchemy Core MetaData from db/models.py — enables autogenerate support.
target_metadata = metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = _database_url if _is_postgres else config.get_main_option("sqlalchemy.url")
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
    if _is_postgres:
        # Crear engine directamente con la URL (evita ConfigParser que interpola %).
        # SQLAlchemy resuelve el esquema "postgresql://" al driver psycopg2 por
        # defecto; el proyecto solo declara psycopg (v3) como dependencia
        # (requirements.txt), así que forzamos el dialecto "+psycopg" explícito.
        engine_url = _database_url
        if engine_url.startswith("postgresql://"):
            engine_url = "postgresql+psycopg://" + engine_url[len("postgresql://") :]
        elif engine_url.startswith("postgres://"):
            engine_url = "postgresql+psycopg://" + engine_url[len("postgres://") :]
        from config import settings

        connect_args: dict[str, object] = {}
        ssl_root_cert = settings.DATABASE_SSL_ROOT_CERT.strip()
        if ssl_root_cert:
            connect_args["sslrootcert"] = ssl_root_cert
        connect_timeout = int(settings.DB_CONNECT_TIMEOUT)
        if connect_timeout > 0:
            connect_args["connect_timeout"] = connect_timeout
        connectable = create_engine(
            engine_url,
            poolclass=pool.NullPool,
            connect_args=connect_args,
        )
    else:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

    try:
        connection_ctx = connectable.connect()
    except Exception as exc:  # solo el establecimiento de conexión puede filtrar el DSN
        try:
            from observability.logging import redact_dsn

            msg = redact_dsn(str(exc))
        except Exception:
            msg = "(redacted)"
        raise RuntimeError(f"Alembic no pudo conectar a la BD: {msg}") from None

    with connection_ctx as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
