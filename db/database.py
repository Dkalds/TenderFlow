"""Fachada de persistencia SQLite / Turso (libSQL) para licitaciones.

Este módulo es el **punto de entrada único** al subsistema de base de datos.
Re-exporta todos los símbolos públicos de los tres submódulos especializados,
permitiendo que los importadores usen ``from db.database import X`` sin
necesidad de conocer la organización interna.

Mantener este módulo como fachada preserva la compatibilidad hacia atrás: si
en el futuro un símbolo se mueve entre submódulos, los importadores existentes
no requieren cambios.

Submódulos y símbolos reexportados
-----------------------------------

**db.connection** — pool de conexiones, context managers y helpers de bajo
nivel:

- ``connect()``             — context manager de escritura (commit/rollback).
- ``connect_read()``        — context manager de solo lectura; usa réplica
                              Turso si ``TURSO_REPLICA_URL`` está configurado.
- ``close_pool()``          — cierra conexiones del hilo actual y vacía el pool.
- ``get_table_columns()``   — inspección de columnas (PRAGMA + fallback Hrana).
- ``is_turso_backend()``    — True si la conexión activa es Turso/libSQL cloud.
- ``now_utc()``             — datetime UTC aware (reemplaza datetime.utcnow()).
- ``now_utc_iso()``         — ISO 8601 del instante actual en UTC.
- ``safe_pragma()``         — ejecuta PRAGMA solo si el backend lo soporta.
- ``set_db_path_override()``— override de ruta para tests (evita reload).
- ``set_pg_test_url()``     — apunta la suite a un Postgres real (ADR-018).

**db.schema** — DDL y bootstrapping:

- ``SCHEMA``    — string con todos los ``CREATE TABLE`` e índices del proyecto.
- ``init_db()`` — aplica el schema y migraciones pendientes; idempotente.

**db.upsert** — dataclasses de dominio y operaciones de escritura:

- ``Licitacion``                      — dataclass de una licitación PLACSP.
- ``Adjudicacion``                    — dataclass de una adjudicación.
- ``DocumentoReferencia``             — dataclass de un adjunto (pliego) referenciado
                                        en el CODICE (ver db.repositories.documentos).
- ``UpsertResult``                    — resultado enriquecido de upsert con
                                        historial (inserted/modified/unchanged).
- ``upsert_licitaciones()``           — bulk upsert sin historial; devuelve
                                        (nuevas, actualizadas).
- ``upsert_licitaciones_with_history()``— upsert con snapshot en
                                        ``licitaciones_history``.
- ``replace_adjudicaciones()``        — reemplaza adjudicaciones de una
                                        licitación (idempotente: DELETE + INSERT).
- ``replace_adjudicaciones_batch()``  — batch version: reemplaza adjudicaciones
                                        de múltiples licitaciones en una sola
                                        transacción (menos contención de lock).
- ``count_licitaciones()``            — total de filas en la tabla.
- ``log_extraccion()``                — registra una ejecución de extracción.
- ``get_cursor()`` / ``set_cursor()`` — lectura/escritura del cursor de
                                        ingesta por fuente.
- ``get_history()``                   — historial de cambios de una licitación.
- ``fts_available()``                 — True si la tabla FTS5 existe.
- ``search_fts()``                    — búsqueda full-text con paginación.

Uso típico
----------

    from db.database import connect, init_db, upsert_licitaciones, Licitacion

    init_db()
    with connect() as conn:
        ...

Ver también: ``db.users`` para operaciones de usuarios/auth (módulo hermano,
no reexportado aquí).
"""

from __future__ import annotations

# Re-exportar desde db.connection
from db.connection import (
    close_pool,
    connect,
    connect_read,
    get_table_columns,
    is_postgres_backend,
    is_turso_backend,
    now_utc,
    now_utc_iso,
    safe_pragma,
    set_db_path_override,
    set_pg_test_url,
)

# Re-exportar desde db.schema
from db.schema import (
    SCHEMA,
    init_db,
)

# Re-exportar desde db.upsert
from db.upsert import (
    Adjudicacion,
    DocumentoReferencia,
    Licitacion,
    UpsertResult,
    count_licitaciones,
    fts_available,
    get_cursor,
    get_history,
    log_extraccion,
    replace_adjudicaciones,
    replace_adjudicaciones_batch,
    search_fts,
    set_cursor,
    upsert_licitaciones,
    upsert_licitaciones_with_history,
)

__all__ = [
    # connection
    "connect",
    "connect_read",
    "close_pool",
    "get_table_columns",
    "is_postgres_backend",
    "is_turso_backend",
    "now_utc",
    "now_utc_iso",
    "safe_pragma",
    "set_db_path_override",
    "set_pg_test_url",
    # schema
    "SCHEMA",
    "init_db",
    # upsert
    "Adjudicacion",
    "DocumentoReferencia",
    "Licitacion",
    "UpsertResult",
    "count_licitaciones",
    "fts_available",
    "get_cursor",
    "get_history",
    "log_extraccion",
    "replace_adjudicaciones",
    "replace_adjudicaciones_batch",
    "search_fts",
    "set_cursor",
    "upsert_licitaciones",
    "upsert_licitaciones_with_history",
]
