"""v123: plantilla de go/no-go ponderada (C6.4, D30).

Revision ID: v123_go_no_go
Revises: v122_pursuit_tasks
Create Date: 2026-09-07

Qué corrige
-----------
`pursuits.decision` guarda `go | no_go` y un `decision_reason` de texto libre.
Eso registra **qué** se decidió y no **por qué**, así que dos meses después nadie
puede responder «¿en qué nos equivocamos al decidir?» — que es la única pregunta
que convierte un histórico de decisiones en aprendizaje.

Cinco criterios fijos, pesos por organización (D30)
---------------------------------------------------
Los criterios son los mismos para todas: encaje estratégico, capacidad,
competencia, rentabilidad y riesgo. Dejar que cada organización los defina daría
un histórico incomparable dentro de la propia organización en cuanto alguien
edite la lista, y comparar es justo para lo que sirve.

Lo que sí varía es el **peso**: una consultora de nicho pondera encaje por
encima de rentabilidad, y una de volumen al revés. Los pesos viven en
`go_no_go_weights`, uno por organización y criterio, y son de owner/admin.

`riesgo` puntúa invertido — 5 es *poco* riesgo — para que la suma ponderada
tenga una sola dirección: más alto, mejor. Sin eso, el umbral tendría que saber
qué criterios restan, y esa lógica acabaría duplicada en cada consumidor.

Por qué la puntuación es una tabla y no columnas en `pursuits`
--------------------------------------------------------------
Cinco columnas más `total` en la tabla núcleo obligarían a migrar `pursuits`
cada vez que se toque un criterio, y `pursuits` es la tabla que más caminos de
escritura tiene. Una fila por (pursuit, criterio) además deja registrar el
*motivo* de cada puntuación, que es donde está el aprendizaje.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v123_go_no_go"
down_revision: str | Sequence[str] | None = "v122_pursuit_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Los cinco de D30. `riesgo` puntúa invertido (5 = poco riesgo).
CRITERIOS = ("encaje", "capacidad", "competencia", "rentabilidad", "riesgo")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _protect_table(table: str) -> None:
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


def upgrade() -> None:
    if not _is_postgres():
        return
    existentes = set(sa.inspect(op.get_bind()).get_table_names())
    criterios_sql = str(CRITERIOS)

    if "go_no_go_weights" not in existentes:
        op.create_table(
            "go_no_go_weights",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "organization_id",
                sa.Integer,
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("criterio", sa.Text, nullable=False),
            # Peso relativo. No se normaliza en la BD: normalizar aquí obligaría
            # a reescribir las cinco filas en cada edición y dejaría estados
            # intermedios que no suman 1. La normalización va al leer.
            sa.Column("peso", sa.Float, nullable=False, server_default="1"),
            sa.Column("updated_at", sa.Text, nullable=False, server_default=sa.text("NOW()")),
            sa.CheckConstraint("peso >= 0", name="ck_go_no_go_weights_peso"),
            sa.CheckConstraint("criterio IN " + criterios_sql, name="ck_go_no_go_weights_criterio"),
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_go_no_go_weights "
            "ON go_no_go_weights(organization_id, criterio)"
        )
        _protect_table("go_no_go_weights")

    if "go_no_go_scores" not in existentes:
        op.create_table(
            "go_no_go_scores",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column(
                "pursuit_id",
                sa.Integer,
                sa.ForeignKey("pursuits.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "organization_id",
                sa.Integer,
                sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("criterio", sa.Text, nullable=False),
            sa.Column("puntuacion", sa.Integer, nullable=False),
            # El aprendizaje está aquí: «capacidad 2 porque no tenemos perfil
            # SAP BW» es lo que se relee al revisar una decisión fallida.
            sa.Column("motivo", sa.Text, nullable=True),
            sa.Column(
                "author_user_id",
                sa.Integer,
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_at", sa.Text, nullable=False, server_default=sa.text("NOW()")),
            sa.Column("updated_at", sa.Text, nullable=False, server_default=sa.text("NOW()")),
            sa.CheckConstraint("puntuacion BETWEEN 1 AND 5", name="ck_go_no_go_scores_puntuacion"),
            sa.CheckConstraint("criterio IN " + criterios_sql, name="ck_go_no_go_scores_criterio"),
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_go_no_go_scores "
            "ON go_no_go_scores(pursuit_id, criterio)"
        )
        _protect_table("go_no_go_scores")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP TABLE IF EXISTS go_no_go_scores CASCADE")
    op.execute("DROP TABLE IF EXISTS go_no_go_weights CASCADE")
