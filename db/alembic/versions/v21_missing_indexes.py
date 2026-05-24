"""Migración v21 — Índices faltantes para queries frecuentes de la API.

Añade índices que cubrían hot paths identificados en auditoría:

* ``idx_lic_tecnologia``  — filtrado por tecnologia en list/search endpoints
  (complementa el índice parcial v19 que solo cubre WHERE tecnologia IS NOT NULL)
* ``idx_lic_cursor``       — keyset pagination por (fecha_publicacion, id_externo);
  evita full-scan en list_cursor cuando hay miles de licitaciones
* ``idx_lic_importe``     — range queries importe_min/importe_max en search_advanced
* ``idx_domain_events_actor`` — queries por actor_id en domain_events (auditoría por usuario)

Revision ID: v21_missing_indexes
Revises: v20_mat_aggregates
Create Date: 2026-05-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v21_missing_indexes"
down_revision: str | Sequence[str] | None = "v20_mat_aggregates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Índice general sobre tecnologia para filtros exactos (ej. tecnologia='SAP').
    # Complementario al parcial idx_lic_fecha_pub_tech (v19) que solo cubre IS NOT NULL.
    op.execute("CREATE INDEX IF NOT EXISTS idx_lic_tecnologia ON licitaciones(tecnologia)")

    # Composite index para cursor pagination: el endpoint list_cursor pagina por
    # (fecha_publicacion DESC, id_externo) para keyset seek eficiente.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_lic_cursor "
        "ON licitaciones(fecha_publicacion DESC, id_externo)"
    )

    # Índice sobre importe para range queries (importe_min / importe_max).
    op.execute("CREATE INDEX IF NOT EXISTS idx_lic_importe ON licitaciones(importe)")

    # Índice sobre actor_id en domain_events para queries de auditoría por usuario.
    op.execute("CREATE INDEX IF NOT EXISTS idx_domain_events_actor ON domain_events(actor_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_lic_tecnologia")
    op.execute("DROP INDEX IF EXISTS idx_lic_cursor")
    op.execute("DROP INDEX IF EXISTS idx_lic_importe")
    op.execute("DROP INDEX IF EXISTS idx_domain_events_actor")
