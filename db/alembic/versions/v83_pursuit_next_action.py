"""v83: ``next_action`` y ``next_action_due`` en ``pursuits``.

Revision ID: v83_pursuit_next_action
Revises: v82_lic_history_id_externo_index
Create Date: 2026-08-13

La agenda de Mi Pipeline ordena los compromisos por reloj, y un pursuit sin
próxima acción definida es un pursuit abandonado en silencio: nadie sabe qué
toca hacer ni cuándo. Estas dos columnas son el mínimo que hace medible ese
abandono (KPI "sin próxima acción") y le da al pursuit una fecha propia que
puede vencer antes que el deadline del expediente.

``next_action_due`` es TEXT ``YYYY-MM-DD`` y no DATE por coherencia con el
resto de la tabla (v61 guarda todos los timestamps como TEXT ISO; ADR-016/021:
las fechas viajan como texto entre repositorio y DTO). El servicio serializa
``date.isoformat()`` antes de escribir.

Ambas columnas son NULL-ables sin default: ``ADD COLUMN`` puro de metadatos,
sin reescritura de tabla ni lock prolongado (la lección de v68 no aplica aquí,
pero se deja dicho por qué: no hay columna generada ni backfill).

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v83_pursuit_next_action"
down_revision: str | Sequence[str] | None = "v82_lic_history_id_externo_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.add_column("pursuits", sa.Column("next_action", sa.Text, nullable=True))
    op.add_column("pursuits", sa.Column("next_action_due", sa.Text, nullable=True))


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_column("pursuits", "next_action_due")
    op.drop_column("pursuits", "next_action")
