"""Servicio de clusters — orquesta clustering de licitaciones.

En el futuro (Fase 3), delegará en tablas materializadas.
Por ahora, proxy al módulo ``dashboard/clustering.py``.
"""

from __future__ import annotations

import pandas as pd

from observability.logging import get_logger

log = get_logger(__name__)


def cluster_licitaciones(
    df: pd.DataFrame,
    *,
    n_clusters: int = 8,
) -> pd.DataFrame:
    """Clusteriza licitaciones y devuelve DataFrame con cluster_id/cluster_label."""
    from dashboard.clustering import cluster_licitaciones as _cl

    return _cl(df, n_clusters=n_clusters)
