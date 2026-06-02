"""Migración v30 — Clasificación multi-tecnología (multilabel).

Crea la tabla ``licitacion_tecnologia_score`` para almacenar las
probabilidades por tecnología de cada licitación, y añade columnas
a ``licitaciones`` para el modelo multilabel.

La tabla ``licitacion_tecnologia_score`` reemplaza funcionalmente la
columna única ``tecnologia`` por un conjunto de etiquetas con scores.

Columnas nuevas en licitaciones:
- ``ml_tecnologias`` — CSV de etiquetas predichas ordenadas por prob.
- ``ml_proba_max`` — Probabilidad máxima entre todas las tecnologías.
- ``ml_tech_principal`` — Etiqueta con mayor probabilidad (routing).

Revision ID: v30_ml_tecnologias_multilabel
Revises: v29_mat_aggregates
Create Date: 2026-06-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v30_ml_tecnologias_multilabel"
down_revision: str | Sequence[str] | None = "v29_mat_aggregates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS licitacion_tecnologia_score (
            licitacion_id      TEXT NOT NULL,
            tecnologia         TEXT NOT NULL,
            probabilidad       REAL NOT NULL,
            threshold_aplicado REAL NOT NULL,
            computed_at        TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (licitacion_id, tecnologia),
            FOREIGN KEY (licitacion_id) REFERENCES licitaciones(id_externo) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_lts_tecnologia "
        "ON licitacion_tecnologia_score(tecnologia, probabilidad DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_lts_lic "
        "ON licitacion_tecnologia_score(licitacion_id)"
    )
    for col, coltype in [
        ("ml_tecnologias", "TEXT"),
        ("ml_proba_max", "REAL"),
        ("ml_tech_principal", "TEXT"),
    ]:
        try:
            op.add_column("licitaciones", sa.Column(col, sa.Text() if coltype == "TEXT" else sa.Float(), nullable=True))
        except Exception:
            pass
    try:
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_ml_tech_principal "
            "ON licitaciones(ml_tech_principal)"
        )
    except Exception:
        pass


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ml_tech_principal")
    # SQLite < 3.35 no soporta DROP COLUMN; omitimos rollback de columnas.
    op.execute("DROP INDEX IF EXISTS idx_lts_lic")
    op.execute("DROP INDEX IF EXISTS idx_lts_tecnologia")
    op.execute("DROP TABLE IF EXISTS licitacion_tecnologia_score")
