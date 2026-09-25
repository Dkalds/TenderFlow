"""v142: GIN sobre los códigos de tecnología normalizados de ``licitaciones``.

El filtro de tecnología de todo el producto —agregados, rama FTS del listado,
export, agenda, RAG y adjudicaciones— es desde 2026-09 un solapamiento de arrays
sobre una sola expresión (``db.sql_fragments.tecnologia_tokens_sql``):
``string_to_array(...) && ARRAY[...]::text[]``. Hasta entonces era un ``unnest``
por fila o cuatro ``LIKE`` por código, sin índice posible, y el btree de ``v21``
es de igualdad sobre el CSV crudo, que nunca fue la pregunta. Con este índice
una consulta filtrada por tecnología lee las filas de esa tecnología en vez de
las ~1,64 M de la tabla, y las variantes por tecnología del snapshot del overview
dejan de ser escaneos secuenciales en cada pasada.

Opclass por defecto de GIN para arrays (``array_ops``): sirve ``&&``, ``@>``,
``<@`` y ``=``. Todas las funciones de la expresión son ``IMMUTABLE``. Es un
índice pequeño: una entrada por código distinto y fila, y las filas sin
clasificar (``{}``) dejan una sola entrada marcadora.

``idx_lic_tecnologia`` (``v21``) no se retira: lo siguen pudiendo usar las
consultas de renovaciones, que filtran por igualdad. Ver
``docs/plans/2026-09-indices-busqueda-propuestos.md``.

La expresión va congelada, como en ``v101``: ninguna migración de este linaje
importa de ``db/``. ``tests/test_indices_busqueda.py`` la compara con la viva, y
si divergen la corrección es una revisión nueva que reconstruya el índice, no
tocar esta constante.

``CONCURRENTLY`` no bloquea escrituras, pero si falla a medias deja un índice
``INVALID`` que el ``IF NOT EXISTS`` de un reintento daría por bueno (la nota de
``v134``): se tira antes de crear si se encuentra así.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v142_lic_tecnologia_tokens_gin
Revises: v141_tasas_anulacion_organo
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v142_lic_tecnologia_tokens_gin"
down_revision: str | Sequence[str] | None = "v141_tasas_anulacion_organo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDICE = "idx_lic_tecnologia_tokens"

#: Gemela congelada de ``db.sql_fragments.tecnologia_tokens_sql("tecnologia")``.
_TOKENS_TECNOLOGIA_SQL = "string_to_array(replace(COALESCE(tecnologia, ''), ' ', ''), ',')"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _descartar_si_invalido(nombre: str) -> None:
    """Tira ``nombre`` si existe como ``INVALID`` (un ``CONCURRENTLY`` fallido)."""
    fila = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT i.indisvalid FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = %s",
            (nombre,),
        )
        .fetchone()
    )
    if fila is not None and not fila[0]:
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}")


def upgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        # `statement_timeout = 0`: construir un índice sobre ~1,64 M filas pasa
        # de largo los 30 s del rol. Van como sentencias y no por `options`,
        # que no llega a través del pooler (ver `v79._relax_timeouts`).
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '30s'")
        _descartar_si_invalido(_INDICE)
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDICE} "
            f"ON licitaciones USING gin (({_TOKENS_TECNOLOGIA_SQL}))"
        )
        # Sin estadísticas de la expresión, el planificador estima a ciegas la
        # selectividad del `&&` hasta que pase el autovacuum.
        op.execute("ANALYZE licitaciones")


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '30s'")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDICE}")
