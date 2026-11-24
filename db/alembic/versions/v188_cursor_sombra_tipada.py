"""v188: índice del cursor del listado sobre la sombra tipada (``idx_lic_cursor_ts``).

Revision ID: v188_cursor_sombra_tipada
Revises: v187_fact_sheets_attempts
Create Date: 2026-11-24

Qué falta
---------
Con ``NUCLEO_TIPADO_LECTURA`` encendido, ``list_cursor`` ordena por
``fecha_publicacion_ts DESC, id_externo DESC`` (``db/repositories/licitaciones/
listado.py``). ``v134`` solo creó ``idx_lic_fecha_publicacion_ts`` sobre la
fecha: sirve a los rangos, pero no da el desempate por ``id_externo`` y el
keyset tiene que ordenar lo que lee.

``idx_lic_cursor`` (``v79``) no lo cubre por dos motivos: va sobre la columna
de texto, y es parcial por ``tecnologia IS NOT NULL AND tecnologia <> ''``,
el universo del listado hasta el 2026-10-31. Desde entonces el listado filtra
con ``universo_producto_sql`` (un ``OR`` que ese predicado no implica), así que
el nuevo índice va **sin** predicado: el universo se aplica como filtro sobre
el recorrido en orden, que es lo que necesita una paginación keyset.

Se queda ``idx_lic_fecha_publicacion_ts``: lo comprueban el runbook de la
ventana del núcleo tipado y su test; retirarlo, ya cubierto por la columna
líder de este, va en otra revisión.

**Si el ``CREATE INDEX CONCURRENTLY`` falla a medias deja un índice
``INVALID``** y el ``IF NOT EXISTS`` de un reintento lo daría por bueno:
comprobar ``pg_index.indisvalid`` después de aplicar, como en ``v134``.

Coste: una pasada por ``licitaciones`` sin bloquear escrituras; ``lock_timeout``
acotado para el lock breve del principio y del final.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v188_cursor_sombra_tipada"
down_revision: str | None = "v187_fact_sheets_attempts"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

INDICE = "idx_lic_cursor_ts"


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
            "ON licitaciones (fecha_publicacion_ts DESC, id_externo DESC)"
        )
        # Que no se hereden en las revisiones que corran detrás en la misma sesión.
        op.execute("RESET lock_timeout")
        op.execute("RESET statement_timeout")


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDICE}")
