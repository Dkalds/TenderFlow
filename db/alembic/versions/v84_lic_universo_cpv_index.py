"""v84: índice parcial del universo tecnológico para la señal de competencia.

Revision ID: v84_lic_universo_cpv_index
Revises: v83_pursuit_next_action
Create Date: 2026-08-17

La media de ofertas por CPV-4 de ``load_competencia_stats`` —la pata que queda
abierta del ítem "el contexto de scoring cuesta ~25 s en frío"— mide 9,5 s en
producción: un hash join de 1,6 M adjudicaciones contra un **Parallel Seq Scan**
de ``licitaciones``. Y el seq scan no es por falta de índices sobre esas
columnas (``idx_cpv`` de baseline002 indexa ``cpv``, y la PK indexa
``id_externo``), sino porque el predicado que acota el universo del radar **no
es una comparación de columna, es una expresión**:

    COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed'

``v63_lineage_index_concurrent`` indexó ``(analysis_universe, filter_version)``,
columna pelada. Un btree sobre la columna no puede resolver esa expresión:
las filas con ``analysis_universe IS NULL`` —que el ``COALESCE`` incluye **a
propósito**, porque todo el legado pre-linaje venía de un pipeline que ya
filtraba tecnología— son justo las que ese índice no sabe clasificar. Sin manera
de evaluar el filtro por índice, al planificador solo le queda recorrer las
1,6 M filas y 972 MB de heap.

**Parcial y no de expresión.** Los dos son indexables (``COALESCE`` contra una
constante es IMMUTABLE) y los dos sirven a este predicado. Se elige el parcial
mirando los call-sites reales:

- Los módulos que escriben ese ``COALESCE`` (``services/analytics/
  scoring_signals``, ``db/repositories/{ml_dataset,pricing,renovaciones}``,
  ``db/domain_truth_audit``, ``services/competitive/{mercado,bajas,
  renovaciones}``, ``scheduler/{kpi,aggregates}_precompute``) lo comparan
  **siempre** contra la misma constante. Nadie consulta otro universo por esa
  vía, así que la única ventaja teórica del índice de expresión —servir varios
  valores— no se ejerce.
- Y no podría ejercerse: el único otro universo que se consulta
  (``WATCHED_COMPANY_AWARDS_SQL``) compara la **columna pelada**
  (``l.analysis_universe = 'watched_company_awards_observed'``), que es
  exactamente lo que ya sirve v63. Para el planificador ``columna = 'x'`` y
  ``COALESCE(columna, 'y') = 'x'`` son expresiones distintas: un índice de
  expresión no cubriría esa consulta de todos modos.

El parcial, además, no repite el valor del universo en cada entrada y deja fuera
del índice todo lo que no es del radar. Y envejece mejor: hoy los 1,46 M avisos
agregados de PSCP probablemente tengan ``analysis_universe`` a NULL —el conector
es del 2026-06-11 y la columna la creó v62 el 2026-07-30— así que el ``COALESCE``
los cuenta como tecnología y el índice arrancará casi tan grande como la tabla;
el día que se les haga backfill a ``pscp_observed`` este índice se encoge solo,
mientras que el de expresión seguiría indexando la tabla entera. Quien aplique
esto puede medir el punto de partida con
``SELECT analysis_universe, count(*) FROM licitaciones GROUP BY 1``.

**Las columnas son ``(id_externo, cpv)``, no ``(cpv)`` a secas.** Un parcial
sobre ``cpv`` resuelve el filtro pero deja el join descubierto: la consulta
necesita de ``licitaciones`` exactamente dos columnas, ``id_externo`` (la clave
del join contra el agregado de ``adjudicaciones``) y ``cpv`` (el segmento y su
``length(...) >= 4``). Con solo ``cpv`` indexado, el planificador tendría que
volver al heap de 972 MB a buscar la clave del join — que es el coste que se
intenta quitar. Con las dos, el nodo puede ser un *index-only scan* sobre el
índice parcial, o un nested loop que entra por ``id_externo`` (columna líder =
clave del join) y sale con ``cpv`` sin tocar el heap. El mismo índice sirve a la
segunda consulta de ese loader —la media global, que solo necesita
``id_externo``— por tener esa columna a la izquierda.

Matiz honesto: con el visibility map incompleto de esta base (documentado en
``db/repositories/base.py::_loose_scan_cte``, donde un DISTINCT acababa bajando
al heap igualmente) el *index-only scan* puede degradar a *index scan* con heap
fetches. Aun así el índice descarta las filas fuera del universo antes del heap
y entrega el join key sin leer la fila entera, que es de donde sale el grueso
del ahorro.

**Por qué esto NO es la trampa de v68.** Aquella revisión añadió una columna
GENERADA a ``licitaciones`` y con ello reescribió la tabla entera (>1,6 M filas)
bajo lock exclusivo durante más de 30 minutos, tumbando la app. Aquí no se toca
ninguna fila: ``CREATE INDEX CONCURRENTLY`` no reescribe la tabla, no añade
columnas, no hace backfill y solo toma locks breves al principio y al final, sin
bloquear las escrituras del scraper mientras construye. Lo que sí hay que contar
es que **la construcción tarda**: sobre 1,6 M filas y 972 MB son dos pasadas
completas de la tabla más la espera a las transacciones en curso — minutos, no
segundos. Por eso ``_relax_timeouts`` (copiado de v79, mismo motivo: el
``PGOPTIONS`` de ``migrate.yml`` no llega a través de este pooler, y el default
de sesión de 2 min mataría la construcción a medias). Si el CONCURRENTLY falla
deja un índice ``INVALID`` que no sirve a nadie y sigue costando en cada INSERT:
se limpia con el ``downgrade`` y se reintenta.

**Verificación tras aplicar.** El criterio de aceptación del ítem —"primera
carga del Radar por debajo de 5 s"— **no se puede comprobar aquí**: exige
Postgres con el volumen de producción y este entorno no tiene ninguno. Se deja
el EXPLAIN para quien la aplique::

    EXPLAIN (ANALYZE, BUFFERS)
    SELECT substr(l.cpv, 1, 4) AS cpv4, AVG(sub.max_ofertas)
    FROM (SELECT a.licitacion_id, MAX(a.n_ofertas_recibidas) AS max_ofertas
          FROM adjudicaciones a
          WHERE a.n_ofertas_recibidas IS NOT NULL
            AND a.fecha_adjudicacion >= '2024-08-17'
          GROUP BY a.licitacion_id) sub
    JOIN licitaciones l ON l.id_externo = sub.licitacion_id
    WHERE COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed'
      AND l.cpv IS NOT NULL AND length(l.cpv) >= 4
    GROUP BY cpv4 HAVING COUNT(*) >= 3;

Antes: ``Parallel Seq Scan on licitaciones``, ~9,5 s. Después se espera
``Index Only Scan using idx_lic_universo_cpv`` (o un ``Nested Loop`` que entre
por él) y que desaparezca el seq scan. Conviene un ``ANALYZE licitaciones``
después de crear el índice: sin estadísticas de la expresión del predicado el
planificador estima la selectividad a ojo.

Si tras aplicarlo el plan **sigue** mostrando el seq scan, la causa casi segura
no es el índice sino el texto de la consulta: el planificador solo usa un índice
parcial cuando puede demostrar que el WHERE implica su predicado, y no normaliza
variantes del ``COALESCE``. Por eso la consulta interpola
``db.sql_fragments.TECHNOLOGY_OBSERVED_SQL`` en vez de escribir el predicado a
mano, y por eso ``tests/test_scoring_universo_index.py`` compara ambos textos:
esa igualdad es la diferencia entre que este índice sirva o sea peso muerto.

DIALECT-GUARDED: solo actúa en Postgres.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v84_lic_universo_cpv_index"
down_revision: str | Sequence[str] | None = "v83_pursuit_next_action"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "idx_lic_universo_cpv"

# Debe ser **estructuralmente idéntico** al predicado que interpolan las
# consultas (``db.sql_fragments.TECHNOLOGY_OBSERVED_SQL``, sin el alias ``l.``
# porque un CREATE INDEX no tiene FROM). No se importa el fragmento: una
# revisión de Alembic es un registro histórico y tiene que seguir describiendo
# lo que creó aunque el fragmento cambie mañana. La igualdad la vigila
# ``tests/test_scoring_universo_index.py``.
INDEX_PREDICATE = "COALESCE(analysis_universe, 'technology_observed') = 'technology_observed'"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _relax_timeouts() -> None:
    """Quita el techo de tiempo y acota la espera por el lock.

    Idéntico a ``v79_perf_hot_paths_indexes._relax_timeouts`` y por el mismo
    motivo: el ``PGOPTIONS`` que exporta ``migrate.yml`` viaja como parámetro de
    arranque ``options`` de libpq y no llega a través de este pooler, así que el
    valor que regiría sería el default de sesión —2 min, menos de lo que tarda
    un ``CREATE INDEX CONCURRENTLY`` sobre 972 MB— y la migración moriría a
    medias dejando un índice ``INVALID``. Un ``SET`` viaja como sentencia normal
    y sí llega.

    ``lock_timeout`` acotado: el CONCURRENTLY solo necesita locks breves al
    principio y al final; con el scraper escribiendo cada 4 h es preferible
    fallar rápido y reintentar que encolarse detrás de una transacción larga.
    """
    op.execute("SET statement_timeout = 0")
    op.execute("SET lock_timeout = '30s'")


def upgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        _relax_timeouts()
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} "
            "ON licitaciones (id_externo, cpv) "
            f"WHERE {INDEX_PREDICATE}"
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    with op.get_context().autocommit_block():
        _relax_timeouts()
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")
