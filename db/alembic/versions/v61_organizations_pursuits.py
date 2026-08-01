"""v61: organizaciones, membresías y ciclo de vida de pursuits.

Revision ID: v61_organizations_pursuits
Revises: v60_pg_missing_user_columns
Create Date: 2026-07-30

La revisión es Postgres-only, en línea con ADR-021.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "v61_organizations_pursuits"
down_revision: str | None = "v60_pg_missing_user_columns"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_NOW = sa.text("NOW()")

# ``NOW()::text`` en Postgres omite los minutos del offset cuando son cero
# (p.ej. "2026-08-01 00:45:48.33444+00"), formato que pydantic rechaza como
# datetime (``datetime_from_date_parsing``). Este fragmento reproduce el
# mismo formato que ``db.connection.now_utc_iso()`` (ISO 8601 con offset
# completo) para los INSERT de backfill de esta migración.
_NOW_ISO_TEXT = "to_char(NOW() AT TIME ZONE 'utc', 'YYYY-MM-DD\"T\"HH24:MI:SS.US') || '+00:00'"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _protect_table(table: str) -> None:
    """Cierra Data API y conserva acceso del rol runtime de la aplicación."""
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
        f"CREATE POLICY tenderflow_app_full_access ON {table} "
        "FOR ALL TO tenderflow_app USING (true) WITH CHECK (true); "
        "END IF; END $$"
    )


def upgrade() -> None:
    if not _is_postgres():
        return

    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("is_personal", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "personal_owner_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("settings_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.Text, nullable=False, server_default=_NOW),
        sa.CheckConstraint(
            "(is_personal = FALSE AND personal_owner_user_id IS NULL) OR "
            "(is_personal = TRUE AND personal_owner_user_id IS NOT NULL)",
            name="ck_organizations_personal_owner",
        ),
        sa.UniqueConstraint(
            "personal_owner_user_id",
            name="uq_organizations_personal_owner",
        ),
    )

    op.create_table(
        "organization_memberships",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "organization_id",
            sa.Integer,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column(
            "invited_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.Text, nullable=False, server_default=_NOW),
        sa.CheckConstraint(
            "role IN ('owner','admin','member','viewer')",
            name="ck_organization_memberships_role",
        ),
        sa.CheckConstraint(
            "status IN ('active','invited','suspended','revoked')",
            name="ck_organization_memberships_status",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_organization_memberships_org_user",
        ),
    )
    op.create_index(
        "idx_org_memberships_user_status",
        "organization_memberships",
        ["user_id", "status"],
    )

    op.create_table(
        "pursuits",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "organization_id",
            sa.Integer,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "licitacion_id",
            sa.Text,
            sa.ForeignKey("licitaciones.id_externo", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "responsible_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.Text, nullable=False, server_default="identified"),
        sa.Column("decision", sa.Text, nullable=False, server_default="pending"),
        sa.Column("decision_reason", sa.Text, nullable=True),
        sa.Column("offer_price_eur", sa.Numeric(18, 2), nullable=True),
        sa.Column("outcome", sa.Text, nullable=False, server_default="pending"),
        sa.Column("awarded_amount_eur", sa.Numeric(18, 2), nullable=True),
        sa.Column("outcome_reason", sa.Text, nullable=True),
        sa.Column("identified_at", sa.Text, nullable=False, server_default=_NOW),
        sa.Column("decision_at", sa.Text, nullable=True),
        sa.Column("submitted_at", sa.Text, nullable=True),
        sa.Column("closed_at", sa.Text, nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.Text, nullable=False, server_default=_NOW),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.CheckConstraint(
            "status IN ('identified','qualifying','go_no_go','preparing',"
            "'submitted','won','lost','withdrawn')",
            name="ck_pursuits_status",
        ),
        sa.CheckConstraint(
            "decision IN ('pending','go','no_go')",
            name="ck_pursuits_decision",
        ),
        sa.CheckConstraint(
            "outcome IN ('pending','won','lost','cancelled')",
            name="ck_pursuits_outcome",
        ),
        sa.CheckConstraint(
            "offer_price_eur IS NULL OR offer_price_eur >= 0",
            name="ck_pursuits_offer_price",
        ),
        sa.CheckConstraint(
            "awarded_amount_eur IS NULL OR awarded_amount_eur >= 0",
            name="ck_pursuits_awarded_amount",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "licitacion_id",
            name="uq_pursuits_org_licitacion",
        ),
    )
    op.create_index(
        "idx_pursuits_org_status_updated",
        "pursuits",
        ["organization_id", "status", "updated_at"],
    )
    op.create_index(
        "idx_pursuits_org_responsible",
        "pursuits",
        ["organization_id", "responsible_user_id"],
    )

    op.create_table(
        "pursuit_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "pursuit_id",
            sa.Integer,
            sa.ForeignKey("pursuits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.Integer,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("payload_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("idempotency_key", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False, server_default=_NOW),
    )
    op.create_index(
        "idx_pursuit_events_pursuit_created",
        "pursuit_events",
        ["pursuit_id", "created_at"],
    )
    op.create_index(
        "idx_pursuit_events_org_created",
        "pursuit_events",
        ["organization_id", "created_at"],
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_pursuit_events_idempotency "
        "ON pursuit_events(pursuit_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )

    # Backfill determinista e idempotente: una organización personal por usuario.
    op.execute(
        "INSERT INTO organizations "
        "(name, is_personal, personal_owner_user_id, created_by_user_id, created_at, updated_at) "
        "SELECT COALESCE(NULLIF(display_name, ''), NULLIF(email, ''), 'Usuario ' || id::text), "
        f"TRUE, id, id, {_NOW_ISO_TEXT}, {_NOW_ISO_TEXT} "
        "FROM users "
        "ON CONFLICT (personal_owner_user_id) DO NOTHING"
    )
    op.execute(
        "INSERT INTO organization_memberships "
        "(organization_id, user_id, role, status, created_at, updated_at) "
        f"SELECT o.id, o.personal_owner_user_id, 'owner', 'active', {_NOW_ISO_TEXT}, {_NOW_ISO_TEXT} "
        "FROM organizations o "
        "WHERE o.is_personal = TRUE AND o.personal_owner_user_id IS NOT NULL "
        "ON CONFLICT (organization_id, user_id) DO NOTHING"
    )

    # Los eventos son un ledger: solo INSERT. La identidad puede anonimizarse
    # en ``users`` sin reescribir el historial.
    op.execute(
        "CREATE OR REPLACE FUNCTION public.prevent_pursuit_event_mutation() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN RAISE EXCEPTION 'pursuit_events is append-only'; END; $$"
    )
    op.execute(
        "CREATE TRIGGER trg_pursuit_events_append_only "
        "BEFORE UPDATE OR DELETE ON pursuit_events "
        "FOR EACH ROW EXECUTE FUNCTION public.prevent_pursuit_event_mutation()"
    )
    op.execute("REVOKE EXECUTE ON FUNCTION public.prevent_pursuit_event_mutation() FROM PUBLIC")

    # Mismo patrón fail-closed de v52 para Supabase/PostgREST.
    for table in (
        "organizations",
        "organization_memberships",
        "pursuits",
        "pursuit_events",
    ):
        _protect_table(table)

    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_app') THEN "
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tenderflow_app; "
        "END IF; END $$"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP TRIGGER IF EXISTS trg_pursuit_events_append_only ON pursuit_events")
    op.drop_table("pursuit_events")
    op.execute("DROP FUNCTION IF EXISTS public.prevent_pursuit_event_mutation()")
    op.drop_table("pursuits")
    op.drop_table("organization_memberships")
    op.drop_table("organizations")
