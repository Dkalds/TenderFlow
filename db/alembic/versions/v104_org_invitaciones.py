"""v104: invitaciones de organización a correos sin cuenta.

Revision ID: v104_org_invitaciones
Revises: v103_documentos_blob_ocr
Create Date: 2026-09-06

``organization_memberships.user_id`` es NOT NULL con FK a ``users``, así que un
correo que todavía no tiene cuenta **no puede** tener membresía: por eso
``services.organizations.add_member_by_email`` rechazaba el alta. Esta tabla es
la pieza que faltaba — guarda la intención («este correo entra en esta
organización con este rol») hasta que exista la persona a la que apuntar.

Diseño, y por qué:

* ``token_hash`` — solo se persiste SHA-256 del token; el valor bruto vive
  únicamente en el correo, igual que en ``password_reset_tokens`` (v96). El
  token además va firmado con ``shared.signing`` (lleva ``kid``, así que
  sobrevive a una rotación de la clave), pero la firma no da unicidad de uso:
  eso lo da esta fila.
* ``accepted_at``/``revoked_at`` — un solo uso y revocación son estados, no
  borrados: quien audite el equipo tiene que poder ver que se invitó a alguien
  y qué pasó con esa invitación.
* Único parcial sobre ``(organization_id, lower(email))`` **solo mientras la
  invitación está viva**: dos invitaciones pendientes al mismo correo en la
  misma organización son un error de la UI, pero volver a invitar a alguien
  cuya invitación caducó o se revocó es legítimo.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v104_org_invitaciones"
down_revision: str | Sequence[str] | None = "v103_documentos_blob_ocr"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _protect_table(table: str) -> None:
    """RLS + grants mínimos, el mismo patrón que v96."""
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
        "organization_invitations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "organization_id",
            sa.Integer,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False, unique=True),
        sa.Column(
            "invited_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "accepted_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revoked_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # `owner` queda fuera a propósito: la propiedad no se transfiere por
        # correo (ver `_guard_owner_row` en services/organizations.py).
        sa.CheckConstraint(
            "role IN ('admin','member','viewer')",
            name="ck_organization_invitations_role",
        ),
    )
    # SQL crudo y no `op.create_index`: son índices por EXPRESIÓN
    # (``lower(email)``) y parciales a la vez, y escribirlos tal cual deja ver
    # exactamente qué se crea sin depender de cómo compone Alembic la mezcla.
    op.execute(
        "CREATE UNIQUE INDEX uq_organization_invitations_pendiente "
        "ON organization_invitations (organization_id, lower(email)) "
        "WHERE accepted_at IS NULL AND revoked_at IS NULL"
    )
    # El login pregunta «¿tiene este correo invitaciones vivas?» en cada
    # entrada: sin este índice sería un seq scan por cada inicio de sesión.
    op.execute(
        "CREATE INDEX ix_organization_invitations_email_pendiente "
        "ON organization_invitations (lower(email)) "
        "WHERE accepted_at IS NULL AND revoked_at IS NULL"
    )
    _protect_table("organization_invitations")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP INDEX IF EXISTS ix_organization_invitations_email_pendiente")
    op.execute("DROP INDEX IF EXISTS uq_organization_invitations_pendiente")
    op.drop_table("organization_invitations")
