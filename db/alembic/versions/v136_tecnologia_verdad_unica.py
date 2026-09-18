"""v136: ``licitacion_tecnologia_score`` es la única verdad del resumen ML (T3).

Revision ID: v136_tecnologia_verdad_unica
Revises: v132_informes_programados
Create Date: 2026-09-18

Qué había
---------
``licitaciones.ml_tecnologias``, ``ml_proba_max`` y ``ml_tech_principal`` eran
un resumen de ``licitacion_tecnologia_score`` (``v30``) que **cada productor
escribía por su cuenta**: ``precompute_ml_tecnologias`` con un ``UPDATE`` que
reescribía las tres columnas en cada pasada, y el merge de la señal de pliego
(``db/repositories/tecnologia_pliego.py``) con otro ``UPDATE`` más un ``INSERT``
en la tabla — los dos lados escritos desde el mismo sitio. El primero pisaba lo
que el segundo había fundido, y ``tech_signal_merge``, paso **bloqueante** del
cierre, existía para deshacer ese daño cada cuatro horas.

Qué hace
--------
1. ``lts_derivar_ml(text[])``: recalcula las tres columnas de las licitaciones
   dadas a partir de sus filas de score, con la misma regla que aplicaban los
   dos productores:

   * **predicha** = ``probabilidad >= threshold_aplicado`` (el umbral que la
     propia fila declara: el del modelo por etiqueta, o
     ``PLIEGO_TECH_MIN_SCORE`` si la subió el pliego);
   * ``ml_tecnologias`` = predichas por score descendente (empate por nombre,
     para que el CSV sea determinista; en Python el orden de un empate exacto
     dependía del orden de las etiquetas);
   * ``ml_tech_principal`` = la primera de ese orden;
   * ``ml_proba_max`` = máximo de las predichas o, sin ninguna, de todas las
     filas — lo que devolvía ``TechnologyClassifier.predict_batch``.

   **Sin ninguna fila** deja ``ml_proba_max`` como está y pone las otras dos a
   ``NULL``. Una licitación puntuada con todas las etiquetas a 0.0 no deja
   filas (``precompute_ml_tecnologias`` no persiste scores nulos), y su
   ``ml_proba_max = 0.0`` es la marca de «ya puntuada» que impide
   reseleccionarla; la escribe ``db.repositories.ml_dataset
   .guardar_scores_tecnologia`` y es la **única** escritura directa que queda
   sobre esas tres columnas fuera de la ingesta.

   Solo escribe las filas que cambian (``IS DISTINCT FROM``), y
   ``ml_proba_max`` con tolerancia 1e-6: ``probabilidad`` es ``real`` y la
   columna ``double precision``, así que 0.8 vuelve como 0.800000011920929 y
   sin tolerancia el backfill reescribiría casi todas las filas puntuadas por
   un redondeo.
2. ``trg_lts_derivar_ml``: *constraint trigger* ``AFTER INSERT OR UPDATE OR
   DELETE`` por fila, ``DEFERRABLE INITIALLY DEFERRED``. Diferido a propósito:
   el precompute y el merge escriben varias filas por licitación en un mismo
   ``executemany``; con un trigger inmediato cada fila reescribiría la fila de
   ``licitaciones`` con un resumen parcial. Al ``COMMIT`` la primera firma de
   cada licitación escribe el resumen final y las demás no cambian nada.
3. **Backfill** en dos pasos, antes de crear el trigger:

   a. *Adopción*: cada tecnología que hoy está en ``ml_tecnologias`` sin estar
      predicha en la tabla (sin fila — la ingesta de ``scraper/pipeline.py``
      escribe el CSV sin filas —, o con fila bajo su umbral) se inserta o se
      ajusta con ``threshold_aplicado = probabilidad``, o sea «predicha a este
      score» (0.0 si no tenía fila: ADR-026 §B, «una tecnología sin fila de
      score vale 0.0»). Sin esto, derivar desde la tabla **borraría** del
      resumen etiquetas que hoy se ven, y el merge nunca borra.
   b. *Derivación*: ``lts_derivar_ml`` sobre toda licitación con filas de score
      o con resumen no nulo.

   El recuento de cada paso sale en el log de Alembic. **Ese es el delta que
   pide el criterio del plan** (``make audit-truth-check`` antes y después):
   se mide en la BD real antes del ``apply``, con ``--sql`` primero.

``licitaciones.tecnologia`` **no** se deriva
--------------------------------------------
El plan nombraba las tres columnas, pero ``tecnologia`` no es un resumen de
esta tabla: es la señal de keywords de la ingesta, **primera** en la
precedencia de ADR-026 §B, y no tiene fila de score que la origine. Derivarla
de aquí borraría la señal más auditable de todas. Sigue escribiéndola solo el
upsert de ingesta; el guardrail de literales (``tests/test_dedup_guardrail.py``,
categoría ``tecnologia``) impide que vuelva a aparecer un ``UPDATE`` directo.

La vista materializada no se reconstruye
----------------------------------------
Se eligió trigger y no vista **por esto**: ``licitaciones_canonicas`` (``v99``)
y el predicado ``universo_tecnologico_sql`` leen ``l.ml_tecnologias``, y esa
columna sigue existiendo con el mismo nombre y tipo. Ni la definición de la MV
ni la cadena byte-idéntica del predicado (índice parcial de ``v84``) cambian,
así que ADR-026 §A no exige reconstruirla: el backfill cambia datos, no la
consulta, y el ``REFRESH`` de la pasada siguiente (≤ 4 h) los recoge. Una
vista sobre la tabla de scores habría obligado a reescribir el predicado, la
MV y el índice a la vez — el riesgo alto que el plan anotaba.

Lo que queda fuera
------------------
* **La ingesta** (``scraper/pipeline.py::_apply_tech_prediction`` → upsert)
  sigue escribiendo el resumen en el ``INSERT`` sin filas de score. No es un
  ``UPDATE`` (el guardrail no lo ve) y el merge adopta esas etiquetas antes de
  que el trigger pueda perderlas; persistir sus scores es el paso siguiente.
* **``tech_signal_merge`` sigue en ``CANONICAL_STEPS``.** El criterio de
  retirada es «cero reparaciones en siete días de cierre, medido en
  ``ops_events``» en producción. ``precompute_ml_tecnologias(force=True)``
  sigue borrando las filas del pliego al sustituir las del modelo, así que
  todavía puede haber reparaciones legítimas.

Downgrade
---------
Quita trigger y funciones. Las filas adoptadas se quedan: describen lo que el
resumen ya decía, y los productores de antes de ``v136`` vuelven a reescribir
las columnas en su siguiente pasada.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v136_tecnologia_verdad_unica"
down_revision: str | Sequence[str] | None = "v132_informes_programados"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

#: La regla de derivación. Es la definición canónica de «resumen ML de una
#: licitación»: el guardrail de literales la usa como referencia de su
#: categoría ``tecnologia`` (el ``UPDATE`` de abajo es el único permitido).
_FUNCION_DERIVAR = """
CREATE OR REPLACE FUNCTION lts_derivar_ml(p_ids text[]) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
    n integer;
BEGIN
    WITH d AS (
        SELECT ids.id AS licitacion_id,
               string_agg(s.tecnologia, ',' ORDER BY s.probabilidad DESC, s.tecnologia)
                   FILTER (WHERE s.probabilidad >= s.threshold_aplicado) AS csv,
               (array_agg(s.tecnologia ORDER BY s.probabilidad DESC, s.tecnologia)
                   FILTER (WHERE s.probabilidad >= s.threshold_aplicado))[1] AS principal,
               COALESCE(
                   max(s.probabilidad) FILTER (WHERE s.probabilidad >= s.threshold_aplicado),
                   max(s.probabilidad)
               )::double precision AS proba_max
        FROM (SELECT DISTINCT unnest(p_ids) AS id) AS ids
        LEFT JOIN licitacion_tecnologia_score s ON s.licitacion_id = ids.id
        GROUP BY ids.id
    )
    UPDATE licitaciones l SET ml_tecnologias = d.csv, ml_tech_principal = d.principal,
        ml_proba_max = COALESCE(d.proba_max, l.ml_proba_max)
    FROM d
    WHERE l.id_externo = d.licitacion_id
      AND (
          l.ml_tecnologias IS DISTINCT FROM d.csv
          OR l.ml_tech_principal IS DISTINCT FROM d.principal
          OR (d.proba_max IS NOT NULL
              AND (l.ml_proba_max IS NULL OR abs(l.ml_proba_max - d.proba_max) > 1e-6))
      );
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END
$$
"""

_FUNCION_TRIGGER = """
CREATE OR REPLACE FUNCTION lts_derivar_ml_trg() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM lts_derivar_ml(ARRAY[OLD.licitacion_id]);
    ELSIF TG_OP = 'UPDATE' AND OLD.licitacion_id IS DISTINCT FROM NEW.licitacion_id THEN
        PERFORM lts_derivar_ml(ARRAY[OLD.licitacion_id, NEW.licitacion_id]);
    ELSE
        PERFORM lts_derivar_ml(ARRAY[NEW.licitacion_id]);
    END IF;
    RETURN NULL;
END
$$
"""

#: Adopción del resumen heredado (paso 3a de la cabecera).
_ADOPCION = """
INSERT INTO licitacion_tecnologia_score
    (licitacion_id, tecnologia, probabilidad, threshold_aplicado, computed_at)
SELECT l.id_externo, t.tech, COALESCE(s.probabilidad, 0), COALESCE(s.probabilidad, 0),
       to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
FROM licitaciones l
CROSS JOIN LATERAL (
    SELECT DISTINCT btrim(x) AS tech
    FROM unnest(string_to_array(l.ml_tecnologias, ',')) AS x
) AS t
LEFT JOIN licitacion_tecnologia_score s
       ON s.licitacion_id = l.id_externo AND s.tecnologia = t.tech
WHERE l.ml_tecnologias IS NOT NULL AND l.ml_tecnologias <> '' AND t.tech <> ''
  AND (s.licitacion_id IS NULL OR s.probabilidad < s.threshold_aplicado)
ON CONFLICT (licitacion_id, tecnologia) DO UPDATE SET
    threshold_aplicado = excluded.threshold_aplicado
"""

_DERIVACION = """
SELECT lts_derivar_ml(ARRAY(
    SELECT licitacion_id FROM licitacion_tecnologia_score
    UNION
    SELECT id_externo FROM licitaciones
    WHERE ml_tecnologias IS NOT NULL OR ml_tech_principal IS NOT NULL
))
"""


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _tablas() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if not _is_postgres() or not {"licitaciones", "licitacion_tecnologia_score"} <= _tablas():
        return

    bind = op.get_bind()
    op.execute(_FUNCION_DERIVAR)
    op.execute(_FUNCION_TRIGGER)

    # Backfill ANTES del trigger: con el trigger puesto, cada fila adoptada
    # encolaría su propia derivación diferida. `exec_driver_sql` y no
    # `sa.text`: el formato de `to_char` lleva `:MI:SS`, que `text()` tomaría
    # por parámetros.
    adoptadas = bind.exec_driver_sql(_ADOPCION).rowcount
    derivadas = bind.exec_driver_sql(_DERIVACION).scalar()
    log.info(
        "v136: %s filas de score adoptadas del resumen heredado; %s licitaciones "
        "con resumen ML reescrito por la derivación",
        adoptadas,
        derivadas,
    )

    op.execute("DROP TRIGGER IF EXISTS trg_lts_derivar_ml ON licitacion_tecnologia_score")
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_lts_derivar_ml "
        "AFTER INSERT OR UPDATE OR DELETE ON licitacion_tecnologia_score "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION lts_derivar_ml_trg()"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute("DROP TRIGGER IF EXISTS trg_lts_derivar_ml ON licitacion_tecnologia_score")
    op.execute("DROP FUNCTION IF EXISTS lts_derivar_ml_trg()")
    op.execute("DROP FUNCTION IF EXISTS lts_derivar_ml(text[])")
