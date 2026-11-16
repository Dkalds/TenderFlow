"""v186: ``resoluciones_recurso.llegada_en`` y ``vinculada_en`` — novedades por llegada.

Revision ID: v186_resoluciones_llegada
Revises: v185_adjudicaciones_primera_extraccion
Create Date: 2026-11-16

Qué corrige
-----------
La banda «desde tu última visita» (``db/repositories/novedades.py``) decidía si
una resolución de recurso era novedad por ``fecha``, la fecha de la resolución.
Una resolución ingerida días después de dictarse, o vinculada a su licitación
días después de entrar (``db/resoluciones.vincular_pendientes``), tenía ya una
``fecha`` anterior a la visita y no salía nunca. Lo que el usuario no ha visto
es lo que **llegó** a lo suyo después de su visita.

Esta revisión crea dos marcas:

- ``llegada_en timestamptz NOT NULL DEFAULT now()``: cuándo entró la fila. El
  ``ON CONFLICT`` del upsert no la toca, así que la reingesta no la re-sella
  (``fecha_extraccion`` sí se re-sella en cada pasada).
- ``vinculada_en timestamptz NULL``: cuándo se enlazó con su licitación, si fue
  después de entrar. ``NULL`` si llegó ya enlazada, si no está enlazada o si se
  enlazó antes de esta revisión.

Novedades compara ``COALESCE(vinculada_en, llegada_en)`` con la marca.

El relleno, y por qué no inunda la próxima visita
-------------------------------------------------
Poner ``now()`` a las filas existentes haría novedad, en la próxima visita de
cada usuario, toda resolución enlazada a algo que sigue. No hay dato de llegada
para ellas, así que se rellenan con lo más temprano que se sabe cierto:

- la medianoche UTC de ``fecha``, el valor con el que el filtro anterior ya las
  comparaba: lo que antes no era novedad tampoco lo es ahora;
- acotado por ``fecha_extraccion`` (``LEAST``), porque la fila no pudo llegar
  después de su última extracción; eso corta una ``fecha`` futura mal parseada,
  que si no saldría como novedad en cada visita hasta esa fecha;
- y si ninguna de las dos se lee como fecha (``pg_input_is_valid``, Postgres 16),
  ``epoch``: nunca novedad, en vez de abortar la migración por una fila.

``vinculada_en`` se queda a ``NULL`` en las existentes: no se sabe cuándo se
enlazaron, y caer a ``llegada_en`` es el comportamiento de arriba.

El ``DEFAULT now()`` se pone **después** del relleno: añadido con la columna,
Postgres lo evaluaría una vez y sellaría todas las filas existentes con la hora
de la migración, que es justo lo que se quiere evitar.

Coste
-----
``resoluciones_recurso`` es pequeña (del orden de dos mil filas por año de
índice TACRC), así que el ``UPDATE`` y el ``SET NOT NULL`` (que recorre la
tabla) duran poco bajo el lock de la transacción de ``env.py``.
``lock_timeout`` para no esperar detrás de una ingesta. Idempotente: el relleno
solo toca las filas a ``NULL``.

Downgrade: borra las dos columnas.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "v186_resoluciones_llegada"
down_revision: str | None = "v185_adjudicaciones_primera_extraccion"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

TABLA = "resoluciones_recurso"

RELLENAR = (
    "UPDATE resoluciones_recurso SET llegada_en = COALESCE(LEAST("
    "  CASE WHEN pg_input_is_valid(fecha, 'date') "
    "       THEN fecha::date::timestamp AT TIME ZONE 'UTC' END, "
    "  CASE WHEN pg_input_is_valid(fecha_extraccion, 'timestamptz') "
    "       THEN fecha_extraccion::timestamptz END"
    "), 'epoch'::timestamptz) "
    "WHERE llegada_en IS NULL"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute("SET lock_timeout = '30s'")
    op.add_column(TABLA, sa.Column("llegada_en", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLA, sa.Column("vinculada_en", sa.DateTime(timezone=True), nullable=True))
    op.execute(RELLENAR)
    op.alter_column(TABLA, "llegada_en", server_default=sa.text("now()"), nullable=False)
    op.execute("RESET lock_timeout")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_column(TABLA, "vinculada_en")
    op.drop_column(TABLA, "llegada_en")
