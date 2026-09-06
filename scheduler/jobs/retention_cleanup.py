"""Data retention cleanup — purge historical rows per policy."""

from __future__ import annotations

from typing import Any


def run() -> dict[str, Any]:
    """Purga los datos históricos según la política de retención publicada.

    No pasa ningún plazo: los toma de `scheduler.retention.POLITICA_RETENCION`,
    que a su vez los lee de `RETENTION_*` en `config/settings.py`. Hasta 2026-09
    este job repetía los ocho números como literales, de modo que el job y el CLI
    podían divergir del documento que los publica sin que nada fallara.
    """
    from scheduler.retention import run_retention

    return run_retention(apply=True)
