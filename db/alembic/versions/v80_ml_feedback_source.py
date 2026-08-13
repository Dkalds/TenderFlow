"""Migración v80 — ml_feedback.source: distingue etiqueta humana de automática.

Hasta ahora toda fila de ``ml_feedback`` era, por construcción, una etiqueta
puesta por una persona en la cola de active learning, y el entrenamiento del
``SAPClassifier`` la aplica como override duro sobre la etiqueta de keywords
(``scheduler/concept_drift.py`` y su copia en ``scraper/ml_training.py``).

El etiquetado batch por LLM rompe esa premisa: si sus etiquetas entran en la
misma tabla sin distintivo, el modelo se entrena con sus propias predicciones
—un lazo de realimentación que confirma sus errores en vez de corregirlos— y
el contador que decide cuándo reentrenar
(``db/model_registry.feedbacks_since_last_train``) se dispara con miles de
filas que no aportan una sola etiqueta nueva.

``source`` es ese distintivo. ``DEFAULT 'human'`` deja el histórico entero
marcado como humano, que es lo que era, y mantiene compatible a cualquier
``INSERT`` que no nombre la columna.

Barata pese al ``NOT NULL``: en Postgres 11+ un ``ADD COLUMN`` con default
constante es una operación de catálogo, sin reescritura de tabla (y
``ml_feedback`` es pequeña de todos modos, a diferencia de ``licitaciones``).

El índice es **parcial sobre las filas humanas**, no sobre las automáticas:
las dos consultas que filtran por esta columna piden ``source = 'human'``, y
tras el primer lote del job las humanas son la minoría de la tabla. Un índice
parcial por el lado que se consulta es el pequeño *y* el que el planner puede
usar.

Revision ID: v80_ml_feedback_source
Revises: v79_perf_hot_paths_indexes
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v80_ml_feedback_source"
down_revision: str | Sequence[str] | None = "v79_perf_hot_paths_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from observability.logging import get_logger

    log = get_logger(__name__)

    # try/except por el mismo motivo que v44: ALTER TABLE ADD COLUMN no admite
    # IF NOT EXISTS en todos los dialectos, y la migración debe poder re-correr
    # sobre una base que ya la tenga aplicada a medias.
    try:
        op.execute("ALTER TABLE ml_feedback ADD COLUMN source TEXT NOT NULL DEFAULT 'human'")
    except Exception:
        log.warning("migration_step_error", version=80, operation="add_source", exc_info=True)

    try:
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_ml_feedback_source_human "
            "ON ml_feedback(created_at) WHERE source = 'human'"
        )
    except Exception:
        log.warning(
            "migration_step_error",
            version=80,
            operation="idx_ml_feedback_source_human",
            exc_info=True,
        )


def downgrade() -> None:
    # Solo el índice, como v44: la columna tiene default, así que el código
    # anterior (que no la nombra) sigue insertando sin problema, y tirarla
    # perdería la distinción humano/automático de las filas ya escritas.
    op.execute("DROP INDEX IF EXISTS idx_ml_feedback_source_human")
