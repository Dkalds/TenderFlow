"""Migración v34 — Tabla job_locks para exclusión mutua de jobs (ADR-012).

Lock liviano en SQLite para jobs no idempotentes (retención, retrain,
precompute). ``acquire(name, ttl)`` devuelve False si hay lock vigente,
convirtiendo el job en no-op en vez de carrera.

Cubre el caso de misconfiguración donde ambos planos de orquestación
(GitHub Actions y APScheduler) corren contra la misma BD.

Revision ID: v34_job_locks
Revises: v33_users_password_hash
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v34_job_locks"
down_revision: str | Sequence[str] | None = "v33_users_password_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_locks",
        sa.Column("name", sa.Text, primary_key=True),
        sa.Column("acquired_at", sa.Text, nullable=False),
        sa.Column("expires_at", sa.Text, nullable=False),
        sa.Column("holder", sa.Text, nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("job_locks")
