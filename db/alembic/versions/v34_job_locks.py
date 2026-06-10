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

from alembic import op

revision: str = "v34_job_locks"
down_revision: str | Sequence[str] | None = "v33_users_password_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS: db/schema.py (SCHEMA) también crea esta tabla, así que
    # la migración debe poder aplicarse sobre una BD ya inicializada vía
    # init_db() sin colisionar (rompía test_full_roundtrip).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS job_locks (
            name         TEXT PRIMARY KEY,
            acquired_at  TEXT NOT NULL,
            expires_at   TEXT NOT NULL,
            holder       TEXT NOT NULL DEFAULT ''
        )
        """
    )


def downgrade() -> None:
    op.drop_table("job_locks")
