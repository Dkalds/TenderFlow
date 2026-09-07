"""v105: ``cuentas_objetivo``, ``etiquetas`` y ``etiquetas_aplicadas``.

Revision ID: v105_cuentas_objetivo_y_etiquetas
Revises: v104_pursuit_outcome_reason_code
Create Date: 2026-09-06

F1.5 (seguir un órgano como cuenta objetivo) y F1.6 (etiquetas de
organización, decisión D38). Van en la misma revisión porque comparten el
mismo modelo de tenencia —ámbito de organización, no de usuario— y porque
``etiquetas_aplicadas`` referencia a ``cuentas_objetivo`` como uno de sus tres
objetos: separarlas obligaría a ordenar dos migraciones por una FK.

``cuentas_objetivo``
--------------------
Se guarda el **nombre normalizado** del órgano (``organo_norm``), no un id: el
maestro de órganos (C1.2 del plan complementario) todavía no existe. La
columna ``organo_id`` nace ya, nullable, para que ese maestro pueda rellenarla
sin otra migración y sin que la clave de unicidad cambie de forma. Mientras
tanto la unicidad es ``(organization_id, organo_norm)``, que es lo que impide
que dos personas del mismo equipo sigan el mismo órgano dos veces.

El nombre normalizado se calcula en Python con ``plegar_organo``
(``db/sql_fragments.py``), el mismo que ya usan los agregados: si aquí se
plegara distinto, «Ayuntamiento de Alcalá» seguido desde Mercado y desde
Cuentas serían dos cuentas.

``etiquetas`` y ``etiquetas_aplicadas``
---------------------------------------
D38: libres por organización, hasta treinta, con color. El límite **no** es un
CHECK: contar filas en un CHECK exige un trigger, y un trigger que cuenta en
cada inserción es un coste permanente para una regla que se comprueba mejor en
la escritura. Lo aplica el servicio, y el test lo fija.

``etiquetas_aplicadas`` es una tabla de unión polimórfica —``objeto_tipo`` +
``objeto_id``— y por tanto **sin FK al objeto**. Es deliberado: las tres cosas
etiquetables viven en tres tablas con tipos de clave distintos (``favorito``
es un ``id_externo`` de texto, ``oportunidad`` un entero, ``cuenta`` otro), y
tres columnas nullable con tres FKs harían la tabla más difícil de leer y de
consultar sin ganar integridad real —el borrado en cascada lo tendría que
hacer igualmente el servicio para el caso del favorito—.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v105_cuentas_objetivo_y_etiquetas"
down_revision: str | Sequence[str] | None = "v104_pursuit_outcome_reason_code"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    op.create_table(
        "cuentas_objetivo",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, nullable=False),
        # Nombre tal como lo publica la fuente, para pintarlo sin re-consultar.
        sa.Column("organo_nombre", sa.Text, nullable=False),
        # Nombre plegado (sin acentos, minúsculas, espacios colapsados): la
        # clave real de identidad mientras no exista el maestro.
        sa.Column("organo_norm", sa.Text, nullable=False),
        # Nace nullable para C1.2. Cuando el maestro llegue, un UPDATE la
        # rellena y la unicidad puede migrar sin tocar la forma de la tabla.
        sa.Column("organo_id", sa.Integer, nullable=True),
        sa.Column("created_by_user_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("nota", sa.Text, nullable=True),
    )
    op.create_unique_constraint(
        "uq_cuentas_objetivo_org_organo",
        "cuentas_objetivo",
        ["organization_id", "organo_norm"],
    )

    op.create_table(
        "etiquetas",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, nullable=False),
        sa.Column("nombre", sa.Text, nullable=False),
        # Normalizado para la unicidad: dos etiquetas «Q4» y «q4» en la misma
        # organización son la misma etiqueta escrita dos veces.
        sa.Column("nombre_norm", sa.Text, nullable=False),
        # Hex `#rrggbb`. Lo valida el DTO; aquí es texto como el resto de
        # enumerados del esquema.
        sa.Column("color", sa.Text, nullable=False),
        sa.Column("created_by_user_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_unique_constraint(
        "uq_etiquetas_org_nombre", "etiquetas", ["organization_id", "nombre_norm"]
    )

    op.create_table(
        "etiquetas_aplicadas",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, nullable=False),
        sa.Column(
            "etiqueta_id",
            sa.Integer,
            sa.ForeignKey("etiquetas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # `favorito` | `oportunidad` | `cuenta`. Vocabulario cerrado en el DTO.
        sa.Column("objeto_tipo", sa.Text, nullable=False),
        # Texto para los tres: el favorito se identifica por `id_externo`, que
        # no es numérico. Guardar el entero como texto cuesta un cast en la
        # consulta y ahorra tres columnas nullable.
        sa.Column("objeto_id", sa.Text, nullable=False),
        sa.Column("aplicada_por_user_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_unique_constraint(
        "uq_etiquetas_aplicadas",
        "etiquetas_aplicadas",
        ["etiqueta_id", "objeto_tipo", "objeto_id"],
    )
    # La consulta caliente es «etiquetas de estos objetos», para pintar los
    # chips de una lista entera de una vez.
    op.create_index(
        "idx_etiquetas_aplicadas_objeto",
        "etiquetas_aplicadas",
        ["organization_id", "objeto_tipo", "objeto_id"],
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_index("idx_etiquetas_aplicadas_objeto", table_name="etiquetas_aplicadas")
    op.drop_table("etiquetas_aplicadas")
    op.drop_table("etiquetas")
    op.drop_table("cuentas_objetivo")
