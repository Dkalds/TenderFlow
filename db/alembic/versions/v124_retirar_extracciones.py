"""v124: `extracciones` se retira, con vista de compatibilidad (C4.6).

Revision ID: v124_retirar_extracciones
Revises: v123_notas_y_menciones
Create Date: 2026-09-07

Cuatro tablas de salud, y una de ellas sin lector
------------------------------------------------
La ingesta tenía cuatro tablas que decían cosas parecidas: `extracciones`,
`extraction_runs`, `source_ingestion_health` y `ops_events`. Al medirlo,
`extracciones` resultó ser **una tabla que nadie lee**:

- la escribe `db/upsert.py::log_extraccion`, desde dos sitios de
  `scheduler/pipeline_runs.py`;
- la lee `ExtractionRunRepository.load_extracciones`, envuelta por
  `services/extraction_runs.load_extracciones`, y **ninguna ruta, job, script ni
  test llama a ninguna de las dos**;
- `scheduler/healthcheck.py` nunca la consulta: sus preguntas las responde con
  `extraction_runs` (último run), `source_ingestion_health` (estado por fuente)
  y `ops_events` (historial de eventos).

Y lo que escribía no se pierde al retirarla, porque ya se escribía dos veces:
`run_connector` deja los contadores por fuente en `source_ingestion_health` y
`record_run` deja las métricas del run en `extraction_runs`. `extracciones` era
un tercer registro del mismo hecho, con menos columnas.

Quedan las dos que el plan pide como par: **`source_ingestion_health` (estado
actual por fuente) y `ops_events` (historial)**, con `extraction_runs` como
detalle por pasada del pipeline.

Por qué renombrar y no borrar
-----------------------------
La tabla se renombra a `extracciones_retirada` y una **vista** ocupa su nombre.
Las dos consecuencias son deliberadas:

- **Nada se destruye.** El histórico sigue ahí y una consulta manual que use el
  nombre de siempre devuelve exactamente las mismas filas que devolvía.
- **Deja de crecer.** Una vista no acepta `INSERT` sin un trigger, así que si
  quedara algún camino de escritura sin retirar, fallaría en voz alta en vez de
  seguir llenando en silencio una tabla que nadie lee.

Es la «vista de compatibilidad durante una ola» que pide C4.6. La ola siguiente
la borra junto con la tabla renombrada; hasta entonces, revertir es un
`DROP VIEW` y un `RENAME` de vuelta.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v124_retirar_extracciones"
down_revision: str | Sequence[str] | None = "v123_notas_y_menciones"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    inspector = sa.inspect(op.get_bind())
    tablas = set(inspector.get_table_names())
    if "extracciones" not in tablas or "extracciones_retirada" in tablas:
        # Ya aplicada, o el entorno no tiene la tabla: no hay nada que retirar.
        return

    op.execute("ALTER TABLE extracciones RENAME TO extracciones_retirada")
    op.execute("CREATE VIEW extracciones AS SELECT * FROM extracciones_retirada")
    op.execute(
        "COMMENT ON VIEW extracciones IS "
        "'Vista de compatibilidad (C4.6, v124). La tabla real es "
        "extracciones_retirada y ya no se escribe: los contadores por fuente "
        "viven en source_ingestion_health y las metricas por pasada en "
        "extraction_runs.'"
    )
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenderflow_app') THEN "
        "GRANT SELECT ON extracciones TO tenderflow_app; "
        "END IF; END $$"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP VIEW IF EXISTS extracciones")
    op.execute("ALTER TABLE IF EXISTS extracciones_retirada RENAME TO extracciones")
