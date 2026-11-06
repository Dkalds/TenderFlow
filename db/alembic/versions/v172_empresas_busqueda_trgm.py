"""v172: GIN trigram para buscar empresas por nombre, NIF y alias.

La paleta ⌘K (``BusquedaRepository.empresas``) y el listado ``/empresas``
(``EmpresasReadRepository.list_empresas``) buscan con ``LIKE '%q%'``: sin un
trigram, cada búsqueda recorre el maestro entero. Medido en producción el
2026-11-06 con 52.450 empresas y 80.410 alias: ~1,3 s por consulta, demasiado
para una paleta que consulta al teclear (``shortcut:`` de ``busqueda.py``).

Tres índices, uno por rama de la búsqueda:

- ``idx_empresas_nombre_plegado_trgm``: el nombre canónico **plegado**, la misma
  expresión que emite ``db.sql_fragments.fold_expr`` (congelada aquí, como en
  ``v143``; ``tests/test_indices_busqueda.py`` la compara con la viva).
- ``idx_empresas_nif_trgm`` y ``idx_empresa_aliases_alias_trgm``: ``nif_canonico``
  y ``alias_normalizado`` ya se guardan en mayúsculas y sin tildes, así que se
  indexan tal cual.

``CONCURRENTLY``, como ``v142``/``v143``: las dos tablas son pequeñas (11 MB el
maestro) y el índice se construye en segundos, pero así la revisión no bloquea
las escrituras del maestro aunque coincida con una ingesta.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v172_empresas_busqueda_trgm
Revises: v171_access_grants_revoked_by
Create Date: 2026-11-06
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v172_empresas_busqueda_trgm"
down_revision: str | Sequence[str] | None = "v171_access_grants_revoked_by"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORIGEN = "'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ'"
_DESTINO = "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC'"

#: Gemela congelada de ``db.sql_fragments.fold_expr("nombre_canonico")``.
NOMBRE_PLEGADO = f"lower(translate(nombre_canonico, {_ORIGEN}, {_DESTINO}))"

#: Nombre → (tabla, expresión indexada).
INDICES: dict[str, tuple[str, str]] = {
    "idx_empresas_nombre_plegado_trgm": ("empresas", NOMBRE_PLEGADO),
    "idx_empresas_nif_trgm": ("empresas", "nif_canonico"),
    "idx_empresa_aliases_alias_trgm": ("empresa_aliases", "alias_normalizado"),
}


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
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '30s'")
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        for nombre, (tabla, expresion) in INDICES.items():
            _descartar_si_invalido(nombre)
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {nombre} "
                f"ON {tabla} USING gin (({expresion}) gin_trgm_ops)"
            )
        op.execute("ANALYZE empresas")
        op.execute("ANALYZE empresa_aliases")


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '30s'")
        for nombre in reversed(INDICES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}")
