"""v149: criterios, garantías y solvencia oficiales de CODICE, por expediente y lote.

Revision ID: v149_condiciones_oficiales_codice
Revises: v146_lic_organo_norm_index
Create Date: 2026-10-12

Qué falta hoy
-------------
De ``cac:TenderingTerms`` solo se guardaba un agregado, ``licitaciones.
peso_precio_pct`` (v85). Qué criterios puntúan y cuánto, qué garantía se
exige y qué solvencia piden solo llegaba por la ficha LLM del pliego
(``tender_fact_sheets``), que no corre en lote y cuya calidad no se mide. La
fuente oficial publica esos datos en el propio anuncio; el parser los lee
desde esta tanda (``scraper.codice_parser.parse_condiciones``) y aquí se
guardan.

Forma, y por qué
----------------
Tres tablas, una por familia, y no una columna JSON en ``licitaciones``:

- Las tres se leen por separado (el checklist Go/No-Go solo quiere la
  solvencia; el simulador, los criterios) y cada una tiene columnas propias
  que se pueden consultar y agregar —el peso del precio por órgano, la
  garantía media por CPV— sin desempaquetar JSON.
- Ninguna engorda la fila de ``licitaciones``, que es la tabla caliente de
  todas las lecturas.

Cada fila lleva ``lote_numero`` (``NULL`` = expediente), el ``cbc:ID`` del lote
tal como se publica, y **no** un FK a ``lotes.id``: ``replace_lotes`` reasigna
esos ids en cada re-ingesta, y la clave estable del lote es su número
—mismo razonamiento que v110 y v140—. ``orden`` es la posición dentro de su
ámbito; la unicidad ``(licitacion_id, lote_numero, orden)`` va en un índice de
expresión con ``COALESCE`` porque ``NULL <> NULL`` dejaría sin proteger justo
el nivel de expediente.

Los códigos (``tipo_codigo``, ``subtipo_codigo``) se guardan **crudos**, sin
lista que los traduzca: sus listas controladas no se han podido verificar
contra la Plataforma, y una etiqueta de memoria sería plausible pero falsa (el
criterio de ``shared/procedimientos.py``).

Sin ``CHECK`` sobre valores del feed (pesos, porcentajes, importes): la tabla
se escribe en la misma transacción que la licitación, y un valor raro de la
fuente que violara una restricción tumbaría la ingesta del expediente entero.
El único ``CHECK`` es el de ``clase``, cuyo vocabulario lo pone el parser.

Escritura
---------
La hace ``db/upsert.py`` dentro de la transacción del upsert de licitaciones:
por familia, si la versión nueva del anuncio trae filas, reemplazan a las
anteriores (``DELETE`` + ``INSERT``); si no trae ninguna, no se toca nada —la
fase de adjudicación deja de publicar ``TenderingTerms``, como deja de publicar
el plazo—. El upsert comprueba en el catálogo que las tablas existen antes de
escribir: el código puede llegar a producción antes que esta revisión.

Volumen
-------
Sin medir sobre el feed (ver el docstring de ``parse_condiciones``). Del orden
de unos pocos criterios, cero o una garantía y unos pocos requisitos por
expediente con anuncio de licitación; el histórico ya ingerido no se rellena
solo, solo al re-ingerirse.

RLS
---
Dato de mercado, sin ``organization_id``: no lleva políticas por tenant. Nace
cerrada a ``anon``/``authenticated`` y abierta a ``tenderflow_app``, como
``tecnologias_keywords`` en v126.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "v149_condiciones_oficiales_codice"
down_revision: str | Sequence[str] | None = "v146_lic_organo_norm_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLAS: tuple[str, ...] = (
    "licitacion_criterios_adjudicacion",
    "licitacion_garantias",
    "licitacion_solvencia",
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _columnas_comunes() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "licitacion_id",
            sa.Text,
            sa.ForeignKey("licitaciones.id_externo", ondelete="CASCADE"),
            nullable=False,
        ),
        # `cbc:ID` del lote tal como se publica; NULL = nivel de expediente.
        sa.Column("lote_numero", sa.Text, nullable=True),
        sa.Column("orden", sa.Integer, nullable=False),
    ]


def _proteger(tabla: str) -> None:
    """RLS fail-closed para la Data API y acceso explícito del rol runtime."""
    op.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN "
        f"REVOKE ALL ON TABLE {tabla} FROM anon; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN "
        f"REVOKE ALL ON TABLE {tabla} FROM authenticated; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_app') THEN "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {tabla} TO tenderflow_app; "
        f"GRANT USAGE, SELECT ON SEQUENCE {tabla}_id_seq TO tenderflow_app; "
        "IF NOT EXISTS (SELECT 1 FROM pg_policies "
        f"WHERE schemaname = current_schema() AND tablename = '{tabla}' "
        "AND policyname = 'tenderflow_app_full_access') THEN "
        f"CREATE POLICY tenderflow_app_full_access ON {tabla} "
        "FOR ALL TO tenderflow_app USING (true) WITH CHECK (true); "
        "END IF; END IF; END $$"
    )


def _unicidad(tabla: str) -> None:
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{tabla}_ambito_orden "
        f"ON {tabla} (licitacion_id, COALESCE(lote_numero, ''), orden)"
    )


def upgrade() -> None:
    if not _is_postgres():
        return

    op.create_table(
        "licitacion_criterios_adjudicacion",
        *_columnas_comunes(),
        # `orden` del criterio del que cuelga este, si es un subcriterio.
        sa.Column("padre_orden", sa.Integer, nullable=True),
        sa.Column("descripcion", sa.Text, nullable=True),
        # `cbc:WeightNumeric` tal como se publica, en la escala del órgano.
        sa.Column("peso", sa.Float, nullable=True),
        # El mismo peso sobre 100, solo si la escala del ámbito es deducible.
        sa.Column("peso_pct", sa.Float, nullable=True),
        sa.Column("es_precio", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("tipo_codigo", sa.Text, nullable=True),
        sa.Column("subtipo_codigo", sa.Text, nullable=True),
        sa.Column("nota", sa.Text, nullable=True),
        sa.Column("fecha_extraccion", sa.Text, nullable=False),
    )
    op.create_table(
        "licitacion_garantias",
        *_columnas_comunes(),
        sa.Column("tipo_codigo", sa.Text, nullable=True),
        # `cbc:AmountRate` tal cual (5 = 5 %).
        sa.Column("porcentaje", sa.Float, nullable=True),
        # `cbc:LiabilityAmount`.
        sa.Column("importe", sa.Float, nullable=True),
        sa.Column("moneda", sa.Text, nullable=True),
        sa.Column("descripcion", sa.Text, nullable=True),
        sa.Column("fecha_extraccion", sa.Text, nullable=False),
    )
    op.create_table(
        "licitacion_solvencia",
        *_columnas_comunes(),
        sa.Column("clase", sa.Text, nullable=False),
        sa.Column("tipo_codigo", sa.Text, nullable=True),
        sa.Column("descripcion", sa.Text, nullable=True),
        # `cbc:ThresholdAmount`.
        sa.Column("umbral_importe", sa.Float, nullable=True),
        sa.Column("moneda", sa.Text, nullable=True),
        sa.Column("fecha_extraccion", sa.Text, nullable=False),
        sa.CheckConstraint(
            "clase IN ('tecnica', 'economica', 'clasificacion')",
            name="ck_licitacion_solvencia_clase",
        ),
    )
    for tabla in TABLAS:
        _unicidad(tabla)
        _proteger(tabla)


def downgrade() -> None:
    if not _is_postgres():
        return
    for tabla in reversed(TABLAS):
        op.execute(f"DROP TABLE IF EXISTS {tabla} CASCADE")
