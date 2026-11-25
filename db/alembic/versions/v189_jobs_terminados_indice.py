"""v189: índice parcial de los ``jobs`` terminados para su purga (``ix_jobs_terminados``).

Revision ID: v189_jobs_terminados_indice
Revises: v188_cursor_sombra_tipada
Create Date: 2026-11-25

Qué falta
---------
La retención (``db/retention.py``, política en ``scheduler/retention.py``)
borra por lotes los ``jobs`` con ``updated_at`` anterior al plazo **y**
``estado IN ('done', 'failed')``: lo que espera o corre no se purga nunca. Los
índices de ``v106`` son los de la cola (``ix_jobs_pendientes``,
``ix_jobs_corriendo``) y el de la organización; ninguno sirve a ese
predicado, así que cada lote de la purga recorría la tabla entera. Pendiente de
la auditoría del 2026-11-04.

El índice es parcial con el mismo predicado que la purga: solo contiene lo
terminado, que es lo único que se borra, y el planificador lo usa porque el
``WHERE`` de la purga lo implica literalmente.

``CONCURRENTLY`` en bloque autocommit, como ``v188``: no bloquea la cola
mientras se construye. Si falla a medias deja un índice ``INVALID`` que el
``IF NOT EXISTS`` de un reintento daría por bueno: comprobar
``pg_index.indisvalid`` después de aplicar.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v189_jobs_terminados_indice"
down_revision: str | None = "v188_cursor_sombra_tipada"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

INDICE = "ix_jobs_terminados"

#: El predicado de la purga (``db.retention._SOLO_SI["jobs"]``), copiado: una
#: migración no importa código de la app. ``tests/test_v189_*`` compara los dos.
PREDICADO = "estado IN ('done', 'failed')"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '30s'")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDICE} "
            f"ON jobs (updated_at) WHERE {PREDICADO}"
        )
        op.execute("RESET lock_timeout")
        op.execute("RESET statement_timeout")


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDICE}")
