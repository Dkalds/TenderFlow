"""Add TOTP secrets, recovery codes and server-side sessions (G1, G2)

Revision ID: v17_totp_sessions
Revises: v16_model_registry
Create Date: 2026-05-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v17_totp_sessions"
down_revision: str | Sequence[str] | None = "v16_model_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "totp_secrets",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False, unique=True),
        sa.Column("secret", sa.Text, nullable=False),
        sa.Column("confirmed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("idx_totp_user", "totp_secrets", ["user_id"])

    op.create_table(
        "totp_recovery_codes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("code_hash", sa.Text, nullable=False),
        sa.Column("used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("used_at", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("idx_recovery_user", "totp_recovery_codes", ["user_id"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("token_hash", sa.Text, nullable=False, unique=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("expires_at", sa.Text, nullable=False),
        sa.Column("ip", sa.Text, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("revoked", sa.Integer, nullable=False, server_default="0"),
        sa.Column("revoked_at", sa.Text, nullable=True),
    )
    op.create_index("idx_sessions_user", "sessions", ["user_id"])
    op.create_index("idx_sessions_token", "sessions", ["token_hash"])
    op.create_index("idx_sessions_expires", "sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("idx_sessions_expires", "sessions")
    op.drop_index("idx_sessions_token", "sessions")
    op.drop_index("idx_sessions_user", "sessions")
    op.drop_table("sessions")
    op.drop_index("idx_recovery_user", "totp_recovery_codes")
    op.drop_table("totp_recovery_codes")
    op.drop_index("idx_totp_user", "totp_secrets")
    op.drop_table("totp_secrets")
