"""v191: ``adjudicaciones.nombre_normalizado`` y ``nif_normalizado``.

Revision ID: v191_adj_identidad_normalizada
Revises: v190_mv_empresas_agregados
Create Date: 2026-11-25

Qué falta
---------
La cobertura de la resolución de empresas del healthcheck
(``_incorporar_resolucion_empresas``) cuenta las adjudicaciones sin empresa
cuya identidad ya está en la cola de revisión. La clave de la cola es
``(normalize_company(nombre), normalize_nif(nif))``, y ``normalize_company``
no tiene gemela exacta en SQL, así que cada pasada traía a Python todas las
identidades sin resolver para normalizarlas (``shortcut:`` de
``db.empresas.identidades_sin_resolver``). Pendiente de la auditoría del
2026-11-04.

Esta revisión añade las dos columnas, anulables y sin default (``ADD COLUMN``
sin reescritura). Las escribe ``db/upsert.py`` al insertar cada adjudicación,
con ``shared.normalization``; las filas existentes las rellena
``scripts/backfill_adj_normalizado.py``. Mientras quede alguna a ``NULL``, el
healthcheck la normaliza en Python como antes: el recuento no cambia durante
el relleno.

**Antes del código.** El upsert de adjudicaciones escribe las dos columnas:
desplegado sin esta revisión, la ingesta falla en cada ``INSERT``. Se aplica
con ``migrate.yml`` antes del despliegue.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "v191_adj_identidad_normalizada"
down_revision: str | None = "v190_mv_empresas_agregados"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

COLUMNAS = ("nombre_normalizado", "nif_normalizado")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute("SET lock_timeout = '30s'")
    for columna in COLUMNAS:
        op.add_column("adjudicaciones", sa.Column(columna, sa.Text(), nullable=True))
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    if not _is_postgres():
        return
    for columna in COLUMNAS:
        op.drop_column("adjudicaciones", columna)
