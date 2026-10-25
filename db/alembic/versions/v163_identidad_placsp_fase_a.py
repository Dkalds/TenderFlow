"""v163: identidad PLACSP, fase A — el órgano de la fuente y los ids anteriores.

Revision ID: v163_identidad_placsp_fase_a
Revises: v162_user_notifications_user_id_fase3
Create Date: 2026-10-25

Qué falla hoy
-------------
El ``id_externo`` de las filas ``placsp``/``bulk_*`` es el ``ContractFolderID``
sin órgano, y dos órganos con el mismo número de expediente se pisan por
``ON CONFLICT(id_externo)`` (3,4 % de los ids con historia; RFC
``2026-10-24-rfc-identidad-placsp-organo-expediente``). Arreglarlo exige
re-escribir la clave de ~24.700 filas y de todo lo que las referencia, y eso
necesita saber **qué órgano** escribió cada fila, cosa que hoy no se guarda en
ninguna columna (``organo_id`` apunta al maestro de ADR-032 y ``organos.dir3``
no es el id de la Plataforma).

Qué hace (migración A del RFC: aditiva, reversible)
--------------------------------------------------
1. ``licitaciones.organo_ref_fuente TEXT NULL``: el identificador del órgano en
   la plataforma de origen, tal como entrará en la clave nueva
   (``ID_PLATAFORMA``, y como respaldo ``NIF`` o ``DIR3``; ``ID_OC_PLAT`` en
   agregadas). El parser CODICE lo extrae desde esta tanda y el upsert lo
   escribe con ``COALESCE`` (nunca lo pisa con ``NULL``). Es el mapa viejo →
   nuevo de la fase B. Sin ``DEFAULT``: no reescribe la tabla.
2. ``licitaciones_id_anterior``: una fila por clave re-escrita. Sostiene la
   resolución de ids viejos en la API (``Deprecation``/``Sunset``) y la 308 de
   la ficha pública. Genérica a propósito (``motivo``): la próxima re-key la
   reutiliza. ``ON DELETE CASCADE``: un alias de una fila borrada no apunta a
   nada. Nace vacía; la fase B la rellena.

Los escritores siguen escribiendo la clave vieja: tras aplicar esto no cambia
nada visible, y la ingesta va rellenando ``organo_ref_fuente``.

Rollback
--------
``downgrade`` borra la columna y la tabla. Sin pérdida mientras la fase B no
haya corrido (la tabla está vacía y la columna se vuelve a rellenar al
reingerir).

Después de aplicar: ``mcp_server/catalogo.py`` ya clasifica la tabla nueva;
regenerar los grants del rol del MCP (runbook de recuperación ante desastres,
§5).

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "v163_identidad_placsp_fase_a"
down_revision: str | None = "v162_user_notifications_user_id_fase3"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

TABLA_ALIAS = "licitaciones_id_anterior"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    op.add_column("licitaciones", sa.Column("organo_ref_fuente", sa.Text, nullable=True))

    op.create_table(
        "licitaciones_id_anterior",
        sa.Column("id_anterior", sa.Text, primary_key=True),
        sa.Column(
            "id_externo",
            sa.Text,
            sa.ForeignKey("licitaciones.id_externo", ondelete="CASCADE"),
            nullable=False,
        ),
        # Qué re-key lo escribió (``rekey_placsp_organo``…): la guarda de FK de
        # la migración de re-key lo usa para contar lo suyo.
        sa.Column("motivo", sa.Text, nullable=False),
        sa.Column("creado_en", sa.Text, nullable=False),
    )
    # La resolución va por la PK; el índice inverso sirve al ``CASCADE`` y a
    # «qué ids viejos tuvo esta fila».
    op.create_index(
        f"idx_{TABLA_ALIAS}_id_externo",
        TABLA_ALIAS,
        ["id_externo"],
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(f"DROP TABLE IF EXISTS {TABLA_ALIAS} CASCADE")
    op.drop_column("licitaciones", "organo_ref_fuente")
