"""Histogramas de rendimiento para el dashboard.

Expone helpers para medir tiempos de render de páginas y queries de BD,
usables como decoradores o context managers.

Métricas añadidas:
  - dashboard_render_seconds{page}   — Tiempo de render de cada página Streamlit
  - db_query_seconds{query}          — Tiempo de consultas SQLite

Los valores se registran en structlog (siempre) y opcionalmente en
prometheus_client si está disponible.

Uso::

    from observability.histograms import timed_render, timed_query

    with timed_render("resumen"):
        render_resumen(ctx)

    with timed_query("load_licitaciones"):
        df = _load_raw()
"""

from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager

from observability.logging import get_logger

log = get_logger(__name__)

# ── Prometheus opcional ──────────────────────────────────────────────────
try:
    from prometheus_client import Histogram

    _RENDER_HIST = Histogram(
        "dashboard_render_seconds",
        "Tiempo de render de una página del dashboard (segundos)",
        ["page"],
        buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )
    _QUERY_HIST = Histogram(
        "db_query_seconds",
        "Tiempo de ejecución de queries SQLite (segundos)",
        ["query"],
        buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
    )
    _PROM_AVAILABLE = True
except Exception:
    _PROM_AVAILABLE = False


@contextmanager
def timed_render(page: str) -> Generator[None, None, None]:
    """Mide y registra el tiempo de render de una página.

    Args:
        page: Nombre de la página (ej. "resumen", "organos").

    Example::

        with timed_render("resumen"):
            resumen.render(ctx)
    """
    t0 = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - t0
        log.debug("dashboard_render_seconds", page=page, seconds=round(elapsed, 4))
        if _PROM_AVAILABLE:
            try:
                _RENDER_HIST.labels(page=page).observe(elapsed)
            except Exception:
                pass  # No interrumpir el flujo si Prometheus falla


@contextmanager
def timed_query(query: str) -> Generator[None, None, None]:
    """Mide y registra el tiempo de una query de BD.

    Args:
        query: Identificador legible de la query (ej. "load_licitaciones").

    Example::

        with timed_query("load_licitaciones"):
            cursor = c.execute(sql)
    """
    t0 = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - t0
        log.debug("db_query_seconds", query=query, seconds=round(elapsed, 4))
        if _PROM_AVAILABLE:
            try:
                _QUERY_HIST.labels(query=query).observe(elapsed)
            except Exception:
                pass
