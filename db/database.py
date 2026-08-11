"""Fachada de persistencia Postgres para licitaciones (motor único, ADR-021).

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
- ``connect_read()``        — context manager de solo lectura.
- ``close_pool()``          — cierra conexiones del hilo actual y el pool Postgres.
- ``ping()``                — ``SELECT 1`` de conectividad (health checks).
- ``pool_stats()``          — estado de los pools para métricas/diagnóstico.
- ``get_table_columns()``   — inspección de columnas (information_schema).
- ``now_utc()``             — datetime UTC aware (reemplaza datetime.utcnow()).
- ``now_utc_iso()``         — ISO 8601 del instante actual en UTC.
- ``set_pg_test_url()``     — apunta la suite al Postgres de tests (ADR-018).

**db.schema** — bootstrapping:

- ``init_db()`` — marca la BD como inicializada; idempotente. El esquema lo
  gestiona Alembic (ADR-021).

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
- ``count_licitaciones()``            — total de filas en la tabla (exacto, o
                                        estimado del planner con ``estimado=True``).
- ``estimar_filas()``                 — estimación O(1) de filas de una tabla.
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
    now_utc,
    now_utc_iso,
    ping,
    pool_stats,
    set_pg_test_url,
)

# Re-exportar desde db.schema
from db.schema import init_db

# Re-exportar desde db.upsert
from db.upsert import (
    Adjudicacion,
    DocumentoReferencia,
    Licitacion,
    Lote,
    UpsertResult,
    count_licitaciones,
    estimar_filas,
    fts_available,
    get_cursor,
    get_history,
    log_extraccion,
    replace_adjudicaciones,
    replace_adjudicaciones_batch,
    replace_lotes,
    replace_lotes_batch,
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
    "ping",
    "pool_stats",
    "get_table_columns",
    "now_utc",
    "now_utc_iso",
    "set_pg_test_url",
    # schema
    "init_db",
    # upsert
    "Adjudicacion",
    "DocumentoReferencia",
    "Licitacion",
    "Lote",
    "UpsertResult",
    "count_licitaciones",
    "estimar_filas",
    "fts_available",
    "get_cursor",
    "get_history",
    "log_extraccion",
    "replace_adjudicaciones",
    "replace_adjudicaciones_batch",
    "replace_lotes",
    "replace_lotes_batch",
    "search_fts",
    "set_cursor",
    "upsert_licitaciones",
    "upsert_licitaciones_with_history",
]
