"""Migración v20 — Tablas materializadas para agregados pre-calculados.

Crea dos tablas de staging para resultados pre-computados por el scheduler:

* ``mat_clusters``          — asignación cluster/etiqueta por licitación
* ``mat_top_empresas_ccaa`` — ranking de empresas adjudicatarias por CCAA

Estas tablas son reemplazadas atómicamente en cada ejecución del scheduler
(DELETE + INSERT en una transacción), por lo que el dashboard nunca lee datos
parciales.

Revision ID: v20_mat_aggregates
Revises: v19_idx_lic_fecha_pub_tech
Create Date: 2026-05-17
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v20_mat_aggregates"
down_revision: str | Sequence[str] | None = "v19_idx_lic_fecha_pub_tech"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mat_clusters (
            id_externo    TEXT NOT NULL,
            cluster_id    INTEGER NOT NULL,
            cluster_label TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            PRIMARY KEY (id_externo)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_mat_clusters_cluster ON mat_clusters(cluster_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mat_top_empresas_ccaa (
            ccaa          TEXT NOT NULL,
            rank          INTEGER NOT NULL,
            nombre_canon  TEXT NOT NULL,
            n_adj         INTEGER NOT NULL DEFAULT 0,
            importe_total REAL NOT NULL DEFAULT 0.0,
            updated_at    TEXT NOT NULL,
            PRIMARY KEY (ccaa, rank)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_mat_top_emp_ccaa ON mat_top_empresas_ccaa(ccaa)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mat_top_empresas_ccaa")
    op.execute("DROP TABLE IF EXISTS mat_clusters")
