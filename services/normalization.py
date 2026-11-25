"""Reexporta :mod:`shared.normalization`, donde vive la normalización desde 2026-11-25.

Bajó a ``shared/`` para que ``db/upsert.py`` pueda escribir la identidad
normalizada de cada adjudicación (``v191``). Este módulo se queda para los
importadores de ``services/``, ``scraper/`` y ``api/``: el código nuevo importa
de ``shared.normalization``.
"""

from __future__ import annotations

from shared.normalization import (
    TipoNif,
    clasificar_nif,
    fold_text,
    nif_espanol_malformado,
    normalize_company,
    normalize_nif,
    parse_ute_members,
)

__all__ = [
    "TipoNif",
    "clasificar_nif",
    "fold_text",
    "nif_espanol_malformado",
    "normalize_company",
    "normalize_nif",
    "parse_ute_members",
]
