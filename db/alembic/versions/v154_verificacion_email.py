"""v154: verificación del correo en el alta con contraseña.

Revision ID: v154_verificacion_email
Revises: v153_rekey_pscp_id_externo
Create Date: 2026-10-21

RFC 2026-10-21-alta-con-contrasena-tras-concesion. Quien tiene el acceso
concedido se da de alta con correo y contraseña, y la cuenta no entra hasta
que demuestra que controla ese buzón pulsando un enlace.

1. ``users.email_verified_at``: cuándo se demostró el buzón. ``NULL`` es una
   cuenta local recién dada de alta que aún no verificó; el login con
   contraseña la rechaza. **Todas las filas existentes quedan verificadas**
   (``DEFAULT NOW()``): las OAuth las verificó el proveedor y las locales se
   respetan tal cual, para que nadie que hoy entra deje de poder hacerlo por
   esta revisión.
2. ``email_verification_tokens``: la misma forma que ``password_reset_tokens``
   (v96). Solo se persiste SHA-256(token); el valor bruto existe únicamente en
   el correo. Cada token es de un uso y caduca a las 24 horas.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v154_verificacion_email"
down_revision: str | Sequence[str] | None = "v153_rekey_pscp_id_externo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLA = "email_verification_tokens"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _protect_table(table: str) -> None:
    """La misma protección que v96 da a ``password_reset_tokens``."""
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
    # `DEFAULT NOW()` hace dos cosas: rellena las filas existentes (Postgres
    # evalúa el default al añadir la columna) y deja verificada cualquier
    # cuenta creada por un camino que no sabe de esta columna (OAuth, alta
    # abierta, scripts de operación). La única que nace sin verificar es la del
    # alta cerrada, que escribe `NULL` explícitamente
    # (`db/email_verification.py`).
    op.add_column(
        "users",
        sa.Column(
            "email_verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("NOW()"),
        ),
    )

    # El nombre literal, no `_TABLA`: `tests/test_tablas_citadas_existen.py`
    # lee de las migraciones qué tablas existen, y solo ve literales.
    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text, nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_email_verification_tokens_user_pending",
        _TABLA,
        ["user_id", "expires_at"],
        postgresql_where=sa.text("used_at IS NULL"),
    )
    _protect_table(_TABLA)


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_index("ix_email_verification_tokens_user_pending", table_name=_TABLA)
    op.drop_table(_TABLA)
    op.drop_column("users", "email_verified_at")
