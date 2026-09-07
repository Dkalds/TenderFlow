"""v104: ``outcome_reason_code`` en ``pursuits`` (motivos de pérdida de D37).

Revision ID: v104_pursuit_outcome_reason_code
Revises: v103_radar_dismissals_hasta
Create Date: 2026-09-06

F3.1 del plan de funcionalidades 2026-09, con la decisión D37 cerrada: lista
**cerrada** de motivos (``precio``, ``tecnica``, ``solvencia``, ``plazo``,
``desierto_o_anulado``, ``no_presentada``, ``otro``).

Por qué una columna nueva y no reutilizar ``outcome_reason``
------------------------------------------------------------
``outcome_reason`` es texto libre de hasta 4.000 caracteres y seguirá
siéndolo: el matiz («nos ganaron por 3 puntos en la memoria técnica») es
valioso y no cabe en un enumerado. Lo que no se puede hacer con él es
**agregar**: «perdemos por precio en el 60 % de los casos en CPV 72» exige un
código, y derivarlo del texto a posteriori es exactamente la clase de
adivinanza que ADR-014 prohíbe. Las dos columnas conviven: código para contar,
texto para entender.

Backfill: **ninguno**. Los cierres existentes quedan con la columna a NULL,
que el dominio lee como ``sin_codificar`` y la UI ofrece completar. Rellenarlos
con ``otro`` los haría indistinguibles de los que alguien clasificó
deliberadamente como «otro», y contaminaría la primera analítica que se mire.

Sin CHECK en la tabla
---------------------
La lista la valida el DTO (``PursuitOutcomeReasonCode``), no un CHECK, por el
mismo motivo que ``estado`` y ``tipo_contrato`` son TEXT libre en
``licitaciones``: un CHECK convierte añadir un motivo en una migración con
lock, y D37 dice que la lista puede revisarse cuando el histórico enseñe un
motivo que falta. La coherencia la garantiza la API, que es por donde pasa
toda escritura de ``pursuits``.

Índice parcial sobre las filas que lo tienen: la consulta caliente es
«pérdidas por motivo de esta organización», y las filas sin código —todas las
antiguas y todas las ganadas— no participan.

Columna nullable y sin default: ``ADD COLUMN`` metadata-only, sin reescritura
(mismo patrón que v83, v85 y v103).

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v104_pursuit_outcome_reason_code"
down_revision: str | Sequence[str] | None = "v103_radar_dismissals_hasta"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.add_column("pursuits", sa.Column("outcome_reason_code", sa.Text, nullable=True))
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pursuits_outcome_reason_code "
        "ON pursuits (organization_id, outcome_reason_code) "
        "WHERE outcome_reason_code IS NOT NULL"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP INDEX IF EXISTS idx_pursuits_outcome_reason_code")
    op.drop_column("pursuits", "outcome_reason_code")
