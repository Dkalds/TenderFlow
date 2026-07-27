"""Repository para vistas materializadas (``mat_clusters``)."""

from __future__ import annotations

from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)


class AggregateRepository:
    """Acceso a las vistas materializadas de aggregates."""

    def load_mat_clusters(self) -> list[dict[str, Any]]:
        """Carga datos de ``mat_clusters`` para ``services/clustering_engine.py``."""
        with connect_read() as c:
            try:
                cur = c.execute(
                    "SELECT id_externo, cluster_id, cluster_label, updated_at FROM mat_clusters"
                )
                return rows_to_dicts(cur)
            except Exception as exc:
                log.warning("repo_mat_clusters_unavailable", error=str(exc))
                return []
