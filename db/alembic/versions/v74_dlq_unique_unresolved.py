"""v74: índice único parcial en ``failed_extractions`` (dedup por carrera de DLQ).

Revision ID: v74_dlq_unique_unresolved
Revises: v73_audit_log_created_idx
Create Date: 2026-08-07

``db.dlq.record_failure`` es SELECT-then-INSERT: dos escritores concurrentes con
el mismo ``(fuente, scope, payload_ref)`` no resuelto pasan ambos el SELECT y
crean dos filas abiertas, inflando el conteo del panel de calidad y disparando
reintentos dobles. El código creía apoyarse en un índice único que nunca viajó
al linaje Postgres (era del sistema SQLite casero retirado en ADR-021). Este
índice único parcial materializa la invariante que ``record_failure`` asume: a
lo sumo una fila abierta por clave.

El predicado (``resolved_at IS NULL AND exhausted_at IS NULL``) y las claves con
``COALESCE(...,'')`` replican EXACTAMENTE el WHERE del SELECT de deduplicación de
``record_failure``, para que la garantía del índice coincida con la semántica del
código.

Como el bug pudo dejar duplicados abiertos preexistentes, ``upgrade`` primero los
colapsa (deja abierto el de mayor ``id`` por clave y marca el resto como
resueltos) para que el índice único pueda construirse. Esa limpieza corre en la
transacción de la migración y queda confirmada al entrar el ``autocommit_block``
que crea el índice CONCURRENTLY (no puede correr en transacción).

DIALECT-GUARDED: solo actúa en Postgres.

REVISAR ANTES DE APLICAR: escrito sin BD en la sesión (AGENTS.md §4). El paso de
limpieza MODIFICA datos (marca duplicados abiertos como resueltos). Conviene
correr antes, contra la BD real, el conteo de duplicados afectados:
``SELECT fuente, COALESCE(scope,''), COALESCE(payload_ref,''), COUNT(*)
  FROM failed_extractions WHERE resolved_at IS NULL AND exhausted_at IS NULL
  GROUP BY 1,2,3 HAVING COUNT(*) > 1;``
"""

from __future__ import annotations

from alembic import op

revision: str = "v74_dlq_unique_unresolved"
down_revision: str | None = "v73_audit_log_created_idx"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    # 1. Colapsar duplicados abiertos preexistentes: conserva abierto solo el de
    #    mayor id por clave y marca los más viejos como resueltos (TEXT ISO,
    #    igual que now_utc_iso()). Sin esto el índice único fallaría al crearse.
    op.execute(
        """
        UPDATE failed_extractions f
        SET resolved_at = to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD"T"HH24:MI:SS')
        WHERE f.resolved_at IS NULL
          AND f.exhausted_at IS NULL
          AND f.id < (
            SELECT MAX(f2.id) FROM failed_extractions f2
            WHERE f2.fuente = f.fuente
              AND COALESCE(f2.scope, '') = COALESCE(f.scope, '')
              AND COALESCE(f2.payload_ref, '') = COALESCE(f.payload_ref, '')
              AND f2.resolved_at IS NULL
              AND f2.exhausted_at IS NULL
          )
        """
    )
    # 2. Índice único parcial CONCURRENTLY (el autocommit_block confirma la
    #    limpieza anterior antes de construir el índice sin bloquear escrituras).
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_fail_unique_unresolved "
            "ON failed_extractions "
            "(fuente, COALESCE(scope, ''), COALESCE(payload_ref, '')) "
            "WHERE resolved_at IS NULL AND exhausted_at IS NULL"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    # Solo se revierte el índice; la limpieza de duplicados no es reversible
    # (no se puede saber cuáles se marcaron resueltos en esta migración).
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_fail_unique_unresolved")
