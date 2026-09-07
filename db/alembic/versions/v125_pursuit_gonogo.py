"""v125: puntuación go/no-go ponderada en ``pursuits`` (C6.4, D30).

Qué corrige
-----------
``pursuits.decision`` es ``go | no_go | pending`` y ``decision_reason`` es texto
libre. Es decir: la decisión más cara del proceso —presentarse o no, con lo que
cuesta preparar una oferta— se registra como una etiqueta y un párrafo. No hay
forma de responder «¿en qué nos equivocamos al decidir?» porque no consta contra
qué se decidió.

Los cinco criterios
-------------------
Encaje estratégico, capacidad, competencia, rentabilidad y riesgo, de uno a
cinco. Son los de D30 y no una lista abierta: un formulario que cada equipo
amplía a su gusto deja de poder compararse consigo mismo el trimestre siguiente,
que es justo para lo que sirve puntuar.

Columnas
--------
==================== ======================================================
``gonogo_json``      Las cinco puntuaciones tal y como se pusieron. Se
                     guardan las **puntuaciones**, no sólo el total: sin
                     ellas, «45 sobre 100» no dice si el problema era el
                     precio o que no hay equipo.
``gonogo_total``     El total ponderado, 0-100, calculado con los pesos de
                     la organización **en el momento de puntuar**.
``gonogo_at``        Cuándo se puntuó.
==================== ======================================================

Por qué el total se congela y no se recalcula
---------------------------------------------
Los pesos son de la organización y cambian. Si el total se recalculara al
leerlo, cambiar un peso reescribiría el pasado: expedientes que se rechazaron
por debajo del umbral aparecerían por encima, y la revisión de decisiones —el
único motivo por el que esto existe— mediría contra un criterio que no era el
vigente cuando se decidió.

Dónde viven los pesos y el umbral
---------------------------------
En ``organizations.settings_json``, que ya existe y ya tiene lectura/escritura
transaccional (``update_settings``). No hacen falta ni tabla ni columna: son una
configuración de la organización, del mismo tipo que las que ya guarda ahí.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v125_pursuit_gonogo"
down_revision: str | Sequence[str] | None = "v124_pursuit_comments_menciones"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNAS = (
    ("gonogo_json", sa.Text),
    ("gonogo_total", sa.Numeric(5, 2)),
    ("gonogo_at", sa.Text),
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    inspector = sa.inspect(op.get_bind())
    if "pursuits" not in inspector.get_table_names():
        return
    existentes = {c["name"] for c in inspector.get_columns("pursuits")}
    for nombre, tipo in COLUMNAS:
        if nombre not in existentes:
            op.add_column("pursuits", sa.Column(nombre, tipo, nullable=True))
    op.execute(
        "ALTER TABLE pursuits ADD CONSTRAINT ck_pursuits_gonogo_total "
        "CHECK (gonogo_total IS NULL OR (gonogo_total >= 0 AND gonogo_total <= 100))"
    )
    # La métrica de `product-status` es «decisiones `go` por debajo del umbral»:
    # recorre los `go` puntuados. Parcial porque los sin puntuar —hoy, todos— no
    # entran nunca en esa consulta.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pursuits_gonogo "
        "ON pursuits (organization_id, decision) WHERE gonogo_total IS NOT NULL"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP INDEX IF EXISTS idx_pursuits_gonogo")
    op.execute("ALTER TABLE pursuits DROP CONSTRAINT IF EXISTS ck_pursuits_gonogo_total")
    for nombre, _ in COLUMNAS:
        op.execute(f"ALTER TABLE pursuits DROP COLUMN IF EXISTS {nombre}")
