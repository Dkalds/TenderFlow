"""v110: la oportunidad se abre por lote, y guarda el desglose que la motivó.

Dos cosas que el producto prometía y el esquema impedía.

1. Pujar por lote (S3.1 / D12)
------------------------------
``pursuits`` nació única por ``(organization_id, licitacion_id)``
(``uq_pursuits_org_licitacion``, v61), así que un expediente dividido en lotes
—que es como se contrata de verdad en España desde que la LCSP 9/2017 hizo
regla la división— solo admitía **una** oportunidad. Un equipo que va a dos
lotes del mismo expediente, con precios, responsables y decisiones distintas,
no tenía dónde escribirlo.

Los lotes existen como entidad desde v65 y ``predicciones_baja`` ya los
distingue (v86). Esta revisión los lleva a la tabla donde el equipo trabaja.

Por qué la columna es ``lote_numero`` (TEXT) y no ``lote_id`` (FK a ``lotes``)
-----------------------------------------------------------------------------
El enunciado de D12 dice «``lote_id`` nullable con FK a ``lotes``», y **la FK
no se puede escribir**: ``lotes.id`` no es una identidad estable.
``db/upsert.py::replace_lotes`` reemplaza los lotes de un expediente con
``DELETE`` + ``INSERT`` en cada re-ingesta, así que cada pasada del scraper les
da ids nuevos. Con una FK contra esa columna, la re-ingesta nocturna haría una
de estas tres cosas, todas malas:

- ``ON DELETE CASCADE`` → **borra el pursuit**. El trabajo del equipo
  desaparece porque el scraper volvió a leer el mismo expediente.
- ``ON DELETE SET NULL`` → convierte una oportunidad *de un lote* en una
  oportunidad *del expediente entero*, que es un dato falso; y si ya existía la
  del expediente entero, choca contra el único parcial y **rompe la ingesta**.
- ``RESTRICT``/``NO ACTION`` → el ``DELETE`` de ``replace_lotes`` falla y
  **rompe la ingesta** de cualquier expediente con un pursuit por lote.

``adjudicaciones.lote_id`` sí puede llevar la FK (v65) porque se reescribe en
el mismo ciclo que ``lotes``: su ``lote_id`` nunca sobrevive a la renumeración.
Un pursuit es lo contrario — dato humano que tiene que sobrevivir a todas las
re-ingestas del expediente.

La identidad estable del lote es su clave de negocio, ``(licitacion_id,
numero)``, que ``uq_lotes_licitacion_numero`` (v65) ya protege y que
``replace_lotes`` conserva por construcción: el parser toma ``numero`` del
``cbc:ID`` del ``cac:ProcurementProjectLot`` y descarta el lote que no lo trae.
Por eso se persiste ``lote_numero``, y ``lote_id`` sigue siendo lo que viaja
por la API: el repositorio lo resuelve al escribir (``lote_id`` → ``numero``,
verificando que el lote sea de ese expediente) y lo re-resuelve al leer con un
LEFT JOIN por la clave de negocio. Si la re-ingesta renumera, la oportunidad
sigue apuntando al mismo lote real; si el lote desaparece del pliego, el JOIN
devuelve ``NULL`` en ``lote_id`` y la oportunidad conserva su ``lote_numero``,
que es exactamente la verdad: «se abrió para el lote 3, que ya no está
publicado».

Dos únicos parciales, no una unique con la columna dentro
---------------------------------------------------------
Mismo razonamiento que v65 para ``adjudicaciones``: en SQL ``NULL <> NULL``, así
que una ``UNIQUE (organization_id, licitacion_id, lote_numero)`` a secas
**perdería toda protección** para el caso sin lote —hoy el 100 % de las filas—
y la misma organización podría abrir el mismo expediente veinte veces. Por eso:

- ``uq_pursuits_org_lic_sin_lote`` (WHERE ``lote_numero IS NULL``): idéntica en
  efecto a la constraint de v61 que sustituye. ``NULL`` significa «expediente
  completo» y las filas existentes no cambian ni una.
- ``uq_pursuits_org_lic_lote`` (WHERE ``lote_numero IS NOT NULL``): protección
  nueva, por lote — permite dos oportunidades del mismo expediente en lotes
  distintos, y sigue haciendo idempotente abrir el mismo lote dos veces.

Los dos índices se construyen ``CONCURRENTLY`` **antes** de borrar la
constraint vieja (lección de v86): así no hay ni un instante en que la tabla
esté sin unicidad. La constraint no tiene nombre garantizado en todos los
entornos —v61 la creó inline y algunas bases se bootstrapearon por otro
camino—, así que se localiza también por su conjunto de columnas, como hizo v65.

2. El desglose que motivó la decisión (S3.3)
--------------------------------------------
v93 selló ``score_al_abrir`` y ``banda_al_abrir`` para poder responder si el
Radar prioriza bien. Con eso se mide el **resultado** (win rate por banda), pero
no se puede proponer un ajuste de pesos: para decir «la dimensión *margen* vale
más de lo que pesa» hace falta el valor de cada dimensión en el momento de
abrir, y eso es el ``desglose`` que ``services/analytics/scoring.py`` calcula en
vivo y tira.

Recalcularlo hoy sobre un pursuit cerrado hace seis meses daría otro número
—percentiles del universo actual, competencia de otros 24 meses, otros pesos—:
fabricaría justo la evidencia que se quiere medir. Igual que v93, la columna es
NULLable, no hay backfill, y ``NULL`` significa «no se supo». El consumidor
filtra por ``IS NOT NULL`` y declara su base (ADR-014).

TEXT y no JSONB: nadie consulta dentro del desglose desde SQL —se lee entero en
Python para promediar—, y TEXT es lo que ya usan ``pursuit_events.payload_json``
y ``user_profiles.weights_json`` para el mismo tipo de dato.

Coste de la revisión
--------------------
Las dos ``ADD COLUMN`` son NULLables y sin ``DEFAULT``: metadata-only en
Postgres, sin reescritura de tabla (misma lección de v68 que citan v83 y v86).
Los dos índices van ``CONCURRENTLY``, con el precio conocido: si la
construcción falla deja un índice ``INVALID`` que hay que borrar a mano antes de
reintentar.

DIALECT-GUARDED: solo actúa en Postgres.

Revision ID: v110_pursuits_lote_id
Revises: v109_watchlist_rules_campos
Create Date: 2026-09-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v110_pursuits_lote_id"
down_revision: str | Sequence[str] | None = "v109_watchlist_rules_campos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Único parcial del caso «expediente completo». Reproduce exactamente la
#: garantía de ``uq_pursuits_org_licitacion`` (v61) para las filas sin lote.
_UQ_SIN_LOTE = "uq_pursuits_org_lic_sin_lote"
#: Único parcial por lote: la protección nueva.
_UQ_CON_LOTE = "uq_pursuits_org_lic_lote"

_CONSTRAINT_VIEJA = "uq_pursuits_org_licitacion"

# La constraint de v61 se creó inline dentro de ``create_table``; en las bases
# que se bootstrapearon por otro camino puede llamarse de otra forma. Se busca
# por su conjunto de columnas, como hizo v65 con ``adjudicaciones``.
_DROP_UNIQUE_VIEJA = """
DO $$
DECLARE
    c_name text;
BEGIN
    SELECT tc.constraint_name INTO c_name
    FROM information_schema.table_constraints tc
    WHERE tc.table_name = 'pursuits'
      AND tc.constraint_type = 'UNIQUE'
      AND tc.constraint_name IN (
          SELECT constraint_name FROM information_schema.key_column_usage
          WHERE table_name = 'pursuits'
          GROUP BY constraint_name
          -- column_name es information_schema.sql_identifier: sin cast
          -- explícito no hay operador "=" contra text[].
          HAVING array_agg(column_name::text ORDER BY column_name)
                 = ARRAY['licitacion_id', 'organization_id']
      )
    LIMIT 1;
    IF c_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE pursuits DROP CONSTRAINT %I', c_name);
    END IF;
END $$;
"""

_RESTAURA_UNIQUE_VIEJA = (
    f"ALTER TABLE pursuits ADD CONSTRAINT {_CONSTRAINT_VIEJA} "
    "UNIQUE (organization_id, licitacion_id)"
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    # Metadata-only: NULLables y sin DEFAULT.
    op.execute("ALTER TABLE pursuits ADD COLUMN IF NOT EXISTS lote_numero TEXT")
    op.execute("ALTER TABLE pursuits ADD COLUMN IF NOT EXISTS desglose_al_abrir TEXT")

    with op.get_context().autocommit_block():
        # Primero los índices nuevos, después el DROP de la constraint vieja:
        # entre las dos sentencias la tabla está protegida por partida doble,
        # nunca por ninguna.
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_UQ_SIN_LOTE} "
            "ON pursuits (organization_id, licitacion_id) WHERE lote_numero IS NULL"
        )
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_UQ_CON_LOTE} "
            "ON pursuits (organization_id, licitacion_id, lote_numero) "
            "WHERE lote_numero IS NOT NULL"
        )

    op.execute(_DROP_UNIQUE_VIEJA)


def downgrade() -> None:
    if not _is_postgres():
        return
    # La constraint vieja vuelve primero: si alguna organización abrió dos
    # lotes del mismo expediente, este ADD CONSTRAINT falla y el downgrade se
    # detiene aquí, que es lo correcto — bajar borraría trabajo del equipo.
    op.execute(_RESTAURA_UNIQUE_VIEJA)
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_UQ_CON_LOTE}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_UQ_SIN_LOTE}")
    op.execute("ALTER TABLE pursuits DROP COLUMN IF EXISTS desglose_al_abrir")
    op.execute("ALTER TABLE pursuits DROP COLUMN IF EXISTS lote_numero")
