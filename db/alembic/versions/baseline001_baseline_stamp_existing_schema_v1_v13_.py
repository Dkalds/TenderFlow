"""baseline: stamp existing schema v1-v13 from custom migrations

Esta es la revisión baseline que marca el schema existente (gestionado por
db/migrations.py versiones 1-13) como punto de partida para Alembic.

No ejecuta ningún SQL — asume que el sistema casero ya aplicó todas las
migraciones hasta v13. Para bases de datos nuevas, ejecutar primero
``db.migrations.apply_pending()`` antes de ``alembic stamp head``.

Revision ID: baseline001
Revises:
Create Date: 2026-05-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa  # noqa: F401
from alembic import op  # noqa: F401

revision: str = "baseline001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: schema ya existe vía db/migrations.py v1-v13."""


def downgrade() -> None:
    """No-op: no se puede revertir el baseline."""
    raise RuntimeError("No se puede revertir el baseline. Restaura desde backup.")
