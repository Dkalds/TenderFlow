"""v143: GIN trigram sobre las cuatro columnas plegadas de la búsqueda ``q``.

La búsqueda ``q`` del listado y de los agregados es un ``LIKE '%q%'`` sobre la
versión plegada (sin acentos, en minúsculas) de ``titulo``, ``descripcion``,
``organo_contratacion`` e ``id_externo``, en ``OR``. El único trigram que había
es el de ``v50``, sobre ``titulo`` **sin plegar**: la consulta no pregunta por esa
columna, así que no servía, y cada búsqueda recorría ~1,64 M filas aplicando
``translate``/``lower`` a cuatro columnas por fila.

**Las cuatro o ninguna.** Un ``OR`` solo se resuelve con ``BitmapOr`` si todas
sus ramas tienen índice; con tres de cuatro sigue siendo secuencial, y se habría
pagado el disco sin ganar nada.

Las expresiones son **literalmente** las que emiten ``db.sql_fragments.fold_expr``
y ``_plegado`` del listado, con las tablas de plegado como literales SQL y no
como parámetros ligados (el paso 1 de
``docs/plans/2026-09-indices-busqueda-propuestos.md``): con psycopg y plan
genérico, un ``translate(col, $1, $2)`` no casa con ningún índice de expresión.
Van congeladas y ``tests/test_indices_busqueda.py`` las compara con las vivas.

**Riesgo de disco.** ``descripcion`` es texto largo, y un GIN trigram ocupa del
orden de una a tres veces el volumen indexado. La propuesta trae las consultas
para medirlo antes de aplicar y las alternativas si no cabe. Esta revisión se
aplica a mano con ``migrate.yml``, en una ventana sin ingesta:
``CONCURRENTLY`` hace dos pasadas por la tabla por índice.

Un ``q`` de menos de tres caracteres no produce trigramas: ahí el planificador
sigue eligiendo el escaneo secuencial, que es lo correcto. El trigram de
``titulo`` de ``v50`` no se retira: lo puede seguir usando el ``ILIKE`` de
``LicitacionRepository.fetch_for_pdf``.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v143_lic_busqueda_plegada_trgm
Revises: v142_lic_tecnologia_tokens_gin
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v143_lic_busqueda_plegada_trgm"
down_revision: str | Sequence[str] | None = "v142_lic_tecnologia_tokens_gin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORIGEN = "'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ'"
_DESTINO = "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC'"

#: Gemelas congeladas de ``db.sql_fragments.fold_expr(<columna>)``, en el orden
#: de ``_COLUMNAS_BUSQUEDA`` del listado.
_INDICES_PLEGADOS = {
    "idx_lic_titulo_plegado_trgm": f"lower(translate(titulo, {_ORIGEN}, {_DESTINO}))",
    "idx_lic_descripcion_plegada_trgm": f"lower(translate(descripcion, {_ORIGEN}, {_DESTINO}))",
    "idx_lic_organo_plegado_trgm": (
        f"lower(translate(organo_contratacion, {_ORIGEN}, {_DESTINO}))"
    ),
    "idx_lic_id_externo_plegado_trgm": f"lower(translate(id_externo, {_ORIGEN}, {_DESTINO}))",
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
        # Ver `v142`: estos índices tardan mucho más que los 30 s del rol.
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '30s'")
        # La crea `v50`; se repite para que la revisión no dependa de ello.
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        for nombre, expresion in _INDICES_PLEGADOS.items():
            _descartar_si_invalido(nombre)
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {nombre} "
                f"ON licitaciones USING gin (({expresion}) gin_trgm_ops)"
            )
        op.execute("ANALYZE licitaciones")


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '30s'")
        for nombre in reversed(_INDICES_PLEGADOS):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}")
