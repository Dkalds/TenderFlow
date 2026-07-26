"""Migracion v59 -- CHECK de formato de fecha en Postgres (paridad con SQLite).

``db/schema.py`` protege seis columnas de fecha con
``CHECK(col IS NULL OR col GLOB '????-??-??*')``. ``GLOB`` es un operador
**exclusivo de SQLite**: al portar el schema a Postgres (ADR-016) esos CHECK
no viajaron, y ninguna de las seis columnas tiene hoy restriccion en
produccion. El resultado es que Postgres acepta ``'14/06/2026'`` en
``adjudicaciones.fecha_adjudicacion`` -- una columna indexada
(``idx_adj_fecha``) que el codigo compara y ordena lexicograficamente
asumiendo ISO-8601.

El hueco era invisible porque la suite de tests corria sobre SQLite mientras
produccion corre Postgres: ``test_replace_adjudicaciones_drops_constraint_violation``
"demostraba" que la fila se rechazaba. Detectado al migrar la suite al motor
real (ADR-018).

Equivalente Postgres de ``GLOB '????-??-??*'``: ``~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'``.

``NOT VALID``: la restriccion se aplica a INSERT/UPDATE nuevos pero **no**
valida las filas ya presentes, que pueden traer fechas malformadas de antes
del cutover. Anadirla como VALID abortaria la migracion en produccion. Una vez
saneado el historico se puede promover con::

    ALTER TABLE <tabla> VALIDATE CONSTRAINT <nombre>;

DIALECT-GUARDED: solo actua en Postgres; en SQLite los CHECK ya existen en
``db/schema.py``.

Revision ID: v59_pg_date_format_checks
Revises: v58_drop_mat_top_empresas_ccaa
Create Date: 2026-07-26
"""

from __future__ import annotations

from alembic import op

revision: str = "v59_pg_date_format_checks"
down_revision: str | None = "v58_drop_mat_top_empresas_ccaa"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

# (tabla, columna) -- espejo de los CHECK GLOB de db/schema.py
_DATE_COLUMNS: list[tuple[str, str]] = [
    ("licitaciones", "fecha_publicacion"),
    ("licitaciones", "fecha_limite"),
    ("licitaciones", "fecha_inicio"),
    ("licitaciones", "fecha_fin"),
    ("licitaciones", "fecha_actualizacion_fuente"),
    ("adjudicaciones", "fecha_adjudicacion"),
]

_ISO_PREFIX = "^[0-9]{4}-[0-9]{2}-[0-9]{2}"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _constraint_name(table: str, column: str) -> str:
    return f"ck_{table}_{column}_iso"


def upgrade() -> None:
    if not _is_postgres():
        return
    for table, column in _DATE_COLUMNS:
        name = _constraint_name(table, column)
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} "
            f"CHECK ({column} IS NULL OR {column} ~ '{_ISO_PREFIX}') NOT VALID"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    for table, column in _DATE_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {_constraint_name(table, column)}"
        )
