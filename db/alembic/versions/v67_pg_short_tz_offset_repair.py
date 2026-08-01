"""v67: repara offsets de timezone cortos en organizations/organization_memberships.

Revision ID: v67_pg_short_tz_offset_repair
Revises: v66_lotes_index_concurrent
Create Date: 2026-08-01

Los backfills de v61 (``_ENSURE_PERSONAL_ORGANIZATIONS``/``..._MEMBERSHIPS``) y
v64 (mismo patrón) escribían ``created_at``/``updated_at`` con ``NOW()::text``.
Postgres serializa un ``timestamptz`` a texto omitiendo los minutos del offset
cuando son cero -- p.ej. ``2026-08-01 00:45:48.33444+00`` en vez de
``...+00:00`` -- y ese formato no cumple RFC3339 estricto: pydantic lo
rechaza con ``datetime_from_date_parsing`` al validar ``OrganizationSummary``
y ``OrganizationMembershipOut`` (``shared/dto.py``).

Esta migración:

1. Normaliza las filas ya escritas con ese offset corto a formato completo
   (``+00`` -> ``+00:00``), sin tocar filas que ya estén bien formadas.
2. Corrige el ``DEFAULT`` de columna (server_default) para que un INSERT que
   omita ``created_at``/``updated_at`` -- hoy no ocurre en el código de
   aplicación, que siempre pasa ``now_utc_iso()`` explícito, pero es el
   comportamiento documentado de la columna -- no reintroduzca el mismo
   formato roto.

``pursuits``/``pursuit_events`` comparten el mismo ``server_default=NOW()``
en v61 pero sus repositories (``db/repositories/pursuits.py``) siempre
insertan ``created_at``/``updated_at`` explícitos vía ``now_utc_iso()``, así
que no hay backfill ni server_default alguna vez disparado para esas tablas:
no requieren reparación de datos, aunque igualmente reciben la corrección del
DEFAULT por prolijidad/defensa en profundidad.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v67_pg_short_tz_offset_repair"
down_revision: str | None = "v66_lotes_index_concurrent"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

# Mismo formato que db.connection.now_utc_iso(): ISO 8601 con offset completo.
_NOW_ISO_TEXT = "to_char(NOW() AT TIME ZONE 'utc', 'YYYY-MM-DD\"T\"HH24:MI:SS.US') || '+00:00'"

# (tabla, columna) con server_default=NOW() heredado de v61.
_DEFAULT_COLUMNS: list[tuple[str, str]] = [
    ("organizations", "created_at"),
    ("organizations", "updated_at"),
    ("organization_memberships", "created_at"),
    ("organization_memberships", "updated_at"),
    ("pursuits", "created_at"),
    ("pursuits", "updated_at"),
    ("pursuit_events", "created_at"),
]

# (tabla, columna) con datos de backfill ya escritos en formato corto -- solo
# organizations/organization_memberships, ver docstring.
_REPAIR_COLUMNS: list[tuple[str, str]] = [
    ("organizations", "created_at"),
    ("organizations", "updated_at"),
    ("organization_memberships", "created_at"),
    ("organization_memberships", "updated_at"),
]


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    for table, column in _REPAIR_COLUMNS:
        op.execute(
            f"UPDATE {table} SET {column} = regexp_replace({column}, "
            r"'([+-][0-9]{2})$', '\1:00') "
            f"WHERE {column} ~ '[+-][0-9]{{2}}$'"
        )

    for table, column in _DEFAULT_COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT ({_NOW_ISO_TEXT})")


def downgrade() -> None:
    if not _is_postgres():
        return

    # No hay downgrade con sentido: revertir el DEFAULT a NOW() reintroduciría
    # el formato roto, y los datos reparados son texto ISO 8601 tan válido
    # como el que producía la app antes de esta migración.
    return
