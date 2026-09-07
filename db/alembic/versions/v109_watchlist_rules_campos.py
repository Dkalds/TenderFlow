"""v109: las reglas de watchlist dejan de ser keyword + CPV + importe + CCAA.

Plan de arquitectura 2026-09 v2, S4.4. Una regla podía decir «SAP en Madrid por
encima de 100.000 €» pero no «SAP, procedimiento abierto, del Ayuntamiento de
X, con al menos 20 días de plazo». Seis columnas aditivas:

- ``tecnologia``: la etiqueta del clasificador, que ya vive en
  ``licitaciones.tecnologia``.
- ``organo`` **y** ``organo_norm``: el usuario escribe el órgano como lo ve, y
  el matching compara la forma plegada de ``services/dedupe.normalize_organo``
  (sin acentos, sin formas societarias, en minúsculas). Se guardan las dos: la
  original para volver a pintarla en el formulario, la normalizada para el
  predicado. Normalizar en cada consulta obligaría a aplicar la función sobre
  la columna de la tabla grande, que no puede usar índice.
- ``procedimiento`` y ``tipo_contrato``: persistidos desde ``v85``.
- ``banda_min``: banda comercial mínima del Radar. Su efecto en SQL es acotar
  al **universo puntuable** (abierta + plazo vivo), que es lo que hace que una
  banda signifique algo; el ranking lo pone el mismo scorer del Radar.
- ``plazo_min_dias``: días que quedan hasta ``fecha_limite``. Una regla para
  quien no puede preparar una oferta en menos de dos semanas.

Todas nullable: ``NULL`` es «este criterio no filtra», que es exactamente lo
que valen hoy las reglas existentes — por eso no cambian de resultado.

Revision ID: v109_watchlist_rules_campos
Revises: v108_webhooks_organizacion
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v109_watchlist_rules_campos"
down_revision: str | Sequence[str] | None = "v108_webhooks_organizacion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNAS = (
    ("tecnologia", "TEXT"),
    ("organo", "TEXT"),
    ("organo_norm", "TEXT"),
    ("procedimiento", "TEXT"),
    ("tipo_contrato", "TEXT"),
    ("banda_min", "TEXT"),
    ("plazo_min_dias", "INTEGER"),
)


def upgrade() -> None:
    for nombre, tipo in _COLUMNAS:
        op.execute(f"ALTER TABLE watchlist_rules ADD COLUMN IF NOT EXISTS {nombre} {tipo}")


def downgrade() -> None:
    for nombre, _tipo in _COLUMNAS:
        op.execute(f"ALTER TABLE watchlist_rules DROP COLUMN IF EXISTS {nombre}")
