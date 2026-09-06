"""v106: ``contratos_cartera`` (F4.3) y ``plantillas_organizacion`` (F6.4).

Revision ID: v106_cartera_y_plantillas_organizacion
Revises: v105_cuentas_objetivo_y_etiquetas
Create Date: 2026-09-06

Dos tablas de organización que D39 pre-autoriza. Van juntas por la misma razón
que v105: mismo modelo de tenencia y ninguna dependencia entre ellas que
obligue a ordenarlas.

``contratos_cartera`` (F4.3)
----------------------------
``won`` era un estado terminal sin vida posterior: la oportunidad se ganaba y
desaparecía del producto, justo cuando empieza lo que decide si se renueva.
Esta tabla es la continuación — un contrato en ejecución con su fecha de fin
efectiva, sus prórrogas y su ventana de relicitación.

**Una fila por oportunidad ganada**, y por eso la unicidad es ``pursuit_id``:
la cartera no es un registro paralelo que haya que mantener sincronizado, es la
proyección de lo que ya se decidió en el pipeline.

``fecha_fin_efectiva`` se guarda en vez de calcularse en cada lectura porque
las prórrogas la mueven y la ventana de aviso (seis, tres y un mes) tiene que
poder consultarse con un índice. ``fecha_fin_origen`` dice de dónde salió
—``publicada``, ``duracion``, ``prorroga`` o ``manual``—: sin eso, una fecha
estimada y una publicada se leen igual, que es lo que ADR-014 prohíbe.

``plantillas_organizacion`` (F6.4)
----------------------------------
Reglas, vistas guardadas y etiquetas que un miembro nuevo recibe al activarse.
``contenido_json`` guarda la definición entera y no una referencia: el miembro
recibe **copias**, no punteros, así que puede borrar lo suyo sin tocar la
plantilla y editar lo suyo sin que cambie para los demás. Guardar referencias
habría hecho lo contrario, que es justo lo que F6.4 dice que no.

``aplicada_a`` registra a quién se le aplicó ya, y es lo que hace la operación
idempotente: activar dos veces la misma membresía no duplica las reglas.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v106_cartera_y_plantillas_organizacion"
down_revision: str | Sequence[str] | None = "v105_cuentas_objetivo_y_etiquetas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    op.create_table(
        "contratos_cartera",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, nullable=False),
        # Sin FK con CASCADE: borrar una oportunidad no debe borrar el registro
        # de un contrato que se ejecutó. La limpieza, si hace falta, es una
        # decisión explícita y no un efecto colateral.
        sa.Column("pursuit_id", sa.Integer, nullable=False),
        sa.Column("licitacion_id", sa.Text, nullable=False),
        sa.Column("fecha_inicio", sa.Text, nullable=True),
        sa.Column("fecha_fin_efectiva", sa.Text, nullable=True),
        # publicada | duracion | prorroga | manual
        sa.Column("fecha_fin_origen", sa.Text, nullable=True),
        sa.Column("importe_adjudicado", sa.Float, nullable=True),
        sa.Column("prorrogas_aplicadas", sa.Integer, nullable=False, server_default="0"),
        # Oportunidad creada por «preparar renovación», si ya se hizo. Es lo
        # que hace ese botón idempotente: con valor, no se crea otra.
        sa.Column("renovacion_pursuit_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )
    op.create_unique_constraint("uq_contratos_cartera_pursuit", "contratos_cartera", ["pursuit_id"])
    # La consulta caliente del job de avisos: «qué vence pronto, por
    # organización». Parcial sobre las que tienen fecha — las que no, no
    # pueden vencer.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cartera_org_fin "
        "ON contratos_cartera (organization_id, fecha_fin_efectiva) "
        "WHERE fecha_fin_efectiva IS NOT NULL"
    )

    op.create_table(
        "plantillas_organizacion",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, nullable=False),
        # regla | vista | etiqueta
        sa.Column("tipo", sa.Text, nullable=False),
        sa.Column("nombre", sa.Text, nullable=False),
        sa.Column("contenido_json", sa.Text, nullable=False),
        sa.Column("created_by_user_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("idx_plantillas_org", "plantillas_organizacion", ["organization_id", "tipo"])

    op.create_table(
        "plantillas_aplicadas",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, nullable=False),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("aplicada_en", sa.Text, nullable=False),
        sa.Column("copias", sa.Integer, nullable=False, server_default="0"),
    )
    # La idempotencia de F6.4: una organización aplica su plantilla a un
    # miembro **una vez**. Activar dos veces la misma membresía no duplica.
    op.create_unique_constraint(
        "uq_plantillas_aplicadas", "plantillas_aplicadas", ["organization_id", "user_id"]
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_table("plantillas_aplicadas")
    op.drop_index("idx_plantillas_org", table_name="plantillas_organizacion")
    op.drop_table("plantillas_organizacion")
    op.execute("DROP INDEX IF EXISTS idx_cartera_org_fin")
    op.drop_table("contratos_cartera")
