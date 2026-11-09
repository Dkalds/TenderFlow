"""Job de pre-cálculo de agregados al cierre de cada pasada.

Refresca la vista materializada ``licitaciones_canonicas`` (de la que lee toda
la superficie pública) y recalcula ``tasas_anulacion_organo`` (F1.4).

Aquí se calculaba también ``mat_clusters`` (TF-IDF + KMeans sobre hasta 50.000
filas, y un DELETE + reinserción de la tabla entera en cada pasada). Se quitó el
2026-11-08: desde que se retiró ``services/clustering_engine.py`` (2026-09-28)
ninguna ruta la leía, y la API calcula los clusters en vivo
(``services/analytics/clusters.py``). La tabla queda congelada hasta que una
migración la borre. Antes había caído por lo mismo ``mat_top_empresas_ccaa``
(2026-07).

Uso:
    python -m scheduler.aggregates_precompute

Se registra automáticamente en ``scheduler/loop.py`` tras cada ejecución
diaria y de recarga bulk.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from db.repositories.publico import refrescar_vista_canonicas
from observability.logging import get_logger
from observability.ops_events import record_event

log = get_logger(__name__)


#: Ventana de la tasa de anulación o desierto por órgano (F1.4).
MESES_TASA_ANULACION = 24


def _recalcular_tasas_anulacion() -> int:
    """Recalcula ``tasas_anulacion_organo`` sobre los últimos 24 meses."""
    from datetime import timedelta

    from db.repositories.tasas_anulacion import recalcular

    desde = (datetime.now(UTC) - timedelta(days=MESES_TASA_ANULACION * 365 // 12)).date()
    n = recalcular(desde_iso=desde.isoformat())
    log.info("aggregates_precompute.tasas_anulacion_done", n=n)
    return n


def run_aggregates_precompute() -> dict[str, Any]:
    """Refresca la vista de canónicas y recalcula las tasas de anulación.

    **Cada pieza va en su propio `try`.** Hasta el 2026-08-30 el refresco
    compartía bloque con el clustering (ya retirado) y cualquier excepción de
    éste se lo saltaba: la superficie pública se quedaba servida sobre el
    corpus del último refresco bueno, con cifras coherentes entre sí, viejas,
    y sin nada que lo delatara.

    El refresco es la pieza crítica: de la vista leen las seis superficies
    indexables. Las tasas alimentan una penalización del scoring.

    Returns:
        Dict con ``status`` (``ok`` · ``partial`` · ``error``), ``n_canonicas``,
        ``n_tasas_anulacion`` y los errores de cada pieza si los hubo. ``error``
        es que el refresco cayó; ``partial``, que sólo cayeron las tasas. Los
        dos ponen el paso en rojo (``scheduler/pipeline_pasos_impl.py``).
    """
    resultado: dict[str, Any] = {"n_canonicas": None, "n_tasas_anulacion": None}
    fallos: list[str] = []

    try:
        n_canonicas = refrescar_vista_canonicas()
        resultado["n_canonicas"] = n_canonicas
        log.info("aggregates_precompute.canonicas_refrescadas", n=n_canonicas)
        # Deja rastro persistente del refresco. Los counters de Prometheus mueren
        # con el proceso efímero de Actions; `scheduler/healthcheck.py` lee
        # `ops_events` desde la BD y es quien convierte esto en la única señal de
        # que la superficie pública sigue viva. Sin ella, una vista congelada no
        # se distingue de una fresca hasta que alguien compara a mano.
        record_event("mv_canonicas_refresh", value=float(n_canonicas))
    except Exception as exc:
        log.exception("aggregates_precompute.canonicas_failed", error=str(exc))
        resultado["error_canonicas"] = str(exc)
        fallos.append("canonicas")

    # F1.4 — con su propio `try`: un fallo aquí deja el scoring con las tasas de
    # la pasada anterior (o sin señal), pero no puede costar el refresco.
    try:
        resultado["n_tasas_anulacion"] = _recalcular_tasas_anulacion()
    except Exception as exc:
        log.exception("aggregates_precompute.tasas_anulacion_failed", error=str(exc))
        resultado["error_tasas_anulacion"] = str(exc)
        fallos.append("tasas_anulacion")

    if not fallos:
        resultado["status"] = "ok"
    else:
        resultado["status"] = "error" if "canonicas" in fallos else "partial"
        resultado["error"] = "; ".join(fallos)
    return resultado


if __name__ == "__main__":
    import json
    import sys

    result = run_aggregates_precompute()
    log.info("aggregates_precompute.result", **{k: v for k, v in result.items() if k != "error"})
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("status") == "ok" else 1)
