"""v58: identidad vinculada, sesiones revocables y feedback atribuible.

Revision ID: v58_security_identity_hardening
Revises: v58_drop_mat_top_empresas_ccaa
Create Date: 2026-07-26
"""

from __future__ import annotations

from alembic import op

revision: str = "v58_security_identity_hardening"
down_revision: str | None = "v58_drop_mat_top_empresas_ccaa"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_seen_at TEXT")
    op.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS mfa_verified_at TEXT")
    op.execute("UPDATE sessions SET last_seen_at = created_at WHERE last_seen_at IS NULL")
    op.execute("ALTER TABLE ml_feedback ADD COLUMN IF NOT EXISTS user_id INTEGER")
    op.execute("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS hash_version TEXT")
    op.execute("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS user_id INTEGER")
    op.execute("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS scopes TEXT NOT NULL DEFAULT '*'")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ml_feedback_user_id ON ml_feedback(user_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id)")
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        "WHERE conname = 'api_keys_user_id_fkey' "
        "AND conrelid = 'api_keys'::regclass) THEN "
        "ALTER TABLE api_keys ADD CONSTRAINT api_keys_user_id_fkey "
        "FOREIGN KEY (user_id) REFERENCES users(id) NOT VALID; "
        "END IF; END $$"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS api_keys_user_id_fkey")
    op.execute("DROP INDEX IF EXISTS idx_api_keys_user_id")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS scopes")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS user_id")
    op.execute("DROP INDEX IF EXISTS idx_ml_feedback_user_id")
    op.execute("ALTER TABLE audit_log DROP COLUMN IF EXISTS hash_version")
    op.execute("ALTER TABLE ml_feedback DROP COLUMN IF EXISTS user_id")
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS mfa_verified_at")
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS last_seen_at")
