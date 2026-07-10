"""add ml_feedback table for human-in-the-loop classifier improvement

Crea la tabla ``ml_feedback`` para almacenar las señales de relevancia
enviadas por los usuarios desde el dashboard o la API.

Revision ID: v14_ml_feedback
Revises: baseline002_pg_core_genesis
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v14_ml_feedback"
down_revision: str | Sequence[str] | None = "baseline002_pg_core_genesis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ml_feedback",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("expediente", sa.Text, nullable=False),
        sa.Column("relevante", sa.Integer, nullable=False),  # 1=positivo, 0=negativo
        sa.Column("nota", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("idx_ml_feedback_expediente", "ml_feedback", ["expediente"])
    op.create_index("idx_ml_feedback_created_at", "ml_feedback", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_ml_feedback_created_at", "ml_feedback")
    op.drop_index("idx_ml_feedback_expediente", "ml_feedback")
    op.drop_table("ml_feedback")
