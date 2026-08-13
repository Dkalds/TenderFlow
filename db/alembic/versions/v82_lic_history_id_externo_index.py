"""Migración v82 — índice sobre licitaciones_history.id_externo.

``licitaciones_history.id_externo`` es FK a ``licitaciones`` con
``ON DELETE CASCADE``, y no tenía índice: Postgres no indexa las claves
foráneas automáticamente. Cada fila borrada en ``licitaciones`` obligaba a un
escaneo secuencial completo de la tabla de histórico (171 MB en producción)
para localizar qué cascadear, así que un borrado por lotes no terminaba nunca.
Se descubrió al purgar el corpus el 2026-08-13, donde lotes de 50.000 filas
expiraban por timeout; con el índice el mismo lote se resuelve en segundos.

También sirve a cualquier consulta del histórico por expediente.

Ya existe en producción, creado a mano para desatascar aquella purga: de ahí el
``IF NOT EXISTS``, que convierte esta migración en un no-op allí y reconcilia
la deriva entre el linaje de Alembic y la base real (mismo criterio que v79).

``CONCURRENTLY`` requiere autocommit, así que va dentro de ``autocommit_block``:
la tabla sigue aceptando escrituras mientras el índice se construye.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v82_lic_history_id_externo_index
Revises: v81_tech_signal_method_llm_metadata
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v82_lic_history_id_externo_index"
down_revision: str | Sequence[str] | None = "v81_tech_signal_method_llm_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDICE = "idx_lic_history_id_externo"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '30s'")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDICE} "
            "ON licitaciones_history (id_externo)"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDICE}")
