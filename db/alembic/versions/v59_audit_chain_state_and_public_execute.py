"""v59: ancla firmada de auditoría y cierre de EXECUTE público.

Revision ID: v59_audit_chain_state_and_public_execute
Revises: v58_security_identity_hardening
Create Date: 2026-07-26
"""

from __future__ import annotations

from alembic import op

revision: str = "v59_audit_chain_state_and_public_execute"
down_revision: str | None = "v58_security_identity_hardening"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    # Alembic's historical version table was created with VARCHAR(32), while
    # current revision identifiers intentionally carry a descriptive suffix.
    # Widen it before Alembic writes this revision at the end of the upgrade.
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")
    op.execute(
        "CREATE TABLE IF NOT EXISTS audit_chain_state ("
        "chain_name TEXT PRIMARY KEY, "
        "head_hash TEXT NOT NULL, "
        "entry_count BIGINT NOT NULL, "
        "state_hmac TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)"
    )
    # PostgreSQL grants EXECUTE on new functions to PUBLIC by default. The
    # Supabase RLS event-trigger helper is SECURITY DEFINER, so that default
    # grant would make it a privilege-escalation primitive.
    op.execute(
        "DO $$ BEGIN "
        "IF to_regprocedure('public.rls_auto_enable()') IS NOT NULL THEN "
        "REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM PUBLIC; "
        "END IF; END $$"
    )
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC")
    # Earlier webhook idempotency rows contained the signing secret in
    # response_json. It is never needed to deduplicate a request; remove it
    # while preserving non-sensitive response metadata for diagnostics.
    op.execute(
        "DO $$ BEGIN "
        "BEGIN "
        "UPDATE idempotency_keys "
        "SET response_json = (response_json::jsonb - 'secret')::text "
        "WHERE endpoint = 'webhook.create' AND response_json::jsonb ? 'secret'; "
        "EXCEPTION WHEN invalid_text_representation THEN "
        "RAISE NOTICE 'Skipping malformed idempotency response during secret scrub'; "
        "END; END $$"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP TABLE IF EXISTS audit_chain_state")
