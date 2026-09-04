"""Job de pre-cálculo de agregados materializados.

Calcula la asignación de cada licitación a su cluster semántico via KMeans
sobre embeddings TF-IDF (fallback) o sentence-transformers si disponible.
Resultado → ``mat_clusters``, que lee ``services/clustering_engine.py``.

El ranking ``mat_top_empresas_ccaa`` se eliminó (2026-07): se recomputaba en
cada pasada de la pipeline y no lo leía ningún consumidor.

Uso:
    python -m scheduler.aggregates_precompute

Se registra automáticamente en ``scheduler/loop.py`` tras cada ejecución
diaria y de recarga bulk.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from db.database import connect, connect_read
from db.repositories.publico import refrescar_vista_canonicas
from db.sql_fragments import technology_observed_sql
from observability.logging import get_logger
from observability.ops_events import record_event

log = get_logger(__name__)

_INSERT_CHUNK = 500  # filas por INSERT multi-fila


def _insert_batched(conn: Any, sql_prefix: str, columns: int, rows: list[tuple[Any, ...]]) -> None:
    """Inserta ``rows`` en bloques de ``_INSERT_CHUNK`` con VALUES multi-fila.

    ``executemany`` emite una sentencia (y por tanto un round-trip de red) por
    fila contra un backend remoto -- a cientos de ms por fila, miles de filas
    se traducen en minutos de latencia acumulada aunque el cómputo en sí sea
    instantáneo. Agrupar en un único INSERT multi-fila por bloque reduce esos
    round-trips de N a N/``_INSERT_CHUNK``.
    """
    for i in range(0, len(rows), _INSERT_CHUNK):
        chunk = rows[i : i + _INSERT_CHUNK]
        placeholders = ", ".join(f"({', '.join(['%s'] * columns)})" for _ in chunk)
        values = [v for row in chunk for v in row]
        conn.execute(f"{sql_prefix} VALUES {placeholders}", values)


_N_CLUSTERS = 8  # número de clusters semánticos


# ── Clusters semánticos ───────────────────────────────────────────────────────


def _compute_clusters(source: Any) -> list[dict[str, Any]]:
    """Calcula la asignación de clusters para las licitaciones dadas."""
    rows = _load_clustering_data(source) if hasattr(source, "execute") else source

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


def _load_clustering_data(conn: Any) -> list[tuple[str, str, str]]:
    """Carga las licitaciones relevantes para el clustering.

    Limitado a las últimas licitaciones para evitar cómputos excesivos.
    """
    # Cargar licitaciones de los últimos 12 meses o un máximo de 50,000 para evitar cómputos excesivos.
    # Asume que 'fecha_publicacion' es el campo adecuado para el filtrado.
    # Si no, se podría usar 'id' o 'rowid' con un LIMIT fijo.
    cutoff_sql = "l.fecha_publicacion >= to_char(CURRENT_DATE - INTERVAL '12 months', 'YYYY-MM-DD')"
    # El alias ``l`` no estaba y se añade sólo para poder interpolar el
    # predicado canónico: ``technology_observed_sql`` siempre califica la
    # columna, porque el índice parcial de v84 se acopla al texto del
    # ``COALESCE`` y quitarle el prefijo sería otra grafía más. El alias no
    # cambia el árbol que ve el planificador.
    return cast(
        "list[tuple[str, str, str]]",
        conn.execute(
            f"""
        SELECT l.id_externo, l.titulo, SUBSTR(l.descripcion, 1, 500)
        FROM licitaciones l
        WHERE l.titulo IS NOT NULL
          AND {technology_observed_sql()}
          AND (l.fecha_publicacion IS NULL OR {cutoff_sql})
        ORDER BY l.fecha_publicacion DESC
        LIMIT 50000
        """  # noqa: S608 — los fragmentos interpolados son constantes, sin input de usuario
        ).fetchall(),
    )


def _persist_clusters(conn: Any, rows: list[dict[str, Any]]) -> None:
    """Reemplaza atómicamente la tabla mat_clusters."""
    conn.execute("DELETE FROM mat_clusters")
    if rows:
        _insert_batched(
            conn,
            "INSERT INTO mat_clusters (id_externo, cluster_id, cluster_label, updated_at)",
            4,
            [(r["id_externo"], r["cluster_id"], r["cluster_label"], r["updated_at"]) for r in rows],
        )


# ── Punto de entrada ──────────────────────────────────────────────────────────


def _recalcular_clusters() -> int:
    """Recalcula ``mat_clusters`` y devuelve cuántas filas quedaron."""
    # Cómputo fuera de la transacción de escritura.
    with connect_read() as read_conn:
        clustering_data = _load_clustering_data(read_conn)

    clusters = _compute_clusters(clustering_data)

    # Persistencia en una transacción separada.
    with connect() as write_conn:
        _persist_clusters(write_conn, clusters)
    log.info("aggregates_precompute.clusters_done", n=len(clusters))
    return len(clusters)


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

    if not fallos:
        resultado["status"] = "ok"
    elif len(fallos) == 2:
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
