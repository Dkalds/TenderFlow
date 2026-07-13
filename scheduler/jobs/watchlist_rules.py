"""Job dedicado de evaluación de reglas de watchlist (mi-watchlist).

Plan Pliegos+RAG, fase C2a. Detrás de ``WATCHLIST_RULES_JOB_ENABLED``
(default False): la pipeline canónica (``scheduler/pipeline_runs.py::
_run_watchlist_notify``) ya invoca ``check_rules_and_notify()`` tras cada
ingesta — este job es el equivalente para el plano APScheduler/Docker
(ADR-012 "un solo plano de orquestación"), pensado para activarse solo si
ese plano pasa a ser el dueño.

Idempotencia frente a doble ejecución (pipeline + este job activos a la
vez): ``_write_user_notifications`` ya inserta con
``ON CONFLICT(user_key, licitacion_id, type) DO NOTHING`` — una licitación
ya notificada a un usuario (por cualquier regla, desde cualquiera de los
dos caminos) no genera una segunda fila. Ver ``test_anti_doble_ejecucion``
en ``tests/test_watchlist_rules_job.py``.
"""

from __future__ import annotations

from observability.logging import get_logger

log = get_logger(__name__)


def run() -> int:
    """Evalúa las reglas activas y notifica matches nuevos.

    No-op (devuelve 0 sin tocar la BD) si ``WATCHLIST_RULES_JOB_ENABLED``
    está en False — el default, mientras la pipeline canónica sea la dueña
    de este trabajo.
    """
    from config import settings

    if not settings.WATCHLIST_RULES_JOB_ENABLED:
        log.debug("watchlist_rules_job_disabled")
        return 0

    from scheduler.watchlist_rules_alerts import check_rules_and_notify

    alerted = check_rules_and_notify()
    log.info("watchlist_rules_job_done", rules_alerted=alerted)
    return alerted
