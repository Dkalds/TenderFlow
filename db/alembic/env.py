"""Alembic environment — configurado para TenderFlow.

Migra la base de ``DATABASE_URL`` (Postgres/Supabase, ADR-016): la del entorno
o, si no está, la que resuelve ``config.settings`` desde ``.env``. SQLite se
retiró (ADR-021), así que sin una URL de Postgres el entorno falla en vez de
migrar otra cosa.
"""

import logging
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

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
            "Could not load DATABASE_URL from config.settings", exc_info=True
        )
if not _database_url.startswith(("postgresql://", "postgres://")):
    raise RuntimeError(
        "Alembic necesita DATABASE_URL apuntando a Postgres (SQLite se retiró, ADR-021)."
    )

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# SQLAlchemy Core MetaData from db/models.py — enables autogenerate support.
target_metadata = metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
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
