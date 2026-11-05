"""Pipeline canónica de orquestación — ADR-012.

Define la secuencia oficial de pasos post-ingesta. Tanto ``run_update.py``
(GitHub Actions) como ``loop.py`` / ``jobs/`` (APScheduler Docker) **delegan**
en estas funciones para garantizar paridad.

Secuencia canónica::

    ingesta → ML scoring → analytics export → KPI precompute
            → aggregates precompute → watchlist notify → event dispatch → digests
            → DLQ retry → anomaly checks → retention cleanup
            → ML retrain → drift checks

``tech_signal_merge`` corre justo después de ``ml_tecnologias``: aplica la
señal de tecnología detectada en los pliegos (``services/tech_signal.py``)
sobre ``ml_tecnologias``/``licitacion_tecnologia_score`` allí donde el resumen
ML aún no la refleja -- lo que ``precompute_ml_tecnologias`` acaba de
reescribir, o lo que nunca se fusionó. ``db/upsert.py`` ya no resetea esas
columnas en cada re-scrape (ver docstring de ``_run_tech_signal_merge``).

**Sigue en ``CANONICAL_STEPS`` a propósito** tras ``v136`` (T3 del plan v2,
2026-09-18): ya ningún productor hace ``UPDATE`` del resumen —lo deriva un
trigger de ``licitacion_tecnologia_score``—, pero el criterio de retirada es
«cero reparaciones en siete días de cierre, medido en ``ops_events``» sobre
producción, y ``precompute_ml_tecnologias(force=True)`` todavía borra las
filas del pliego al sustituir las del modelo. Se retira cuando el contador
``licitaciones_reparadas`` lo demuestre, no antes; ``scripts/check_job_parity.py``
va en el mismo commit. El paso deja ese contador en ``ops_events`` como
``EVENTO_TECH_SIGNAL_MERGE`` (``value`` = reparaciones de la pasada)::

    SELECT ts, value FROM ops_events
    WHERE event_type = 'tech_signal_merge' AND ts > now() - interval '7 days'
    ORDER BY ts DESC

``digests``, ``retention_cleanup`` y ``drift_checks`` tienen **cadencia
propia** (ver ``_run_periodic``): la pipeline corre cada 4h, pero un digest
diario debe enviarse una vez al día y la retención purgar una vez al día,
no seis.

El módulo se partió en cuatro (2026-11) y este queda como fachada: es la ruta
que importan ``run_update.py``, los jobs, la API y la cola
(``services/jobs.py`` resuelve ``scheduler.pipeline_runs:ejecutar_paso_encolado``).

- ``scheduler.pipeline_pasos``: catálogo, severidad, dependencias y carriles.
- ``scheduler.pipeline_pasos_impl``: un ``_run_<paso>`` por paso canónico.
- ``scheduler.pipeline_cierre``: el ejecutor del cierre, en línea y por cola.
- ``scheduler.pipeline_carriles``: los carriles diario, bulk y backfill.

Un test que sustituye una pieza la parchea en su módulo dueño: aquí solo se
reexporta, y parchear la fachada no cambia lo que ejecutan los demás.
"""

from __future__ import annotations

from scheduler.pipeline_carriles import (
    meses_a_procesar,
    run_backfill_pipeline,
    run_bulk_pipeline,
    run_daily_pipeline,
)
from scheduler.pipeline_cierre import (
    ColaNoDisponible,
    ejecutar_paso,
    ejecutar_paso_encolado,
    run_post_ingestion_only,
)
from scheduler.pipeline_pasos import (
    CANONICAL_STEPS,
    LANE_BULK,
    LANE_DAILY,
    STEP_DEPS,
    STEP_ERROR,
    STEP_OK,
    STEP_SKIPPED,
    STEP_SKIPPED_DEP,
    STEP_TIER,
    StepTier,
    dependencias_incumplidas,
    pasos_bloqueantes_fallidos,
    step_tier,
)
from scheduler.pipeline_pasos_impl import EVENTO_TECH_SIGNAL_MERGE

__all__ = [
    "CANONICAL_STEPS",
    "EVENTO_TECH_SIGNAL_MERGE",
    "LANE_BULK",
    "LANE_DAILY",
    "STEP_DEPS",
    "STEP_ERROR",
    "STEP_OK",
    "STEP_SKIPPED",
    "STEP_SKIPPED_DEP",
    "STEP_TIER",
    "ColaNoDisponible",
    "StepTier",
    "dependencias_incumplidas",
    "ejecutar_paso",
    "ejecutar_paso_encolado",
    "meses_a_procesar",
    "pasos_bloqueantes_fallidos",
    "run_backfill_pipeline",
    "run_bulk_pipeline",
    "run_daily_pipeline",
    "run_post_ingestion_only",
    "step_tier",
]
