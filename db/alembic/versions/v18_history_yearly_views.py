"""Migración v18 — Vistas anuales de licitaciones_history.

SQLite no soporta particionado nativo, por lo que creamos vistas filtradas
por año (2022-2026) sobre ``licitaciones_history``. Estas vistas se pueden
usaren consultas de análisis temporal para evitar full-scans de la tabla.

También añade un índice compuesto (id_externo, changed_at) si no existe.

Revision ID: v18_history_yearly_views
Revises: v17_totp_sessions
Create Date: 2026-05-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v18_history_yearly_views"
down_revision: str | Sequence[str] | None = "v17_totp_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_YEARS = list(range(2022, 2027))


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    # CREATE VIEW IF NOT EXISTS es sintaxis SQLite; Postgres usa
    # CREATE OR REPLACE VIEW (semánticamente equivalente para este caso:
    # idempotente, la vista siempre queda con esta misma definición).
    create_view = "CREATE OR REPLACE VIEW" if is_postgres else "CREATE VIEW IF NOT EXISTS"
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_licitaciones_history_externo_date "
        "ON licitaciones_history(id_externo, captured_at)"
    )
    for year in _YEARS:
        op.execute(
            f"{create_view} licitaciones_history_{year} AS "
            f"SELECT * FROM licitaciones_history "
            f"WHERE captured_at >= '{year}-01-01' AND captured_at < '{year + 1}-01-01'"
        )


def downgrade() -> None:
    for year in reversed(_YEARS):
        op.execute(f"DROP VIEW IF EXISTS licitaciones_history_{year}")
    op.drop_index("idx_licitaciones_history_externo_date", table_name="licitaciones_history")
