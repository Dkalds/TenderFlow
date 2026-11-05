"""Job de pre-cálculo de agregados materializados.

Calcula la asignación de cada licitación a su cluster semántico via KMeans
sobre embeddings TF-IDF (fallback) o sentence-transformers si disponible.
Resultado → ``mat_clusters``. Ojo: desde que se retiró
``services/clustering_engine.py`` (2026-09-28) ninguna ruta lee esa tabla; la
API calcula los clusters en vivo (``services/analytics/clusters.py``).

El ranking ``mat_top_empresas_ccaa`` se eliminó (2026-07): se recomputaba en
cada pasada de la pipeline y no lo leía ningún consumidor.

Uso:
    python -m scheduler.aggregates_precompute

Se registra automáticamente en ``scheduler/loop.py`` tras cada ejecución
diaria y de recarga bulk.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from db.repositories.mat_clusters import filas_para_clustering, reemplazar_clusters
from db.repositories.publico import refrescar_vista_canonicas
from observability.logging import get_logger
from observability.ops_events import record_event

log = get_logger(__name__)

_N_CLUSTERS = 8  # número de clusters semánticos


# ── Clusters semánticos ───────────────────────────────────────────────────────


def _compute_clusters(rows: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
    """Calcula la asignación de clusters para las licitaciones dadas."""

    if not rows:
        return []

    ids = [r[0] for r in rows]
    texts = [f"{r[1] or ''} {r[2] or ''}".strip() for r in rows]

    try:
        from sklearn.cluster import KMeans
        from sklearn.feature_extraction.text import TfidfVectorizer

        n_clusters = min(_N_CLUSTERS, len(ids))
        vectorizer = TfidfVectorizer(max_features=5000, sublinear_tf=True)
        X = vectorizer.fit_transform(texts)
        # Reducir n_init a 1 para optimizar el rendimiento.
        # k-means++ es la inicialización por defecto y es muy efectiva.
        km = KMeans(n_clusters=n_clusters, random_state=42, n_init=1)
        labels = km.fit_predict(X)

        # Construir etiquetas: top-3 términos TF-IDF del centroide de cada cluster
        feature_names = vectorizer.get_feature_names_out()
        cluster_labels: dict[int, str] = {}
        order_centroids = km.cluster_centers_.argsort()[:, ::-1]
        for k in range(n_clusters):
            top_terms = [feature_names[i] for i in order_centroids[k, :3]]
            cluster_labels[k] = " · ".join(top_terms)

        now = datetime.now(UTC).isoformat()
        return [
            {
                "id_externo": id_ext,
                "cluster_id": int(lbl),
                "cluster_label": cluster_labels[int(lbl)],
                "updated_at": now,
            }
            for id_ext, lbl in zip(ids, labels, strict=False)
        ]

    except Exception as exc:
        log.warning("aggregates_precompute.cluster_failed", error=str(exc))
        return []


# ── Punto de entrada ──────────────────────────────────────────────────────────


def _recalcular_clusters() -> int:
    """Recalcula ``mat_clusters`` y devuelve cuántas filas quedaron."""
    # Cómputo fuera de la transacción de escritura, que abre `reemplazar_clusters`.
    clusters = _compute_clusters(filas_para_clustering())
    reemplazar_clusters(clusters)
    log.info("aggregates_precompute.clusters_done", n=len(clusters))
    return len(clusters)


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
    """Recalcula los clusters semánticos y refresca la vista de canónicas.

    Los dos trabajos comparten paso porque comparten disparador —el final de la
    pasada de ingesta— y porque los dos son lo mismo: precálculo que evita pagar
    en cada petición lo que se puede pagar una vez por pasada.

    **Comparten paso pero no destino, y por eso van en `try` separados.** Hasta
    el 2026-08-30 estaban en el mismo bloque, con un comentario que afirmaba lo
    contrario: cualquier excepción cargando o persistiendo clusters salía por el
    `except` sin llegar al refresco. Y los dos caminos por los que este paso
    puede caer de verdad —una lectura de hasta 50.000 filas y un DELETE con
    inserciones por lotes— estaban justo por delante. El precio de ese orden lo
    paga la superficie pública entera, que se queda servida sobre el corpus del
    último refresco bueno: cifras coherentes entre sí, viejas, y sin nada que
    lo delate.

    El refresco es además el trabajo importante de los dos: los clusters
    alimentan una vista analítica, la vista alimenta las seis superficies
    indexables.

    Returns:
        Dict con ``status`` (``ok`` · ``partial`` · ``error``), ``n_clusters``,
        ``n_canonicas`` y los errores de cada mitad si los hubo. ``partial``
        significa que una de las dos salió: el paso no es verde, pero tampoco
        es lo mismo que no haber hecho nada.
    """
    resultado: dict[str, Any] = {"n_clusters": None, "n_canonicas": None}
    fallos: list[str] = []

    try:
        resultado["n_clusters"] = _recalcular_clusters()
    except Exception as exc:
        log.exception("aggregates_precompute.clusters_failed", error=str(exc))
        resultado["error_clusters"] = str(exc)
        fallos.append("clusters")

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

    # F1.4 — tercera pieza, con su propio `try` por lo mismo que las otras
    # dos. Un fallo aquí deja el scoring con las tasas de la pasada anterior
    # (o sin señal), así que cuenta como `partial`; `error` sigue reservado a
    # que las dos piezas originales caigan.
    try:
        resultado["n_tasas_anulacion"] = _recalcular_tasas_anulacion()
    except Exception as exc:
        log.exception("aggregates_precompute.tasas_anulacion_failed", error=str(exc))
        resultado["error_tasas_anulacion"] = str(exc)
        fallos.append("tasas_anulacion")

    if not fallos:
        resultado["status"] = "ok"
    elif "clusters" in fallos and "canonicas" in fallos:
        resultado["status"] = "error"
        resultado["error"] = "; ".join(fallos)
    else:
        resultado["status"] = "partial"
        resultado["error"] = fallos[0]
    return resultado


if __name__ == "__main__":
    import json
    import sys

    result = run_aggregates_precompute()
    log.info("aggregates_precompute.result", **{k: v for k, v in result.items() if k != "error"})
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("status") == "ok" else 1)
