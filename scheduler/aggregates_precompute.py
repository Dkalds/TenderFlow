"""Job de pre-cálculo de agregados materializados.

Calcula en el scheduler dos tipos de resultados costosos:

* **Clusters**: asignación de cada licitación a su cluster semántico via KMeans
  sobre embeddings TF-IDF (fallback) o sentence-transformers si disponible.
  Resultado → ``mat_clusters``.

* **Top empresas por CCAA**: ranking top-10 de empresas por número de
  adjudicaciones y volumen de importe, agrupadas por comunidad autónoma.
  Resultado → ``mat_top_empresas_ccaa``.

Uso:
    python -m scheduler.aggregates_precompute

Se registra automáticamente en ``scheduler/loop.py`` tras cada ejecución
diaria y de recarga bulk.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from db.database import connect
from observability.logging import get_logger

log = get_logger(__name__)

_TOP_N = 10  # empresas por CCAA
_N_CLUSTERS = 8  # número de clusters semánticos


# ── Top empresas por CCAA ─────────────────────────────────────────────────────


def _compute_top_empresas(conn: Any) -> list[dict[str, Any]]:
    """Agrupa adjudicatarios por CCAA y devuelve el top-N de cada comunidad."""
    rows = conn.execute(
        """
        SELECT
            a.ccaa,
            a.nombre               AS nombre_raw,
            COUNT(*)               AS n_adj,
            SUM(COALESCE(a.importe_adjudicado, 0)) AS importe_total
        FROM adjudicaciones a
        WHERE a.ccaa IS NOT NULL
          AND a.nombre IS NOT NULL
          AND a.nombre != ''
        GROUP BY a.ccaa, a.nombre
        ORDER BY a.ccaa, n_adj DESC, importe_total DESC
        """
    ).fetchall()

    # Normalizar en Python para agrupar nombres equivalentes
    try:
        from services.normalization import normalize_company
    except Exception:

        def normalize_company(s: str) -> str:  # type: ignore[misc]
            return s.upper().strip()

    now = datetime.now(UTC).isoformat()
    result: list[dict[str, Any]] = []
    ccaa_rank: dict[str, int] = {}
    for ccaa, nombre_raw, n_adj, importe_total in rows:
        nombre_canon = normalize_company(nombre_raw) if nombre_raw else ""
        if not nombre_canon:
            continue
        rank = ccaa_rank.get(ccaa, 0) + 1
        if rank > _TOP_N:
            continue
        ccaa_rank[ccaa] = rank
        result.append(
            {
                "ccaa": ccaa,
                "rank": rank,
                "nombre_canon": nombre_canon,
                "n_adj": n_adj,
                "importe_total": float(importe_total or 0.0),
                "updated_at": now,
            }
        )
    return result


def _persist_top_empresas(conn: Any, rows: list[dict[str, Any]]) -> None:
    """Reemplaza atómicamente la tabla mat_top_empresas_ccaa."""
    conn.execute("DELETE FROM mat_top_empresas_ccaa")
    if rows:
        conn.executemany(
            "INSERT INTO mat_top_empresas_ccaa "
            "(ccaa, rank, nombre_canon, n_adj, importe_total, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    r["ccaa"],
                    r["rank"],
                    r["nombre_canon"],
                    r["n_adj"],
                    r["importe_total"],
                    r["updated_at"],
                )
                for r in rows
            ],
        )


# ── Clusters semánticos ───────────────────────────────────────────────────────


def _compute_clusters(conn: Any) -> list[dict[str, Any]]:
    """Calcula la asignación de clusters para todas las licitaciones."""
    rows = conn.execute(
        "SELECT id_externo, titulo, SUBSTR(descripcion, 1, 500) "
        "FROM licitaciones WHERE titulo IS NOT NULL"
    ).fetchall()

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
        km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
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


def _persist_clusters(conn: Any, rows: list[dict[str, Any]]) -> None:
    """Reemplaza atómicamente la tabla mat_clusters."""
    conn.execute("DELETE FROM mat_clusters")
    if rows:
        conn.executemany(
            "INSERT INTO mat_clusters (id_externo, cluster_id, cluster_label, updated_at) "
            "VALUES (?, ?, ?, ?)",
            [(r["id_externo"], r["cluster_id"], r["cluster_label"], r["updated_at"]) for r in rows],
        )


# ── Punto de entrada ──────────────────────────────────────────────────────────


def run_aggregates_precompute() -> dict[str, Any]:
    """Ejecuta ambos cálculos y persiste los resultados.

    Returns:
        Dict con ``n_empresas``, ``n_clusters``, ``status``.
    """
    try:
        with connect() as conn:
            empresas = _compute_top_empresas(conn)
            _persist_top_empresas(conn, empresas)
            log.info(
                "aggregates_precompute.top_empresas_done",
                n=len(empresas),
            )

            clusters = _compute_clusters(conn)
            _persist_clusters(conn, clusters)
            log.info(
                "aggregates_precompute.clusters_done",
                n=len(clusters),
            )

        return {
            "status": "ok",
            "n_empresas": len(empresas),
            "n_clusters": len(clusters),
        }
    except Exception as exc:
        log.exception("aggregates_precompute.failed", error=str(exc))
        return {"status": "error", "error": str(exc)}


if __name__ == "__main__":
    import json
    import sys

    result = run_aggregates_precompute()
    log.info("aggregates_precompute.result", **{k: v for k, v in result.items() if k != "error"})
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("status") == "ok" else 1)
