"""Migracion v50 -- infraestructura de búsqueda Postgres (pg_trgm + search_vector).

Esta migración es DIALECT-GUARDED: solo hace algo en Postgres.
En SQLite es un no-op seguro (los bloques están protegidos por is_postgres).

Cambios en Postgres:
  1. Habilita la extensión pg_trgm (búsqueda por similitud LIKE eficiente).
  2. Añade columna generada ``search_vector tsvector`` en ``licitaciones``,
     calculada como la concatenación ponderada de titulo + descripcion + cpv
     con configuración 'spanish'. Al ser GENERATED ALWAYS STORED, no
     requiere triggers ni mantenimiento manual.
  3. Crea índice GIN sobre ``search_vector`` para búsquedas @@ eficientes.

Orden de aplicación:
  - F3a: Esta migración se crea pero no se aplica en producción hasta F3c.
  - En dev: `alembic upgrade head` sobre el Postgres local la aplica.
  - En CI: el job integration-pg la aplica contra postgres:17.

Revision ID: v50_pg_search_infra
Revises: v49_user_profiles
Create Date: 2026-07-05
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v50_pg_search_infra"
down_revision: str | None = "v49_user_profiles"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    """True si la migración se está ejecutando contra Postgres."""
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return  # no-op en SQLite

    # 1. Extensión pg_trgm (necesaria para similitud ILIKE eficiente)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # 2. Columna generada search_vector
    # La expresión concatena titulo (peso A), descripcion (peso B) y cpv (peso C).
    # GENERATED ALWAYS AS ... STORED: se mantiene automáticamente en INSERT/UPDATE.
    op.execute(
        """
        ALTER TABLE licitaciones
        ADD COLUMN IF NOT EXISTS search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('spanish', coalesce(titulo, '')), 'A') ||
            setweight(to_tsvector('spanish', coalesce(descripcion, '')), 'B') ||
            setweight(to_tsvector('simple', coalesce(cpv, '')), 'C')
        ) STORED
        """
    )

    # 3. Índice GIN sobre search_vector
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_licitaciones_search_vector "
        "ON licitaciones USING GIN (search_vector)"
    )

    # 4. Índice pg_trgm para ILIKE fallback (útil en búsquedas parciales)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_licitaciones_titulo_trgm "
        "ON licitaciones USING GIN (titulo gin_trgm_ops)"
    )


def downgrade() -> None:
    if not _is_postgres():
        return  # no-op en SQLite

    op.execute("DROP INDEX IF EXISTS idx_licitaciones_titulo_trgm")
    op.execute("DROP INDEX IF EXISTS idx_licitaciones_search_vector")
    op.execute("ALTER TABLE licitaciones DROP COLUMN IF EXISTS search_vector")
    # No dropeamos pg_trgm: puede estar usada por otros índices.
