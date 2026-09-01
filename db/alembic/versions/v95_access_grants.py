"""v95: concesiones dinámicas de acceso OAuth.

Revision ID: v95_access_grants
Revises: v94_mv_licitaciones_canonicas
Create Date: 2026-09-01

La configuración estática sigue siendo el bootstrap. Esta tabla añade grants
administrables y auditables sin convertir una caída de BD en acceso abierto.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v95_access_grants"
down_revision: str | Sequence[str] | None = "v94_mv_licitaciones_canonicas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _protect_table(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN "
        f"REVOKE ALL ON TABLE {table} FROM anon; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN "
        f"REVOKE ALL ON TABLE {table} FROM authenticated; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_app') THEN "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO tenderflow_app; "
        f"GRANT USAGE, SELECT ON SEQUENCE {table}_id_seq TO tenderflow_app; "
        f"CREATE POLICY tenderflow_app_full_access ON {table} "
        "FOR ALL TO tenderflow_app USING (true) WITH CHECK (true); "
        "END IF; END $$"
    )


def upgrade() -> None:
    if not _is_postgres():
        return
    op.create_table(
        "access_grants",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("granted_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('email', 'domain')", name="ck_access_grants_kind"),
        sa.UniqueConstraint("kind", "value", name="uq_access_grants_kind_value"),
    )
    op.create_index(
        "ix_access_grants_active_kind_value",
        "access_grants",
        ["active", "kind", "value"],
    )
    _protect_table("access_grants")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_index("ix_access_grants_active_kind_value", table_name="access_grants")
    op.drop_table("access_grants")
