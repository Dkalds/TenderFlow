"""v115: ``licitaciones.organo_id`` — el órgano deja de ser una cadena (C1.2).

Qué hace
--------
Añade la columna, nullable, con clave foránea a ``organos`` (``v114``). **No
rellena nada**: el backfill lo hace ``scripts/backfill_organos.py``, por lotes y
con delta medido.

Por qué el backfill no va aquí
------------------------------
Resolver 706.000 filas de texto libre contra un maestro que arranca **vacío**
significa, en la práctica, construir el maestro: normalizar cada
``organo_contratacion``, agrupar, decidir la grafía canónica y encolar las
dudosas. Eso no es un ``UPDATE``, es un proceso con criterio, y meterlo en una
migración tiene tres problemas concretos:

1. Una migración que tarda una hora bloquea el despliegue entero.
2. Un error a mitad deja el maestro a medias y sin forma de reanudar.
3. El delta —cuántos órganos resultan, cuántas fusiones, cuántas dudas— hay que
   **mirarlo** antes de que la analítica empiece a agrupar por él, y una
   migración no da ocasión de mirar nada.

De ahí la separación: la migración abre el hueco, el script lo llena en ventana
y quien lo ejecuta ve el resultado.

Por qué nullable, y por qué se queda así
----------------------------------------
Un expediente cuyo órgano no resuelve **sigue siendo un expediente válido**. Lo
que no puede es desaparecer de la analítica, así que durante el backfill —y
después, para las fuentes que nunca resuelvan— la agrupación es dual: por
``organo_id`` cuando lo hay, por texto normalizado cuando no. `NOT NULL` habría
obligado a inventar un órgano «desconocido» y a que todo lo no resuelto se
agregara junto, que es peor que no agrupar.

Riesgo
------
Alto: es la tabla núcleo (~706k filas medidas el 2026-09-06). La columna es
aditiva y nullable, así que el ``ALTER`` no reescribe la tabla en Postgres 11+.
El índice se crea aquí y no en el script porque el backfill lo va a usar en cada
lote.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v115_lic_organo_id"
down_revision: str | Sequence[str] | None = "v114_organos_master"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNA = "organo_id"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    op.add_column("licitaciones", sa.Column(COLUMNA, sa.Integer, nullable=True))
    op.create_foreign_key(
        "fk_licitaciones_organo",
        "licitaciones",
        "organos",
        [COLUMNA],
        ["organo_id"],
        # `SET NULL` y no `CASCADE`: fusionar o borrar un órgano del maestro no
        # puede llevarse por delante sus expedientes. La fila vuelve a "sin
        # resolver", que es un estado que la lectura dual ya sabe tratar.
        ondelete="SET NULL",
    )
    # Índice parcial: arranca vacío y crece con el backfill. La analítica filtra
    # `organo_id IS NOT NULL` para el camino resuelto, así que el parcial es
    # exactamente la población que consulta y ocupa menos que el completo.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_lic_organo_id "
        "ON licitaciones (organo_id) WHERE organo_id IS NOT NULL"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP INDEX IF EXISTS idx_lic_organo_id")
    op.drop_constraint("fk_licitaciones_organo", "licitaciones", type_="foreignkey")
    op.drop_column("licitaciones", COLUMNA)
