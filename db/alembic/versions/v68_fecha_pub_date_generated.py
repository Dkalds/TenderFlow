"""v68: columna generada ``fecha_pub_d`` (date) en licitaciones.

Revision ID: v68_fecha_pub_date_generated
Revises: v67_pg_short_tz_offset_repair
Create Date: 2026-08-02

Las columnas de fecha son ``TEXT`` ISO-8601 (ver v59 y el docstring de
``db/repositories/aggregates.py``). Los filtros de rango lexicográficos
funcionan sobre el btree, pero cualquier agregación que necesite aritmética
de fechas (lead time, bucketing distinto del prefijo, comparaciones con
``date``) obliga a castear fila a fila. Esta revisión añade una columna
generada STORED con el prefijo fecha ya tipado, sin tocar el código de
ingesta: Postgres la mantiene en cada INSERT/UPDATE.

``text::date`` no es IMMUTABLE (depende de ``DateStyle``), así que la
expresión generada usa una función wrapper IMMUTABLE propia. Es una promesa
segura aquí: el prefijo ``YYYY-MM-DD`` se parsea igual bajo cualquier
``DateStyle`` y el CHECK de v59 garantiza el formato en escrituras nuevas.

OJO: añadir una columna GENERATED STORED reescribe la tabla (~1.2 GB,
AccessExclusiveLock durante la reescritura). Aplicar en ventana valle.
El índice se crea CONCURRENTLY en v69 (mismo patrón v65->v66).

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v68_fecha_pub_date_generated"
down_revision: str | None = "v67_pg_short_tz_offset_repair"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_ISO_PREFIX_TO_DATE_FN = """
CREATE OR REPLACE FUNCTION iso_prefix_to_date(v text)
RETURNS date
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
AS $$
    SELECT CASE
        WHEN v ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
        THEN substring(v from 1 for 10)::date
        ELSE NULL
    END
$$;
"""


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(_ISO_PREFIX_TO_DATE_FN)
    op.execute(
        "ALTER TABLE licitaciones ADD COLUMN IF NOT EXISTS fecha_pub_d date "
        "GENERATED ALWAYS AS (iso_prefix_to_date(fecha_publicacion)) STORED"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("ALTER TABLE licitaciones DROP COLUMN IF EXISTS fecha_pub_d")
    op.execute("DROP FUNCTION IF EXISTS iso_prefix_to_date(text)")
