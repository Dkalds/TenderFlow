"""Inicialización de la conexión a BD.

Desde ADR-021 el esquema lo gestiona **exclusivamente Alembic**
(``db/alembic/``): no hay DDL en el código de aplicación. Este módulo conserva
``init_db()`` porque una veintena de entry points de producción y la suite lo
invocan como paso de arranque, pero su trabajo real hoy es marcar el proceso
como inicializado.

Lo que vivía aquí y se retiró junto con SQLite:

- La constante ``SCHEMA`` (~460 líneas de ``CREATE TABLE`` en dialecto SQLite),
  que duplicaba lo que ya describen las migraciones Alembic y era la fuente del
  desajuste que ADR-018 documentó (los seis ``CHECK ... GLOB`` que nunca
  viajaron a producción).
- Los helpers ``_ensure_*_columns()``: reconciliación de columnas al estilo
  SQLite (``ALTER TABLE ... ADD COLUMN`` en bucle, tragándose el error si la
  columna ya existía). En Postgres una columna ausente es un fallo de migración
  que debe verse, no algo que la aplicación parchee en caliente al arrancar.
- La llamada a ``db.migrations.apply_pending()`` (sistema de migraciones
  casero, borrado en ADR-021).
"""

from __future__ import annotations

import db.connection as _conn_module

# ---------------------------------------------------------------------------
# Inicialización
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Marca la BD como inicializada para este proceso. Idempotente.

    No-op efectivo: con Postgres como único motor (ADR-021) el esquema ya lo
    aplicó ``alembic upgrade head`` antes de que el proceso arranque. Se
    mantiene como punto único de arranque y por compatibilidad con los
    call-sites existentes.
    """
    if _conn_module._db_initialized:
        return
    _conn_module._db_initialized = True
