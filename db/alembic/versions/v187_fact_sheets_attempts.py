"""v187: ``tender_fact_sheets.attempts`` — tope explícito de intentos fallidos.

Revision ID: v187_fact_sheets_attempts
Revises: v186_resoluciones_llegada
Create Date: 2026-11-24

Qué corrige
-----------
El selector nocturno de fichas (``TenderFactSheetsRepository.
list_pending_licitaciones``) reintenta una ficha ``failed`` una vez por versión
del extractor y, si el fallo es del proveedor, una vez cada
``PLIEGO_FACTS_REINTENTO_DIAS`` mientras el plazo siga abierto. El tope salía
de la versión, de los documentos y del plazo (``shortcut:`` en el selector):
un expediente cuyo pliego hace fallar al proveedor siempre gastaba un hueco
del lote cada semana hasta su fecha límite.

``attempts`` cuenta los fallos seguidos de la fila: el upsert lo sube con cada
``failed`` que escribe y lo pone a 0 con cada ficha extraída. El selector deja
de reintentar al llegar al tope, salvo que cambien los documentos.

Las filas existentes nacen con 0: no hay historial de intentos, así que cada
ficha fallida tiene el tope entero por delante (lo mismo que hoy, acotado).

**Antes del código.** ``TenderFactSheetsRepository.upsert`` escribe
``attempts``: desplegado sin esta revisión, el lote de fichas falla en cada
``INSERT``. Se aplica con ``migrate.yml`` antes del despliegue de la API y del
job de pliegos.

Coste
-----
``ADD COLUMN ... NOT NULL DEFAULT 0`` con un default constante no reescribe la
tabla (Postgres ≥ 11): toma el lock un instante. ``lock_timeout`` para no
esperar detrás del lote de fichas.

Downgrade: borra la columna.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "v187_fact_sheets_attempts"
down_revision: str | None = "v186_resoluciones_llegada"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

TABLA = "tender_fact_sheets"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute("SET lock_timeout = '30s'")
    op.add_column(
        TABLA,
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_column(TABLA, "attempts")
