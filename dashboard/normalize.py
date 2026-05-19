"""Normalización de nombres de empresas y NIFs.

.. deprecated::
    La lógica ha sido migrada a ``services.normalization``.
    Este módulo se mantiene como shim de compatibilidad hacia atrás.
    Importa directamente de ``services.normalization`` para código nuevo.
"""

from __future__ import annotations

# Re-export from services layer — backward compatible
from services.normalization import (
    normalize_company,
    normalize_nif,
    parse_ute_members,
)

__all__ = [
    "normalize_company",
    "normalize_nif",
    "parse_ute_members",
]
