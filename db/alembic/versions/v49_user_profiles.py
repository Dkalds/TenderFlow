"""Migracion v49 -- tabla user_profiles (scoring personalizado por usuario).

Cada fila es el perfil de un usuario (keyed por user_key).
Los campos JSON son TEXT con contenido JSON valido (validado en la capa de servicio).

Campos:
  - weights_json           : dict {importe, plazo, competencia, margen, afinidad} suman 100
  - afinidad_keywords_json : list[str] de keywords de afinidad
  - cpvs_json              : list[str] de prefijos CPV de interes
  - ccaa_json              : list[str] de CCAA de interes
  - importe_min / max      : rango de importe ejecutable (penalizacion fuera de rango)

Revision ID: v49_user_profiles
Revises: v48_user_notifications
Create Date: 2026-07-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v49_user_profiles"
down_revision: str | Sequence[str] | None = "v48_user_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_key              TEXT PRIMARY KEY,
            weights_json          TEXT,
            afinidad_keywords_json TEXT,
            cpvs_json             TEXT,
            ccaa_json             TEXT,
            importe_min           REAL,
            importe_max           REAL,
            updated_at            TEXT NOT NULL DEFAULT (datetime('now','utc'))
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_profiles")
