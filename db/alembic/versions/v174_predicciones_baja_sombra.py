"""v174: ``predicciones_baja_sombra``, el candidato puntuado sin enseñarlo.

Ninguna versión de ``baja_model`` se ha activado: el gate decide con métricas
de validación sobre el pasado, y la calibración servida
(``services.ml.calibration``) solo mide lo que ya se enseña. El modo sombra
cierra ese hueco: el batch puntúa además la última versión registrada que no
está activa y la guarda aquí. Cuando esas licitaciones se adjudican, el par
predicción↔realidad del **candidato** existe antes de activarlo.

Solo la granularidad agregada (una fila por expediente y versión): es la que se
sirve. La clave incluye ``model_version`` para que dos candidatos sucesivos no
se pisen; el escritor borra las filas de versiones que ya no son candidatas
(``PrediccionesRepository.guardar_baja_sombra``).

``licitacion_id`` con ``ON DELETE CASCADE``, como ``predicciones_baja``: una
predicción sin licitación no tiene par que medir. La PK empieza por
``licitacion_id`` y sirve también al JOIN de la calibración.

RLS
---
Dato derivado, sin ``organization_id``: nace cerrada a ``anon``/
``authenticated`` y abierta a ``tenderflow_app``, como ``v170``.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v174_predicciones_baja_sombra
Revises: v173_predicciones_baja_prob_sin_baja
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v174_predicciones_baja_sombra"
down_revision: str | Sequence[str] | None = "v173_predicciones_baja_prob_sin_baja"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLA = "predicciones_baja_sombra"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.create_table(
        "predicciones_baja_sombra",
        sa.Column(
            "licitacion_id",
            sa.Text,
            sa.ForeignKey("licitaciones.id_externo", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_version", sa.Integer, nullable=False),
        sa.Column("p10", sa.Float, nullable=False),
        sa.Column("p50", sa.Float, nullable=False),
        sa.Column("p90", sa.Float, nullable=False),
        sa.Column("prob_sin_baja", sa.Float, nullable=True),
        sa.Column("computed_at", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("licitacion_id", "model_version", name="pk_pred_baja_sombra"),
    )
    op.execute(f"ALTER TABLE {_TABLA} ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN "
        f"REVOKE ALL ON TABLE {_TABLA} FROM anon; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN "
        f"REVOKE ALL ON TABLE {_TABLA} FROM authenticated; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_app') THEN "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {_TABLA} TO tenderflow_app; "
        "IF NOT EXISTS (SELECT 1 FROM pg_policies "
        f"WHERE schemaname = current_schema() AND tablename = '{_TABLA}' "
        "AND policyname = 'tenderflow_app_full_access') THEN "
        f"CREATE POLICY tenderflow_app_full_access ON {_TABLA} "
        "FOR ALL TO tenderflow_app USING (true) WITH CHECK (true); "
        "END IF; END IF; END $$"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_table(_TABLA)
