"""v141: ``tasas_anulacion_organo`` — riesgo de anulación o desierto (F1.4).

Revision ID: v141_tasas_anulacion_organo
Revises: v138_notice_type_code
Create Date: 2026-09-19

Qué falta hoy
-------------
El scoring tenía redactada la frase de ``organo_anula_frecuente``
(``services/analytics/scoring_explicacion.py``) y el cliente su etiqueta, pero
nada emitía el flag: no había dónde leer la tasa. Calcularla en cada petición
del Radar sería agregar veinticuatro meses de ``licitaciones`` por órgano en
cada carga; se precalcula una vez por pasada (``aggregates_precompute``) y el
scoring la lee por clave.

Forma, y por qué
----------------
Una fila por ``(organo_key, cpv4)``, con ``cpv4 = '*'`` para el total del
órgano. ``organo_key`` es el nombre plegado (``lower(btrim(...))``): el maestro
de órganos (C1.2) todavía no cubre todo el corpus, y la clave de texto es la
que el scoring tiene en cada fila. Se guardan **los conteos**, no solo la tasa:
el mínimo de muestra (diez expedientes, D39/F1.4) lo aplica quien lee, y con la
tasa sola un 50 % de dos expedientes sería indistinguible de uno de doscientos.

Tabla de reemplazo completo por pasada, sin histórico: es un derivado que se
recalcula entero en segundos, y el histórico ya está en ``licitaciones``.
Sin ``organization_id``: es dato de mercado, igual para todos.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v141_tasas_anulacion_organo"
down_revision: str | Sequence[str] | None = "v138_notice_type_code"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.create_table(
        "tasas_anulacion_organo",
        sa.Column("organo_key", sa.Text, nullable=False),
        # Cuatro primeros dígitos del CPV, o '*' para el total del órgano.
        sa.Column("cpv4", sa.Text, nullable=False),
        sa.Column("n_expedientes", sa.Integer, nullable=False),
        sa.Column("n_fallidos", sa.Integer, nullable=False),
        sa.Column("tasa", sa.Float, nullable=False),
        # Primer día de la ventana (ISO). Dice sobre qué periodo se contó.
        sa.Column("desde", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("organo_key", "cpv4", name="pk_tasas_anulacion_organo"),
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_table("tasas_anulacion_organo")
