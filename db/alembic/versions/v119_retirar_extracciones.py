"""v119: retira ``extracciones``, la cuarta tabla de salud (C4.6).

Qué había
---------
Cuatro tablas contaban lo mismo desde ángulos distintos:

======================== =================================================
``extraction_runs``      Un run de la pipeline: cuándo, cuánto tardó, con
                         qué estado, cuántas licitaciones y adjudicaciones.
``source_ingestion_health`` Estado **actual** por fuente: último run, si
                         salió bien, cuántos avisos trajo.
``ops_events``           Historial operativo: tripwires de persistencia.
``extracciones``         Por fuente y run: ``nuevas``, ``actualizadas``,
                         ``total_revisadas`` y una nota en texto libre.
======================== =================================================

Por qué se retira la cuarta
---------------------------
No la lee **nadie**. El único lector —``ExtractionRunRepository.load_extracciones``
y su envoltorio en ``services/extraction_runs.py``— no tiene consumidor: el
``dashboard/`` que lo llamaba ya no existe en el repo. ``scheduler/healthcheck.py``
no la consulta en ninguna de sus comprobaciones.

Y lo que escribía ya estaba escrito dos veces: ``nuevas`` y ``actualizadas``
llegan a ``extraction_runs`` por ``record_run``, y el recuento por fuente a
``source_ingestion_health`` por ``run_connector``. Los tres escritores de
``log_extraccion`` corrían **después** de esas dos escrituras, con los mismos
números.

Una tabla que sólo se escribe no es un registro: es un coste de escritura en el
camino caliente de la ingesta y una respuesta más que dar cuando alguien
pregunta «¿dónde miro cuántas trajo PLACSP ayer?».

Qué contesta ahora cada pregunta
--------------------------------
- «¿Corrió la pipeline, cuándo y con qué resultado?» → ``extraction_runs``.
- «¿Qué trajo cada fuente en su último run?» → ``source_ingestion_health``.
- «¿Qué pasó en la infraestructura?» → ``ops_events``.

Qué hace esta revisión
----------------------
**No borra nada.** Renombra la tabla a ``extracciones_retirada`` y deja una
vista ``extracciones`` encima durante una ola:

- lo que siga haciendo ``SELECT`` sigue viendo el histórico entero;
- lo que intente ``INSERT`` falla en voz alta, que es justo lo que se quiere de
  un escritor que se creía retirado. Una vista simple sin ``INSTEAD OF`` no es
  insertable en Postgres, y ese error es la señal.

El ``DROP`` definitivo va en una revisión posterior, cuando la ola haya pasado.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v119_retirar_extracciones"
down_revision: str | Sequence[str] | None = "v118_webhook_deliveries_reintento"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLA_RETIRADA = "extracciones_retirada"
VISTA = "extracciones"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    inspector = sa.inspect(op.get_bind())
    tablas = set(inspector.get_table_names())
    if TABLA_RETIRADA in tablas:
        return
    if VISTA not in tablas:
        # Instalación nueva: la tabla nunca existió y no hay nada que retirar.
        return

    op.execute(f"ALTER TABLE {VISTA} RENAME TO {TABLA_RETIRADA}")
    # El índice se renombra con la tabla en Postgres, pero su nombre
    # (`idx_extr_fecha`) queda apuntando a algo que ya no se consulta. Se deja:
    # borrarlo obligaría a recrearlo en el downgrade sin ganar nada.
    op.execute(
        f"CREATE VIEW {VISTA} AS SELECT id, fecha, fuente, nuevas, actualizadas, "
        f"total_revisadas, notas FROM {TABLA_RETIRADA}"
    )
    op.execute(
        f"COMMENT ON VIEW {VISTA} IS "
        "'Retirada en v119 (C4.6): compatibilidad de lectura durante una ola. "
        "Escribir aquí falla a propósito; los datos vivos están en "
        "extraction_runs y source_ingestion_health.'"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(f"DROP VIEW IF EXISTS {VISTA}")
    op.execute(f"ALTER TABLE IF EXISTS {TABLA_RETIRADA} RENAME TO {VISTA}")
