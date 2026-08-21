"""v87: extensión ``unaccent`` — plegado de acentos dentro del motor.

Revision ID: v87_unaccent_extension
Revises: v86_predicciones_baja_lote
Create Date: 2026-08-18

``services/analytics/competitors.py`` es el último analítico híbrido: sus
filtros ya se empujan al ``WHERE`` (v. ``AdjudicacionRepository
.load_for_competitors``), pero la **resolución de identidad de empresa** sigue
en pandas porque no es reducible a un ``GROUP BY``: es un union-find sobre
cinco tokens por fila (grupo del maestro, grupo curado, ``empresa_id``, NIF
normalizado y nombre normalizado). Bajarla a SQL exige que el motor sepa
calcular ``services/normalization.py::normalize_company``, cuyo primer paso es
plegar acentos — y hoy la base solo tiene ``pg_trgm`` (v50) y ``vector`` (v56),
ninguna de las dos con una primitiva de accent-fold.

Esta revisión **solo habilita la extensión**. No consume ``unaccent`` todavía:
existe para desbloquear el diseño de la CTE recursiva de identidad
(``db/repositories/competitor_identity.py``), que se mide contra la
implementación de pandas antes de sustituirla. Habilitarla es barato y
reversible; la reescritura no lo es.

Por qué esto NO es v68
----------------------
v68 añadió una **columna generada** a ``licitaciones`` y con ello reescribió
1,6 M de filas bajo lock exclusivo durante más de 30 minutos. Aquí no hay nada
de eso: ``CREATE EXTENSION`` escribe filas de catálogo (``pg_extension``,
``pg_proc``, ``pg_ts_dict``, ``pg_ts_config``) y no toca ni una tabla de
usuario — cero filas reescritas, cero lock sobre ``licitaciones`` o
``adjudicaciones``, tiempo constante. No añade columnas, ni defaults, ni
``SET NOT NULL``, ni backfill.

Dos avisos que hereda quien la consuma
--------------------------------------
1. **Schema de la extensión.** Se emite sin cláusula ``SCHEMA``, que es el
   patrón exacto de v50 (``CREATE EXTENSION IF NOT EXISTS pg_trgm``) y v56
   (``... vector``): la extensión cae en el primer schema creable del
   ``search_path`` de quien migra. En un Postgres local eso es ``public``; en
   Supabase el convenio es el schema ``extensions``, y hay constancia de que un
   ``search_path`` que lo excluye deja de resolver ``vector``/``<=>`` y el
   ``%`` de pg_trgm. Con ``unaccent`` pasaría lo mismo, y peor: el fallo no
   sería un tipo desconocido sino un ``function unaccent(text) does not
   exist`` en mitad de la consulta de competidores.
   Comprobación tras aplicar:
   ``SELECT extname, extnamespace::regnamespace FROM pg_extension;``
   Por eso ``db/repositories/competitor_identity.py`` **no** llama a
   ``unaccent`` a pelo: resuelve el schema real por catálogo y cualifica la
   llamada, de modo que el código nuevo es inmune al ``search_path``.

2. **``unaccent(text)`` no es IMMUTABLE.** La forma de un argumento resuelve el
   diccionario a través del ``search_path``, así que Postgres la declara
   STABLE y rechaza usarla en una expresión de índice. Esta revisión no crea
   ningún índice sobre ``unaccent`` precisamente por eso. Si más adelante hace
   falta indexar el nombre normalizado, la receta es la de la documentación de
   Postgres: envolver la forma de **dos** argumentos con el diccionario fijado
   como ``regdictionary`` (``unaccent('unaccent'::regdictionary, $1)``) en una
   función SQL declarada IMMUTABLE, y indexar esa. Esa promesa deja de ser
   cierta si alguien edita ``unaccent.rules``, cosa que obliga a un REINDEX;
   asumir ese contrato es una decisión aparte, no un efecto colateral de
   habilitar la extensión.

``unaccent`` es *trusted* desde PG13, así que no requiere superusuario si el
rol que migra tiene CREATE sobre el schema destino.

El ``downgrade`` es ``DROP EXTENSION`` **sin** ``CASCADE``: si para entonces
existe un índice o una vista que dependa de la extensión, queremos que falle
con un mensaje que los nombre, no que se los lleve por delante en silencio.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v87_unaccent_extension"
down_revision: str | Sequence[str] | None = "v86_predicciones_baja_lote"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP EXTENSION IF EXISTS unaccent")
