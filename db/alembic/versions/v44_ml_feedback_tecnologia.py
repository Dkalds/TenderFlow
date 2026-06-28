"""Migración v44 — ml_feedback: columnas tecnologia, tecnologias_secundarias, model_version.

Añade soporte para etiquetado multi-tecnología en el bucle de Active Learning:
- ``tecnologia`` (TEXT): tecnología principal seleccionada por el etiquetador.
- ``tecnologias_secundarias`` (TEXT): JSON array de tecnologías secundarias.
- ``model_version`` (INTEGER): referencia suave a la versión del modelo activo
  al momento del etiquetado.

Idempotente: usa try/except para ALTER TABLE ADD COLUMN (SQLite no soporta
IF NOT EXISTS en ALTER TABLE). IF NOT EXISTS en el índice.

Revision ID: v44_ml_feedback_tecnologia
Revises: v43_watchlist_rules
Create Date: 2026-06-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v44_ml_feedback_tecnologia"
down_revision: str | Sequence[str] | None = "v43_watchlist_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from observability.logging import get_logger

    log = get_logger(__name__)

    for stmt in (
        "ALTER TABLE ml_feedback ADD COLUMN tecnologia TEXT",
        "ALTER TABLE ml_feedback ADD COLUMN tecnologias_secundarias TEXT",
        "ALTER TABLE ml_feedback ADD COLUMN model_version INTEGER",
    ):
        try:
            op.execute(stmt)
        except Exception:
            log.warning("migration_step_error", version=44, stmt=stmt[:60], exc_info=True)

    try:
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_ml_feedback_tecnologia ON ml_feedback(tecnologia)"
        )
    except Exception:
        log.warning(
            "migration_step_error",
            version=44,
            operation="idx_ml_feedback_tecnologia",
            exc_info=True,
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ml_feedback_tecnologia")
