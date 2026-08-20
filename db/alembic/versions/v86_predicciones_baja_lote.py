"""v86: ``predicciones_baja`` preparada para servir por lote.

Revision ID: v86_predicciones_baja_lote
Revises: v85_lic_procedimiento_tramitacion
Create Date: 2026-08-18

El expediente no es la unidad sobre la que se puja: el lote lo es. En un
expediente de 30 lotes una única cifra de baja agregada no le dice al licitador
a qué lote entrar ni con qué margen -- promedia justo la información que el
pliego separa. ``predicciones_baja`` nació con PK ``licitacion_id`` (v41 en
SQLite, v55 en Postgres), y esa PK **fija la granularidad del serving en el
esquema**: mientras exista, dos filas del mismo expediente son imposibles y
ningún modelo por lote puede materializarse por mucho que se entrene.

Esta revisión abre esa puerta **sin cruzarla**. El ítem de backlog condiciona
sustituir el modelo agregado a haber medido antes el ``mae_p50`` por lote
contra el agregado actual; esa medida no está hecha (requiere Postgres con
histórico y un modelo entrenado), así que aquí solo se instala la
infraestructura y el camino por defecto queda **intacto**.

Por qué la PK ``(licitacion_id, lote_id)`` del enunciado no se puede escribir
-----------------------------------------------------------------------------
El criterio pedía PK ``(licitacion_id, lote_id)`` con ``lote_id`` *nullable*
para los expedientes de lote único. En Postgres eso es contradictorio: una
PRIMARY KEY implica NOT NULL en todas sus columnas, así que una columna
nullable no puede formar parte de ella. Las dos salidas reales son:

1. ``lote_id`` NOT NULL con un centinela (``0``/``-1``) para "el expediente
   entero". Obliga a renunciar a la FK contra ``lotes(id)`` o a inventar una
   fila centinela en ``lotes``: un valor que miente sobre el dominio para
   satisfacer una restricción de forma, y que además haría que cualquier JOIN
   descuidado contra ``lotes`` mezclase el agregado con los lotes reales.
2. Un **índice único** sobre ``(licitacion_id, COALESCE(lote_id, -1))``, que
   da exactamente la misma garantía —como mucho una predicción por lote, y
   como mucho una agregada por expediente— dejando ``lote_id`` NULL en el caso
   agregado, que es lo que el dominio dice de verdad.

Se elige (2). ``lotes.id`` es un serial positivo (v65), así que ``-1`` no
puede colisionar jamás con un lote real, y el índice es además utilizable como
índice de búsqueda por ``licitacion_id`` (columna líder) — que es como lee
``services.ml.scoring.prediccion_baja``.

Por qué esta revisión **no** borra la PK actual
-----------------------------------------------
Borrar ``predicciones_baja_pkey`` es barato en disco (es un cambio de catálogo
más el borrado de su índice) pero caro en semántica: ``services/ml/scoring.py``
materializa el batch con ``INSERT ... ON CONFLICT (licitacion_id) DO UPDATE``,
y la inferencia del árbitro de ``ON CONFLICT`` exige un índice único **sobre
exactamente esa columna**. En el instante en que la PK desaparece, el upsert
nocturno del camino agregado revienta — el camino que este ítem obliga
explícitamente a conservar como default hasta que la comparación de ``mae_p50``
diga otra cosa.

Así que el reparto de trabajo es deliberado:

- **aquí** (barato de esperar, caro de construir): añadir la columna y
  construir el índice único compuesto ``CONCURRENTLY``, sin bloquear al batch
  ni a la API. Mientras la PK siga viva este índice es redundante —PK sobre
  ``licitacion_id`` implica unicidad de ``(licitacion_id, cualquier cosa)``—,
  y esa redundancia es justamente el objetivo: cuando llegue el switch, la
  unicidad ya está garantizada y no hay ni un instante sin protección.
- **en el commit del switch** (caro de esperar, barato de ejecutar): un
  ``ALTER TABLE ... DROP CONSTRAINT predicciones_baja_pkey`` —una sentencia de
  catálogo, ACCESS EXCLUSIVE de milisegundos, que conviene lanzar con
  ``lock_timeout`` para que encole en vez de bloquear a media BD— junto al
  cambio de una línea en ``scoring.py``:
  ``ON CONFLICT (licitacion_id, COALESCE(lote_id, -1))`` (Postgres infiere el
  árbitro sobre índices de expresión). El estado final es una tabla sin PRIMARY
  KEY y con índice único de expresión; nada depende hoy de que la constraint se
  llame PK, solo de que la unicidad exista.

La lección de v68 y por qué esta migración no cae en ella
----------------------------------------------------------
v68 añadió una columna **generada** a ``licitaciones`` y reescribió 1,6 M filas
con lock exclusivo durante media hora. Aquí no ocurre nada de eso:

- ``ADD COLUMN lote_id INTEGER`` es **nullable y sin DEFAULT**, luego es
  metadata-only: Postgres no reescribe ni una página (mismo argumento que v83 y
  que el ``lote_id`` de ``adjudicaciones`` en v65).
- No hay columna generada, ni ``SET NOT NULL``, ni default volátil, ni backfill
  dentro de la migración. Las filas existentes quedan con ``lote_id`` NULL, que
  es exactamente su significado correcto: "predicción del expediente entero".
- La FK se añade ``NOT VALID`` y se valida después en ``autocommit_block``:
  ``VALIDATE CONSTRAINT`` toma SHARE UPDATE EXCLUSIVE, que no bloquea lecturas
  ni escrituras. Sobre una columna recién creada la validación no puede fallar,
  pero el patrón evita el ACCESS EXCLUSIVE prolongado si un día se re-ejecuta
  sobre una tabla ya poblada de ``lote_id``.
- El índice único va ``CONCURRENTLY``, como v66/v69/v79. Si la construcción
  falla deja un índice ``INVALID`` que hay que borrar a mano antes de
  reintentar: es el precio conocido de no bloquear escrituras.

``predicciones_baja`` es además órdenes de magnitud más pequeña que
``licitaciones`` (el batch puntúa como mucho ``limit`` licitaciones abiertas
por corrida y nunca purga), así que ni siquiera se está pagando el caso malo.
La disciplina se mantiene igual porque la tabla la escribe un cron y la lee la
API: un lock de minutos aquí es un incidente, no una molestia.

``ON DELETE CASCADE`` y no ``SET NULL``
----------------------------------------
v65 usó ``SET NULL`` para ``adjudicaciones.lote_id`` porque una adjudicación
huérfana de lote sigue siendo un hecho real. Aquí es al revés: una predicción
cuyo lote desaparece no significa nada, y ``SET NULL`` la convertiría en una
predicción *agregada* del expediente, chocando contra la fila agregada legítima
en el índice único. CASCADE es la única opción que no fabrica datos falsos.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v86_predicciones_baja_lote"
down_revision: str | Sequence[str] | None = "v85_lic_procedimiento_tramitacion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Centinela del agregado en el índice único. `lotes.id` es un serial positivo
# (v65), así que -1 no puede colisionar con ningún lote real.
_SENTINELA_AGREGADO = -1

_UQ = "uq_pred_baja_lic_lote"
_FK = "fk_pred_baja_lote"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    # Metadata-only: nullable y sin DEFAULT (ver docstring, lección de v68).
    op.add_column("predicciones_baja", sa.Column("lote_id", sa.Integer, nullable=True))
    op.execute(
        f"ALTER TABLE predicciones_baja ADD CONSTRAINT {_FK} "
        "FOREIGN KEY (lote_id) REFERENCES lotes(id) ON DELETE CASCADE NOT VALID"
    )

    with op.get_context().autocommit_block():
        # SHARE UPDATE EXCLUSIVE: no bloquea al batch de scoring ni a la API.
        op.execute(f"ALTER TABLE predicciones_baja VALIDATE CONSTRAINT {_FK}")
        # La PK sobre `licitacion_id` sigue viva y hace redundante a este
        # índice HOY; existe para que el switch a granularidad de lote no tenga
        # ni un instante sin unicidad garantizada.
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_UQ} "
            "ON predicciones_baja "
            f"(licitacion_id, COALESCE(lote_id, {_SENTINELA_AGREGADO}))"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_UQ}")
    op.execute(f"ALTER TABLE predicciones_baja DROP CONSTRAINT IF EXISTS {_FK}")
    op.drop_column("predicciones_baja", "lote_id")
