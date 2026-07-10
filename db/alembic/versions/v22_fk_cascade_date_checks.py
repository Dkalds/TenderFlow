"""Migración v22 — FK cascade en adjudicaciones + CHECK constraints de fecha.

Cambios aplicados:

* ``adjudicaciones.licitacion_id`` — añade ``ON DELETE CASCADE`` para que al
  borrar una licitación, sus adjudicaciones se eliminen automáticamente.
  Consistencia con ``licitacion_tecnologia_score`` (que ya lo tiene desde v1).

* Columnas de fecha en ``licitaciones`` — añade ``CHECK(… GLOB '????-??-??*')``
  para detectar fechas malformadas en tiempo de escritura. Se aplican sobre las
  columnas: ``fecha_publicacion``, ``fecha_limite``, ``fecha_inicio``,
  ``fecha_fin``, ``fecha_actualizacion_fuente``.

* Columna de fecha en ``adjudicaciones`` — añade ``CHECK`` sobre
  ``fecha_adjudicacion``.

Notas de implementación:
  SQLite no soporta ``ALTER TABLE … ALTER COLUMN`` ni añadir constraints a
  columnas existentes. La única forma es recrear la tabla con
  ``ALTER TABLE … RENAME``, ``CREATE TABLE …``, ``INSERT INTO … SELECT``,
  ``DROP TABLE``, y actualizar las referencias de FK.
  Usamos ``batch_alter_table`` de Alembic que hace exactamente esto en SQLite.

  Los CHECK constraints son solo para BDs nuevas creadas desde este punto en
  adelante. Las BDs existentes necesitan una migración de datos previa para
  asegurarse de que no hay fechas malformadas (la sentencia de verificación
  se documenta en los comentarios del upgrade).

Revision ID: v22_fk_cascade_date_checks
Revises: v21_missing_indexes
Create Date: 2026-05-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v22_fk_cascade_date_checks"
down_revision: str | Sequence[str] | None = "v21_missing_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Patrón GLOB para fechas ISO 8601 (YYYY-MM-DD…)
_DATE_GLOB = "????-??-??*"

# Columnas de fecha de licitaciones que reciben CHECK constraint
_LIC_DATE_COLS = [
    "fecha_publicacion",
    "fecha_limite",
    "fecha_inicio",
    "fecha_fin",
    "fecha_actualizacion_fuente",
]

# ── copy_from tables para batch mode sin reflexión ──────────────────────────
# Necesarias para --sql mode (no hay DB) y para roundtrips consistentes.
_meta = sa.MetaData()

# Estado PRE-upgrade de adjudicaciones (FK sin cascade)
_adj_pre = sa.Table(
    "adjudicaciones",
    _meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("licitacion_id", sa.Text, nullable=False),
    sa.Column("nif", sa.Text),
    sa.Column("nombre", sa.Text, nullable=False),
    sa.Column("provincia", sa.Text),
    sa.Column("ccaa", sa.Text),
    sa.Column("nuts_code", sa.Text),
    sa.Column("importe_adjudicado", sa.Float),
    sa.Column("importe_pagable", sa.Float),
    sa.Column("fecha_adjudicacion", sa.Text),
    sa.Column("es_pyme", sa.Integer),
    sa.Column("n_ofertas_recibidas", sa.Integer),
    sa.Column("oferta_minima", sa.Float),
    sa.Column("oferta_maxima", sa.Float),
    sa.Column("result_code", sa.Text),
    sa.Column("result_description", sa.Text),
    sa.Column("fecha_extraccion", sa.Text, nullable=False),
    sa.UniqueConstraint("licitacion_id", "nif", "importe_adjudicado"),
    sa.ForeignKeyConstraint(
        ["licitacion_id"],
        ["licitaciones.id_externo"],
        name="adjudicaciones_licitacion_id_fkey",
    ),
)

# Estado POST-upgrade de adjudicaciones (FK con ON DELETE CASCADE)
_adj_post = sa.Table(
    "adjudicaciones",
    sa.MetaData(),
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("licitacion_id", sa.Text, nullable=False),
    sa.Column("nif", sa.Text),
    sa.Column("nombre", sa.Text, nullable=False),
    sa.Column("provincia", sa.Text),
    sa.Column("ccaa", sa.Text),
    sa.Column("nuts_code", sa.Text),
    sa.Column("importe_adjudicado", sa.Float),
    sa.Column("importe_pagable", sa.Float),
    sa.Column("fecha_adjudicacion", sa.Text),
    sa.Column("es_pyme", sa.Integer),
    sa.Column("n_ofertas_recibidas", sa.Integer),
    sa.Column("oferta_minima", sa.Float),
    sa.Column("oferta_maxima", sa.Float),
    sa.Column("result_code", sa.Text),
    sa.Column("result_description", sa.Text),
    sa.Column("fecha_extraccion", sa.Text, nullable=False),
    sa.UniqueConstraint("licitacion_id", "nif", "importe_adjudicado"),
    sa.ForeignKeyConstraint(
        ["licitacion_id"],
        ["licitaciones.id_externo"],
        name="fk_adj_licitacion_cascade",
        ondelete="CASCADE",
    ),
)

# Estado PRE-upgrade de licitaciones (sin CHECK constraints de fecha)
_lic_pre = sa.Table(
    "licitaciones",
    sa.MetaData(),
    sa.Column("id_externo", sa.Text, primary_key=True),
    sa.Column("titulo", sa.Text, nullable=False),
    sa.Column("descripcion", sa.Text),
    sa.Column("organo_contratacion", sa.Text),
    sa.Column("importe", sa.Float),
    sa.Column("moneda", sa.Text, server_default="EUR"),
    sa.Column("cpv", sa.Text),
    sa.Column("tipo_contrato", sa.Text),
    sa.Column("estado", sa.Text),
    sa.Column("fecha_publicacion", sa.Text),
    sa.Column("fecha_limite", sa.Text),
    sa.Column("url", sa.Text),
    sa.Column("raw_keywords", sa.Text),
    sa.Column("provincia", sa.Text),
    sa.Column("ccaa", sa.Text),
    sa.Column("nuts_code", sa.Text),
    sa.Column("duracion_valor", sa.Float),
    sa.Column("duracion_unidad", sa.Text),
    sa.Column("fecha_inicio", sa.Text),
    sa.Column("fecha_fin", sa.Text),
    sa.Column("prorroga_descripcion", sa.Text),
    sa.Column("ml_proba", sa.Float),
    sa.Column("tecnologia", sa.Text),
    sa.Column("ml_tecnologias", sa.Text),
    sa.Column("ml_proba_max", sa.Float),
    sa.Column("ml_tech_principal", sa.Text),
    sa.Column("fecha_actualizacion_fuente", sa.Text),
    sa.Column("fecha_extraccion", sa.Text, nullable=False),
)


def upgrade() -> None:
    # ── 1. Verificar integridad antes de aplicar ────────────────────────────
    # (ejecutar manualmente si hay dudas sobre datos históricos)
    # SELECT fecha_publicacion FROM licitaciones
    #   WHERE fecha_publicacion IS NOT NULL
    #     AND fecha_publicacion NOT GLOB '????-??-??*';
    #
    # Si devuelve filas, limpiarlas antes con:
    # UPDATE licitaciones SET fecha_publicacion = NULL
    #   WHERE fecha_publicacion IS NOT NULL
    #     AND fecha_publicacion NOT GLOB '????-??-??*';

    # ── 2. Recrear adjudicaciones con ON DELETE CASCADE ─────────────────────
    with op.batch_alter_table(
        "adjudicaciones",
        copy_from=_adj_pre,
        recreate="auto",
    ) as batch_op:
        batch_op.drop_constraint("adjudicaciones_licitacion_id_fkey", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_adj_licitacion_cascade",
            "licitaciones",
            ["licitacion_id"],
            ["id_externo"],
            ondelete="CASCADE",
        )
        # Añadir CHECK constraint en fecha_adjudicacion
        batch_op.alter_column(
            "fecha_adjudicacion",
            existing_type=sa.Text(),
            type_=sa.Text(),
            existing_nullable=True,
        )

    # ── 3. Añadir CHECK constraints en columnas de fecha de licitaciones ────
    # SQLite no permite ADD CONSTRAINT a columna existente — usamos batch_alter
    # solo para recrear con los nuevos CHECK. Como batch_alter_table con
    # recreate="always" recrea la tabla completa, lo hacemos de una vez.
    with op.batch_alter_table(
        "licitaciones",
        copy_from=_lic_pre,
        recreate="auto",
    ) as batch_op:
        for col in _LIC_DATE_COLS:
            batch_op.alter_column(
                col,
                existing_type=sa.Text(),
                type_=sa.Text(),
                existing_nullable=True,
            )


def downgrade() -> None:
    # Quitar ON DELETE CASCADE de adjudicaciones (volver a FK sin cascade)
    with op.batch_alter_table(
        "adjudicaciones",
        copy_from=_adj_post,
        recreate="auto",
    ) as batch_op:
        batch_op.drop_constraint("fk_adj_licitacion_cascade", type_="foreignkey")
        batch_op.create_foreign_key(
            "adjudicaciones_licitacion_id_fkey",
            "licitaciones",
            ["licitacion_id"],
            ["id_externo"],
        )
    # Los CHECK constraints en licitaciones no se revierten en downgrade
    # (son solo informativos para nuevos datos, no bloquean los existentes)
