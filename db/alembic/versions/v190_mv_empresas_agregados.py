"""v190: vista materializada ``empresas_agregados`` para ordenar ``/empresas``.

Revision ID: v190_mv_empresas_agregados
Revises: v189_jobs_terminados_indice
Create Date: 2026-11-25

Qué falta
---------
``EmpresasReadRepository.list_empresas`` ordena por ``contratos`` o
``importe`` (el orden por defecto de ``/empresas``) agrupando **todas** las
adjudicaciones del maestro en cada petición: necesita el agregado de todas las
empresas para saber cuáles van primero, y después tira todo menos ``limit``
filas. Los órdenes por nombre y NIF ya cortan la página sobre ``empresas`` y
agregan solo sus filas (``LATERAL``). Pendiente de la auditoría del 2026-11-04.

Esta vista guarda, por empresa del maestro, ``n_adjudicaciones`` e
``importe_total`` —la misma cuenta que hace la consulta, con ``LEFT JOIN``
para que una empresa sin adjudicaciones tenga 0—, con un índice por cada orden.
La página se elige sobre ella y sus filas se agregan en vivo, como en los
otros órdenes: las cifras que se ven son las de ahora; el orden, el del último
refresco (``scheduler/aggregates_precompute.py``, tras cada pasada).

El índice único sobre ``empresa_id`` es el requisito de
``REFRESH ... CONCURRENTLY``: sin él, refrescar bloquearía ``/empresas``.

Coste: una agregación de ``adjudicaciones`` (~130 000 filas en producción el
2026-11-24) al crearla y en cada refresco.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from alembic import op

revision: str = "v190_mv_empresas_agregados"
down_revision: str | None = "v189_jobs_terminados_indice"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

VISTA = "empresas_agregados"

#: Cuerpo congelado: el agregado de ``db/repositories/empresas.py::_LISTA_SELECT``.
CUERPO = (
    "SELECT e.empresa_id, COUNT(a.id) AS n_adjudicaciones, "
    "COALESCE(SUM(a.importe_adjudicado), 0) AS importe_total "
    "FROM empresas e LEFT JOIN adjudicaciones a ON a.empresa_id = e.empresa_id "
    "GROUP BY e.empresa_id"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute("SET statement_timeout = 0")
    op.execute(f"CREATE MATERIALIZED VIEW IF NOT EXISTS {VISTA} AS {CUERPO}")
    op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{VISTA}_empresa ON {VISTA} (empresa_id)")
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{VISTA}_importe ON {VISTA} (importe_total, empresa_id)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{VISTA}_contratos "
        f"ON {VISTA} (n_adjudicaciones, empresa_id)"
    )
    op.execute(f"ANALYZE {VISTA}")
    op.execute("RESET statement_timeout")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {VISTA}")
