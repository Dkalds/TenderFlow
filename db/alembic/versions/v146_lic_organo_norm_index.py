"""v146: índice por el órgano plegado de ``licitaciones``.

Revision ID: v146_lic_organo_norm_index
Revises: v145_cuenta_organos
Create Date: 2026-09-25

Qué falta hoy
-------------
Las cuentas objetivo (F1.5) casan sus órganos contra ``licitaciones`` por
``organo_normalizado_sql`` —el nombre plegado, que es la identidad del órgano
mientras el maestro (C1.2) no cubra el corpus—. Ningún índice cubre esa
expresión: ``idx_organo`` indexa el texto crudo y ``idx_lic_clave_canonica_v101``
la lleva dentro de un ``md5``. Sin índice, el resumen de la lista de cuentas y
la ficha de cada una serían un escaneo completo de ~710k filas con un
``translate`` por fila en cada carga de pantalla.

Va en revisión aparte de v145 por lo mismo que v101 fue aparte de v100:
``CREATE INDEX CONCURRENTLY`` no puede correr dentro de una transacción, y el
backfill de v145 sí tiene que ir en una. ``CONCURRENTLY`` porque el scraper
tiene que poder seguir escribiendo mientras se construye.

La expresión va congelada en vez de importarse del árbol de la app, como en
v101: ninguna migración de este linaje importa de ``db/``. El precio —que se
separe de su gemela sin que nadie se entere y el planificador deje de usar el
índice en silencio— lo cubre ``tests/test_organo_norm_index.py``.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v146_lic_organo_norm_index"
down_revision: str | Sequence[str] | None = "v145_cuenta_organos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDICE = "idx_lic_organo_norm"

#: Gemela congelada de ``db.sql_fragments.organo_normalizado_sql("licitaciones")``.
_ORGANO_NORMALIZADO_SQL = (
    "nullif(lower(translate(btrim(coalesce(licitaciones.organo_contratacion, '')), "
    "'áàäâéèëêíìïîóòöôúùüûñçÁÀÄÂÉÈËÊÍÌÏÎÓÒÖÔÚÙÜÛÑÇ', "
    "'aaaaeeeeiiiioooouuuuncAAAAEEEEIIIIOOOOUUUUNC')), '')"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        # `statement_timeout = 0`: construir el índice sobre ~710k filas pasa
        # de largo los 30 s del rol.
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '30s'")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDICE} "
            f"ON licitaciones (({_ORGANO_NORMALIZADO_SQL}))"
        )
        op.execute("ANALYZE licitaciones")


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDICE}")
