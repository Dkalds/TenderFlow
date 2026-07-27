"""Migracion v58 -- elimina la materializacion ``mat_top_empresas_ccaa``.

La tabla se recomputaba entera en cada pasada de la pipeline canonica (cada
4h: DELETE + INSERT del top-10 de empresas por CCAA) y **ningun consumidor la
leia**. El unico lector era ``AggregateRepository.load_mat_top_empresas_ccaa``,
que a su vez no lo llamaba nadie desde que se retiro el dashboard Streamlit
(ADR-002). Coste recurrente sin valor, y una copia derivada mas de la verdad
que podia divergir en silencio.

``mat_clusters`` **se conserva**: si tiene lector real
(``services/clustering_engine.py``), y ``kpi_snapshots`` tambien
(``scheduler/healthcheck.py`` lo usa como marca temporal de la ultima pipeline).

Reversible: ``downgrade`` recrea la tabla vacia con su schema original. No se
restauran datos porque son derivados -- se repoblaban solos en cada pipeline.

Revision ID: v58_drop_mat_top_empresas_ccaa
Revises: v57_pg_users_is_admin
Create Date: 2026-07-26
"""

from __future__ import annotations

from alembic import op

revision: str = "v58_drop_mat_top_empresas_ccaa"
down_revision: str | None = "v57_pg_users_is_admin"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mat_top_empresas_ccaa")


def downgrade() -> None:
    """Recrea la tabla vacia (los datos eran derivados, no fuente de verdad)."""
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
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mat_top_empresas_ccaa ON mat_top_empresas_ccaa(ccaa)"
    )
