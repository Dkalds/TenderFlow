"""v169: el descarte guarda el desglose del score que lo motivó.

Revision ID: v169_radar_dismissals_desglose
Revises: v168_mv_canonicas_universo_producto
Create Date: 2026-11-02

Qué falta hoy
-------------
``v93`` sella en el descarte el ``score`` y la ``banda`` que el usuario tenía
delante, y ``v110`` sella en la oportunidad, además, el **desglose** por
dimensión (``pursuits.desglose_al_abrir``). La propuesta de pesos
(``services/pursuits.py::get_weights_proposal``) compara desgloses dimensión a
dimensión, así que solo puede aprender de las oportunidades: de los cierres
ganados y perdidos, que en el piloto son nueve en dos meses.

El triaje es mucho más abundante y dice justo lo que el Radar intenta acertar:
qué abre el equipo y qué descarta. Lo que se abre ya trae desglose; lo que se
descarta, no. Esta columna es la otra mitad: con ella, «abiertas frente a
descartadas» es una base para proponer pesos que se llena en semanas.

Qué hace
--------
``desglose`` (TEXT, NULL) en ``radar_dismissals``: el JSON del desglose, con la
misma forma y el mismo serializador que ``pursuits.desglose_al_abrir``. TEXT y
no JSONB por la misma razón que ``v110``: nadie consulta dentro del desglose
desde SQL, se lee entero en Python.

``NULL`` en las filas existentes y en los clientes que no lo mandan: el
desglose se calcula en vivo sobre el universo del día, así que no se puede
reconstruir después. La propuesta cuenta solo las filas que lo traen y dice
sobre cuántas habla.

Nullable y sin default: ``ADD COLUMN`` es solo metadatos, sin reescribir filas
ni lock largo (mismo razonamiento que ``v103``).

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v169_radar_dismissals_desglose"
down_revision: str | Sequence[str] | None = "v168_mv_canonicas_universo_producto"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute("ALTER TABLE radar_dismissals ADD COLUMN IF NOT EXISTS desglose TEXT")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("ALTER TABLE radar_dismissals DROP COLUMN IF EXISTS desglose")
