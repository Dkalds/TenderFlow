"""v112: perfil de capacidad de la organización (S2.2).

Plan de arquitectura 2026-09 v2, S2.2, bajo la decisión D11 —tablas propias y
no ``organizations.settings_json``, «porque el cierre por NIF y el contraste de
solvencia se resuelven en SQL y un JSON no se indexa ni se valida».

**Por qué CUATRO tablas y no una llamada ``organization_capabilities``.** El
plan nombra el perfil en singular, pero lo que guarda son cuatro cosas sin una
sola columna en común: una certificación tiene ámbito y vigencia, una
facturación tiene ejercicio e importe, una referencia tiene órgano, año y
tecnología, y un perfil de equipo tiene rol, años y cantidad. Meterlas en una
tabla con un discriminador obliga a dejar nullable todo lo específico de cada
tipo y a defenderlo con ``CHECK``s condicionales: sería el problema que D11
rechaza —campos que nadie valida— escrito en SQL en vez de en JSON. Cuatro
tablas con sus ``NOT NULL`` de verdad es lo que la decisión pedía. El perfil
como concepto vive en ``db/repositories/organization_capabilities.py``, que las
lee y las escribe en una sola transacción.

Diseño común a las cuatro:

* ``organization_id`` con ``ON DELETE CASCADE``: el perfil no sobrevive a su
  organización, y no hay nada que conservar por auditoría —es un dato
  declarativo que se reemplaza entero en cada PUT.
* Sin ``updated_at`` por fila: el PUT reemplaza el conjunto completo, así que
  la marca de tiempo por fila mediría el reemplazo y no el cambio.
  ``created_at`` sirve para saber cuándo se declaró por última vez.
* Los importes van a ``NUMERIC(16, 2)`` y no a ``double precision``: la
  facturación se compara contra el umbral de solvencia del pliego y el error
  binario del float haría depender un veredicto de la representación.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "v112_organization_capabilities"
down_revision: str | Sequence[str] | None = "v111_organization_nifs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLAS = (
    "organization_certifications",
    "organization_revenues",
    "organization_references",
    "organization_team_profiles",
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _protect_table(table: str) -> None:
    """RLS + grants mínimos, el mismo patrón que v96, v104 y v111."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN "
        f"REVOKE ALL ON TABLE {table} FROM anon; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN "
        f"REVOKE ALL ON TABLE {table} FROM authenticated; "
        "END IF; "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_app') THEN "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO tenderflow_app; "
        f"GRANT USAGE, SELECT ON SEQUENCE {table}_id_seq TO tenderflow_app; "
        f"CREATE POLICY tenderflow_app_full_access ON {table} "
        "FOR ALL TO tenderflow_app USING (true) WITH CHECK (true); "
        "END IF; END $$"
    )


# `sa.Column[Any]` y no `sa.Column[object]`: los stubs de SQLAlchemy parametrizan
# `Column` por el tipo *Python* de la columna, y ese tipo es distinto en cada una
# de las tres de aquí (int, int, datetime). Con `object` mypy no puede resolver
# la sobrecarga de `Column.__init__` que acepta la CLASE `sa.Integer` en vez de
# una instancia, que es como las declara el resto de migraciones del repo. El
# `Any` acota a la firma del helper y no viaja a ningún sitio: lo que devuelve se
# pasa tal cual a `op.create_table`.
def _columnas_comunes() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "organization_id",
            sa.Integer,
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    ]


def upgrade() -> None:
    if not _is_postgres():
        return

    op.create_table(
        "organization_certifications",
        *_columnas_comunes(),
        sa.Column("nombre", sa.Text, nullable=False),
        # Mismo vocabulario que `CertificationRequirement.scope` del pliego
        # menos `other`: en la ficha `other` significa «no se sabe quién la
        # acredita», y declarar eso de la propia empresa no dice nada.
        sa.Column("ambito", sa.Text, nullable=False, server_default=sa.text("'company'")),
        # NULL = «sin caducidad declarada». El checklist la trata como vigente
        # y lo dice en el motivo, en vez de inventarse una fecha.
        sa.Column("vigente_hasta", sa.Date, nullable=True),
        sa.CheckConstraint(
            "ambito IN ('company','team')",
            name="ck_organization_certifications_ambito",
        ),
    )

    op.create_table(
        "organization_revenues",
        *_columnas_comunes(),
        sa.Column("ejercicio", sa.Integer, nullable=False),
        sa.Column("importe_eur", sa.Numeric(16, 2), nullable=False),
        sa.CheckConstraint("importe_eur >= 0", name="ck_organization_revenues_importe"),
        sa.CheckConstraint(
            "ejercicio BETWEEN 1990 AND 2100",
            name="ck_organization_revenues_ejercicio",
        ),
        # Un ejercicio se factura una vez. Dos filas del mismo año son un
        # error de carga y romperían el «máximo de los tres últimos».
        sa.UniqueConstraint(
            "organization_id", "ejercicio", name="uq_organization_revenues_ejercicio"
        ),
    )

    op.create_table(
        "organization_references",
        *_columnas_comunes(),
        sa.Column("organo", sa.Text, nullable=False),
        sa.Column("importe_eur", sa.Numeric(16, 2), nullable=True),
        sa.Column("anio", sa.Integer, nullable=False),
        sa.Column("tecnologia", sa.Text, nullable=True),
        # `licitaciones.id_externo` cuando la referencia salió de la propia
        # plataforma. Sin FK a propósito: el histórico de una organización
        # empieza antes de que use TenderFlow y una FK obligaría a tirar esas
        # referencias, que son justo las que acreditan más antigüedad.
        sa.Column("expediente_id", sa.Text, nullable=True),
        sa.CheckConstraint(
            "importe_eur IS NULL OR importe_eur >= 0",
            name="ck_organization_references_importe",
        ),
        sa.CheckConstraint("anio BETWEEN 1990 AND 2100", name="ck_organization_references_anio"),
    )

    op.create_table(
        "organization_team_profiles",
        *_columnas_comunes(),
        sa.Column("rol", sa.Text, nullable=False),
        sa.Column("anios", sa.Numeric(5, 2), nullable=False),
        sa.Column("cantidad", sa.Integer, nullable=False),
        sa.CheckConstraint(
            "anios >= 0 AND anios <= 60", name="ck_organization_team_profiles_anios"
        ),
        sa.CheckConstraint("cantidad >= 1", name="ck_organization_team_profiles_cantidad"),
    )

    for tabla in _TABLAS:
        # Toda lectura del perfil es «dame el de esta organización»: el índice
        # por `organization_id` es el único acceso que estas tablas reciben.
        op.execute(f"CREATE INDEX ix_{tabla}_org ON {tabla} (organization_id)")
        _protect_table(tabla)


def downgrade() -> None:
    if not _is_postgres():
        return
    for tabla in reversed(_TABLAS):
        op.execute(f"DROP INDEX IF EXISTS ix_{tabla}_org")
        op.drop_table(tabla)
