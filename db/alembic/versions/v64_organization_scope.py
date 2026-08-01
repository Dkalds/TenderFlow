"""v64: scope organizativo aditivo para datos de usuario existentes.

Revision ID: v64_organization_scope
Revises: v63_lineage_index_concurrent
Create Date: 2026-07-30

La revisión es Postgres-only, en línea con ADR-021.

Compatibilidad:

* ``organization_id`` permanece nullable para no atribuir filas legacy cuya
  identidad no pueda demostrarse. El login autenticado puede reclamarlas luego
  mediante ``OrganizationRepository.claim_legacy_rows``.
* Las restricciones UNIQUE/PK históricas basadas en ``user_key`` se conservan.
  Por tanto, durante la transición siguen siendo más estrictas que el nuevo
  scope organizativo (por ejemplo, ``user_profiles`` continúa con PK
  ``user_key``). Relajarlas requiere coordinar repositorios y contratos y no
  forma parte de esta migración aditiva.
* Las FK se instalan ``NOT VALID``: protegen escrituras nuevas sin escanear ni
  bloquear las tablas existentes. Una revisión posterior puede validarlas.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "v64_organization_scope"
down_revision: str | None = "v63_lineage_index_concurrent"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_SCOPED_TABLES: dict[str, tuple[bool, bool]] = {
    # table: (has_user_id, has_visibility)
    "watchlist_items": (True, True),
    "watchlist_rules": (True, True),
    "watchlist_empresas": (False, True),
    "watchlist_cpv": (True, True),
    "saved_filters": (False, True),
    "user_profiles": (False, True),
    # Una notificación siempre pertenece a su destinatario; no es compartible.
    "user_notifications": (False, False),
}

# ``NOW()::text`` en Postgres omite los minutos del offset cuando son cero
# (p.ej. "2026-08-01 00:45:48.33444+00"), formato que pydantic rechaza como
# datetime (``datetime_from_date_parsing``). ``_NOW_ISO_TEXT`` reproduce el
# mismo formato que ``db.connection.now_utc_iso()`` (ISO 8601 con offset
# completo) para los INSERT de backfill de esta migración.
_NOW_ISO_TEXT = "to_char(NOW() AT TIME ZONE 'utc', 'YYYY-MM-DD\"T\"HH24:MI:SS.US') || '+00:00'"

_ENSURE_PERSONAL_ORGANIZATIONS = f"""
INSERT INTO organizations
    (name, is_personal, personal_owner_user_id, created_by_user_id,
     created_at, updated_at)
SELECT
    COALESCE(NULLIF(display_name, ''), NULLIF(email, ''), 'Usuario ' || id::text),
    TRUE, id, id, {_NOW_ISO_TEXT}, {_NOW_ISO_TEXT}
FROM users
ON CONFLICT (personal_owner_user_id) DO NOTHING
"""

_ENSURE_PERSONAL_MEMBERSHIPS = f"""
INSERT INTO organization_memberships
    (organization_id, user_id, role, status, created_at, updated_at)
SELECT o.id, o.personal_owner_user_id, 'owner', 'active', {_NOW_ISO_TEXT}, {_NOW_ISO_TEXT}
FROM organizations AS o
WHERE o.is_personal = TRUE AND o.personal_owner_user_id IS NOT NULL
ON CONFLICT (organization_id, user_id) DO NOTHING
"""

_IDENTITY_ROWS_QUERY = sa.text(
    """
    SELECT u.id AS user_id, u.email, o.id AS organization_id, ak.key_hash
    FROM users AS u
    JOIN organizations AS o
      ON o.is_personal = TRUE AND o.personal_owner_user_id = u.id
    LEFT JOIN api_keys AS ak ON ak.user_id = u.id
    ORDER BY u.id, ak.id
    """
)

_CREATE_IDENTITY_SCOPE = """
CREATE TEMPORARY TABLE v64_identity_scope (
    user_key TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    organization_id INTEGER NOT NULL
) ON COMMIT DROP
"""

_INSERT_IDENTITY_SCOPE = sa.text(
    """
    INSERT INTO v64_identity_scope (user_key, user_id, organization_id)
    VALUES (:user_key, :user_id, :organization_id)
    ON CONFLICT (user_key) DO NOTHING
    """
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _stable_user_key(email: str | None, user_id: int) -> str:
    """Replica la derivación de ``shared.identity`` sin importar app code."""
    seed = (email or f"user:{user_id}").strip().lower()
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _identity_keys(
    *,
    user_id: int,
    email: str | None,
    api_key_hash: str | None,
) -> Iterable[str]:
    """Identidades históricas demostrables, ordenadas de más a menos actual."""
    yield _stable_user_key(email, user_id)
    if email and email.strip():
        yield email.strip().lower()
    yield str(user_id)
    if api_key_hash:
        yield api_key_hash
        # Algunos endpoints legacy acortaban el hash de la credencial.
        yield hashlib.sha256(api_key_hash.encode("utf-8")).hexdigest()[:16]


def _mapping_value(row: Mapping[str, Any], key: str) -> Any:
    """Accede a resultados SQLAlchemy y fakes unitarios con la misma ruta."""
    return row[key]


def _seed_identity_scope(bind: Any) -> None:
    """Materializa identidades opacas en una tabla temporal de esta transacción."""
    op.execute(_CREATE_IDENTITY_SCOPE)
    rows = bind.execute(_IDENTITY_ROWS_QUERY).mappings()
    payload: list[dict[str, int | str]] = []
    seen: set[str] = set()
    for row in rows:
        user_id = int(_mapping_value(row, "user_id"))
        organization_id = int(_mapping_value(row, "organization_id"))
        raw_email = _mapping_value(row, "email")
        raw_key_hash = _mapping_value(row, "key_hash")
        email = str(raw_email) if raw_email is not None else None
        key_hash = str(raw_key_hash) if raw_key_hash is not None else None
        for user_key in _identity_keys(
            user_id=user_id,
            email=email,
            api_key_hash=key_hash,
        ):
            if user_key in seen:
                continue
            seen.add(user_key)
            payload.append(
                {
                    "user_key": user_key,
                    "user_id": user_id,
                    "organization_id": organization_id,
                }
            )
    if payload:
        bind.execute(_INSERT_IDENTITY_SCOPE, payload)


def _add_scope_columns(table: str, *, has_visibility: bool) -> None:
    op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS organization_id INTEGER")
    fk_name = f"fk_{table}_organization_id"
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        f"WHERE conname = '{fk_name}' AND conrelid = '{table}'::regclass) THEN "
        f"ALTER TABLE {table} ADD CONSTRAINT {fk_name} "
        "FOREIGN KEY (organization_id) REFERENCES organizations(id) "
        "ON DELETE CASCADE NOT VALID; "
        "END IF; END $$"
    )
    if not has_visibility:
        return
    op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS visibility TEXT")
    op.execute(
        f"UPDATE {table} SET visibility = 'private' "
        "WHERE visibility IS NULL "
        "OR visibility NOT IN ('private', 'organization')"
    )
    check_name = f"ck_{table}_visibility"
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
        f"WHERE conname = '{check_name}' AND conrelid = '{table}'::regclass) THEN "
        f"ALTER TABLE {table} ADD CONSTRAINT {check_name} "
        "CHECK (visibility IS NOT NULL "
        "AND visibility IN ('private', 'organization')) NOT VALID; "
        "END IF; END $$"
    )
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {check_name}")
    op.execute(f"ALTER TABLE {table} ALTER COLUMN visibility SET DEFAULT 'private'")
    op.execute(f"ALTER TABLE {table} ALTER COLUMN visibility SET NOT NULL")


def _backfill_scope(table: str, *, has_user_id: bool) -> None:
    if has_user_id:
        op.execute(
            f"UPDATE {table} AS target SET organization_id = personal.id "
            "FROM organizations AS personal "
            "WHERE target.organization_id IS NULL "
            "AND target.user_id IS NOT NULL "
            "AND personal.is_personal = TRUE "
            "AND personal.personal_owner_user_id = target.user_id"
        )
    op.execute(
        f"UPDATE {table} AS target SET organization_id = identity.organization_id "
        "FROM v64_identity_scope AS identity "
        "WHERE target.organization_id IS NULL "
        "AND target.user_key = identity.user_key"
    )


def _protect_table(table: str) -> None:
    """RLS fail-closed para Data API y acceso explícito del rol runtime."""
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
        "IF NOT EXISTS (SELECT 1 FROM pg_policies "
        f"WHERE schemaname = 'public' AND tablename = '{table}' "
        "AND policyname = 'tenderflow_app_full_access') THEN "
        f"CREATE POLICY tenderflow_app_full_access ON {table} "
        "FOR ALL TO tenderflow_app USING (true) WITH CHECK (true); "
        "END IF; END IF; END $$"
    )


def upgrade() -> None:
    if not _is_postgres():
        return

    op.execute(_ENSURE_PERSONAL_ORGANIZATIONS)
    op.execute(_ENSURE_PERSONAL_MEMBERSHIPS)
    for table, (_, has_visibility) in _SCOPED_TABLES.items():
        _add_scope_columns(table, has_visibility=has_visibility)

    bind = op.get_bind()
    _seed_identity_scope(bind)
    for table, (has_user_id, _) in _SCOPED_TABLES.items():
        _backfill_scope(table, has_user_id=has_user_id)
        _protect_table(table)

    # Los índices recorren tablas existentes: siempre concurrentes y al final.
    # Todo lo anterior es idempotente, por lo que un fallo concurrente se puede
    # reintentar aunque ``autocommit_block`` haya confirmado el DDL previo.
    with op.get_context().autocommit_block():
        for table in _SCOPED_TABLES:
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                f"idx_{table}_organization ON {table} (organization_id)"
            )


def downgrade() -> None:
    if not _is_postgres():
        return

    with op.get_context().autocommit_block():
        for table in reversed(_SCOPED_TABLES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS idx_{table}_organization")

    for table, (_, has_visibility) in reversed(_SCOPED_TABLES.items()):
        op.execute(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_app') THEN "
            f"DROP POLICY IF EXISTS tenderflow_app_full_access ON {table}; "
            f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE {table} "
            "FROM tenderflow_app; "
            "END IF; END $$"
        )
        if has_visibility:
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS visibility")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS organization_id")
