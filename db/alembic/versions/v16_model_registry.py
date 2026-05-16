"""add model_versions registry for ML lifecycle tracking (C2)

Revision ID: v16_model_registry
Revises: v15_webhooks
Create Date: 2026-05-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v16_model_registry"
down_revision: str | Sequence[str] | None = "v15_webhooks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),  # e.g. "sap_classifier"
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("metrics_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("trained_at", sa.Text, nullable=False),
        sa.Column("trained_on_n_samples", sa.Integer, nullable=True),
        sa.Column("trained_on_n_feedbacks", sa.Integer, nullable=True),
        sa.Column("is_active", sa.Integer, nullable=False, server_default="0"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.UniqueConstraint("name", "version", name="uq_model_name_version"),
    )
    op.create_index(
        "idx_model_versions_active",
        "model_versions",
        ["name", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("idx_model_versions_active", "model_versions")
    op.drop_table("model_versions")
