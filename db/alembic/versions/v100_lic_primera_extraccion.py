"""v100: ``licitaciones.primera_extraccion`` — la clave canónica deja de moverse sola.

Qué corrige
-----------
La clave canónica de un contrato (``db.sql_fragments.clave_canonica_sql``) lleva
una componente temporal: el año-mes de ``coalesce(fecha_publicacion,
fecha_extraccion)``. Y el criterio que decide **cuál** de las filas gemelas se
publica (``_rango_canonico_sql`` / ``orden_canonico_sql``) desempata por
``coalesce(fecha_extraccion, '9999')``.

``fecha_extraccion`` no es una fecha del contrato: es cuándo lo vio el scraper
por última vez, y ``db/upsert.py`` la **reescribe en cada pasada**. Para las
filas sin ``fecha_publicacion`` —que son muchas: PSCP no la trae en la mayoría
de sus avisos— eso significa que:

- el año-mes de la clave cambia solo al cruzar un mes, así que una fila deja de
  agrupar con sus gemelas y el mismo contrato aparece dos veces en un hub; y
- el desempate cambia de orden, así que la canónica de un grupo puede cambiar
  entre refrescos y con ella la **URL** que publica el sitemap. Un sitemap
  existe precisamente para que eso no pase: Search Console lo reporta como
  error de cobertura y las señales de ranking se reparten entre dos URLs.

La corrección es que la componente temporal salga de un dato inmutable. Esta
revisión crea ``primera_extraccion``, la rellena con el primer avistamiento
conocido de cada fila, y a partir de aquí los fragmentos la prefieren.

De dónde sale el relleno (y el matiz honesto)
---------------------------------------------
El plan pedía ``MIN(fecha_extraccion)`` de ``licitaciones_history``. Esa columna
**no existe** en esa tabla: su esquema (``baseline002``) es ``id_externo``,
``captured_at``, ``source``, ``snapshot_json``, ``changed_fields``. El valor
histórico de ``fecha_extraccion`` sólo está dentro de ``snapshot_json``, y
castear ~692k blobs JSON —algunos de linaje antiguo, sin garantía de forma— es
caro y frágil para un backfill de una sola pasada.

Lo que sí hay es ``captured_at``: el instante en que se capturó el primer cambio
de esa fila, o sea un momento en el que la fila **ya existía**. No es la primera
extracción (la historia se escribe a partir de la segunda pasada), pero es una
cota superior de ella y siempre anterior o igual a la ``fecha_extraccion``
actual. Por eso el relleno es::

    LEAST(fecha_extraccion, MIN(captured_at))

que para una fila sin historial devuelve ``fecha_extraccion`` —``LEAST`` ignora
los ``NULL``— y para una fila con historial devuelve algo estrictamente mejor
que lo que había. En los dos casos el valor queda **fijo**, que es la propiedad
que se persigue; la exactitud del instante no cambia ninguna decisión, porque el
fragmento sólo mira ``substr(..., 1, 7)``.

Lo que esta revisión NO hace, y hay que coordinar
-------------------------------------------------
**``db/upsert.py`` tiene que escribir esta columna, y sólo en el INSERT.** Si la
escribiera también en el ``ON CONFLICT DO UPDATE`` volvería a moverse en cada
pasada y esta revisión no habría servido de nada; si no la escribe en absoluto,
las filas nuevas la traen a ``NULL``. Ese caso está cubierto: los fragmentos
mantienen ``fecha_extraccion`` como último término del ``coalesce``, así que una
fila con la columna vacía se comporta exactamente como antes de esta revisión.
El cambio en el upsert es aditivo y puede llegar después; hasta entonces el
beneficio sólo lo tiene el histórico ya rellenado.

Coste
-----
``ADD COLUMN`` de una columna anulable sin default no reescribe la tabla
(Postgres 11+): es instantáneo y no toma lock largo. El ``UPDATE`` del backfill
sí toca las ~692k filas — mismo orden que el de ``v91``, que reescribió 645k— y
por eso va con ``statement_timeout = 0``. Deja bloat, como cualquier ``UPDATE``
masivo en Postgres; si tras aplicarlo los tiempos suben, el siguiente paso es un
``VACUUM (ANALYZE) licitaciones`` desde el panel, fuera de Alembic (no se puede
correr dentro de una migración).

Esto **no** es la trampa de ``v68``: aquélla añadió una columna GENERADA, que sí
obliga a reescribir la tabla entera bajo lock exclusivo. Aquí la columna es
normal y el relleno va en un ``UPDATE`` aparte.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v100_lic_primera_extraccion
Revises: v99_mv_canonicas_universo_ml
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v100_lic_primera_extraccion"
down_revision: str | Sequence[str] | None = "v99_mv_canonicas_universo_ml"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNA = "primera_extraccion"

#: El relleno. ``LEAST`` ignora los ``NULL`` en Postgres, así que una fila sin
#: historial se queda con su ``fecha_extraccion`` sin necesidad de ``COALESCE``.
BACKFILL_SQL = (
    "UPDATE licitaciones l SET primera_extraccion = LEAST("
    "l.fecha_extraccion, "
    "(SELECT MIN(h.captured_at) FROM licitaciones_history h "
    "WHERE h.id_externo = l.id_externo)) "
    "WHERE l.primera_extraccion IS NULL"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.add_column("licitaciones", sa.Column(COLUMNA, sa.Text, nullable=True))
    # El backfill recorre las ~692k filas y el índice de `licitaciones_history`
    # (`idx_hist_externo`, baseline002) resuelve cada subconsulta; aun así pasa
    # de largo los 30 s del rol de la API.
    op.execute("SET statement_timeout = 0")
    op.execute(BACKFILL_SQL)
    # Las estadísticas de la columna nueva las necesita el planificador para el
    # índice funcional que crea `v101` sobre una expresión que la incluye.
    op.execute("ANALYZE licitaciones")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.drop_column("licitaciones", COLUMNA)
