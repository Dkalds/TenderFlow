"""Tipos compartidos entre scraper, scheduler y API.

Uso:
    from shared.types import JsonDict
"""

from __future__ import annotations

from typing import Any, TypeAlias

# ── Alias genérico ───────────────────────────────────────────────────────
# Usar sólo cuando el shape real no está especificado. Preferir TypedDicts.
JsonDict: TypeAlias = dict[str, Any]
