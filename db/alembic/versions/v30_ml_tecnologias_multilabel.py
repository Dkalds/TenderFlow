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
from alembic import context, op

revision: str = "v30_ml_tecnologias_multilabel"
down_revision: str | Sequence[str] | None = "v29_mat_aggregates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_COLUMNS = [
    ("ml_tecnologias", "TEXT"),
    ("ml_proba_max", "REAL"),
    ("ml_tech_principal", "TEXT"),
]


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    # datetime('now') es sintaxis SQLite; Postgres no tiene esa función.
    computed_at_default = "NOW()" if is_postgres else "datetime('now')"

    # En modo offline (--sql) no hay conexión real que introspeccionar;
    # emitir el DDL directamente (mismo criterio que v35/v37).
    if context.is_offline_mode():
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS licitacion_tecnologia_score (
                licitacion_id      TEXT NOT NULL,
                tecnologia         TEXT NOT NULL,
                probabilidad       REAL NOT NULL,
                threshold_aplicado REAL NOT NULL,
                computed_at        TEXT NOT NULL DEFAULT ({computed_at_default}),
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
            "CREATE INDEX IF NOT EXISTS idx_lts_lic ON licitacion_tecnologia_score(licitacion_id)"
        )
        for col, coltype in _COLUMNS:
            op.add_column(
                "licitaciones",
                sa.Column(col, sa.Text() if coltype == "TEXT" else sa.Float(), nullable=True),
            )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_ml_tech_principal ON licitaciones(ml_tech_principal)"
        )
        return

    insp = sa.inspect(op.get_bind())
    if "licitacion_tecnologia_score" not in insp.get_table_names():
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS licitacion_tecnologia_score (
                licitacion_id      TEXT NOT NULL,
                tecnologia         TEXT NOT NULL,
                probabilidad       REAL NOT NULL,
                threshold_aplicado REAL NOT NULL,
                computed_at        TEXT NOT NULL DEFAULT ({computed_at_default}),
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
            "CREATE INDEX IF NOT EXISTS idx_lts_lic ON licitacion_tecnologia_score(licitacion_id)"
        )

    # No usar try/except: en Postgres un ADD COLUMN fallido deja la
    # transacción abortada para el resto de la migración.
    lic_cols = {c["name"] for c in insp.get_columns("licitaciones")}
    for col, coltype in _COLUMNS:
        if col not in lic_cols:
            op.add_column(
                "licitaciones",
                sa.Column(col, sa.Text() if coltype == "TEXT" else sa.Float(), nullable=True),
            )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ml_tech_principal ON licitaciones(ml_tech_principal)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ml_tech_principal")
    # SQLite < 3.35 no soporta DROP COLUMN; omitimos rollback de columnas.
    op.execute("DROP INDEX IF EXISTS idx_lts_lic")
    op.execute("DROP INDEX IF EXISTS idx_lts_tecnologia")
    op.execute("DROP TABLE IF EXISTS licitacion_tecnologia_score")
