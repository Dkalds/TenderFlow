"""v93: cada decisión guarda el score y la banda que la motivaron.

TenderFlow vende priorización —«Radar ordena la bandeja diaria por score de
oportunidad»— y hasta esta revisión era **imposible saber si acierta**, ni
siquiera con acceso total a la base de datos.

El score no se persiste en ninguna parte: ``services/analytics/scoring.py`` lo
calcula en vivo sobre el estado de hoy (percentiles del universo puntuable
actual, competencia de 24 meses, ``predicciones_baja``) y con los pesos del
perfil del usuario, que éste puede cambiar cuando quiera. Y las dos decisiones
que sí se guardan server-side no anotaban la puntuación que el usuario tenía
delante: ``radar_dismissals`` guardaba ``(user_key, id_externo, created_at)`` y
``pursuits`` guarda estado, decisión, precio ofertado y desenlace won/lost, pero
ni score ni banda.

Consecuencia: nadie puede cruzar «lo que el Radar puso arriba» con «lo que el
equipo ganó» ni con «lo que descartó en dos segundos». Y no es un hueco que se
pueda tapar más tarde — **el score de ayer ya no existe**, así que cada día sin
esta columna es un día de evidencia perdida sobre la promesa central del
producto.

Con estas cuatro columnas, dos preguntas se responden con SQL y sin telemetría
de cliente:

- distribución de bandas de lo descartado (si el grueso de los descartes son
  «Caliente», el orden no está sirviendo);
- win rate de los pursuits abiertos desde cada banda de entrada.

Por qué NULLables, y por qué no hay backfill
--------------------------------------------
Las filas anteriores a esta revisión no tienen score que recuperar y no se puede
reconstruir: dependía del universo y del perfil de aquel día. ``NULL`` significa
aquí «no se supo», que es la verdad; rellenarlas con el score de hoy fabricaría
exactamente la evidencia que estas columnas existen para recoger. Los
consumidores tienen que filtrar por ``IS NOT NULL`` y declarar la cobertura,
igual que hace ``CoberturaMetricaDTO`` en el resto del producto.

Por qué no se guarda la versión de los pesos
--------------------------------------------
Sería lo correcto para poder reproducir un score, pero **no existe tal versión**
en el repositorio: el perfil de scoring no lleva sello ni número de revisión, así
que no hay nada que copiar. Inventar una columna vacía sería peor que no
tenerla. Queda anotado como lo que falta para cerrar del todo la trazabilidad;
la decisión de versionar el perfil es de producto, no de esta migración.

``banda`` es TEXT y no un enum de Postgres: el vocabulario
(``Caliente``/``Atractiva``/``Tibia``/``Descarte``) lo fija ``_band()`` en
``services/analytics/scoring.py`` y ahí es donde tiene que poder moverse. Un
``CHECK`` con los cuatro literales congelaría en el schema una decisión de
producto y obligaría a migrar la tabla para renombrar una banda.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v93_decisiones_guardan_su_score
Revises: v92_lic_clave_canonica_index
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v93_decisiones_guardan_su_score"
down_revision: str | Sequence[str] | None = "v92_lic_clave_canonica_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (tabla, columna del score, columna de la banda). En `pursuits` llevan sufijo
#: `_al_abrir` porque esa tabla tiene ciclo de vida: un `score` a secas se leería
#: como "el score actual del expediente", que es justo lo que NO es.
_COLUMNAS: tuple[tuple[str, str, str], ...] = (
    ("radar_dismissals", "score", "banda"),
    ("pursuits", "score_al_abrir", "banda_al_abrir"),
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    for tabla, col_score, col_banda in _COLUMNAS:
        # `ADD COLUMN` de una columna NULLable sin default es instantáneo en
        # Postgres (solo toca el catálogo), así que no hace falta ni
        # `CONCURRENTLY` ni relajar el `statement_timeout`.
        op.execute(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {col_score} SMALLINT")
        op.execute(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {col_banda} TEXT")


def downgrade() -> None:
    if not _is_postgres():
        return
    for tabla, col_score, col_banda in _COLUMNAS:
        op.execute(f"ALTER TABLE {tabla} DROP COLUMN IF EXISTS {col_banda}")
        op.execute(f"ALTER TABLE {tabla} DROP COLUMN IF EXISTS {col_score}")
