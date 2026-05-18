"""Aplica FiltersState a un DataFrame de licitaciones."""

from __future__ import annotations

import re

import pandas as pd

from dashboard.filters.state import FiltersState
from observability.logging import get_logger

log = get_logger(__name__)

# ── Cache del estado FTS5 (evitar consultar sqlite_master en cada rerun) ──
_fts_available: bool | None = None


def _check_fts() -> bool:
    """Comprueba una sola vez si FTS5 está disponible."""
    global _fts_available
    if _fts_available is None:
        try:
            from db.database import fts_available

            _fts_available = fts_available()
        except Exception:
            _fts_available = False
    return _fts_available


def _search_fts_ids(query: str, limit: int = 1000) -> list[str] | None:
    """Busca con FTS5 y devuelve id_externo ordenados por bm25 rank.

    Returns None si FTS no está disponible o la query falla (fallback a str.contains).
    """
    if not _check_fts() or not query.strip():
        return None
    try:
        from services.licitaciones import search_fts_ids

        return search_fts_ids(query, limit=limit)
    except Exception as exc:
        log.debug("fts_search_fallback", error=str(exc), query=query)
        return None


def apply_filters(df: pd.DataFrame, state: FiltersState) -> pd.DataFrame:
    # Evitar copia completa upfront: cada máscara booleana ya materializa un nuevo DataFrame.
    result = df
    _fts_used = False
    if state.q:
        # Intentar FTS5 primero para ranking por relevancia
        fts_ids = _search_fts_ids(state.q)
        if fts_ids is not None and fts_ids:
            # Preservar orden de relevancia de FTS5
            _fts_used = True
            id_order = {eid: i for i, eid in enumerate(fts_ids)}
            result = result[result["id_externo"].isin(id_order)]
            result = result.assign(_fts_rank=result["id_externo"].map(id_order))
            result = result.sort_values("_fts_rank").drop(columns=["_fts_rank"])
        else:
            # Fallback: pandas str.contains
            q_escaped = re.escape(state.q)
            mask = (
                result["titulo"].str.contains(q_escaped, case=False, na=False)
                | result["descripcion"].str.contains(q_escaped, case=False, na=False)
                | result["organo_contratacion"].str.contains(q_escaped, case=False, na=False)
            )
            result = result[mask]
    if state.rango and isinstance(state.rango, tuple) and len(state.rango) == 2:
        result = result[
            (result["fecha_publicacion"].dt.date >= state.rango[0])
            & (result["fecha_publicacion"].dt.date <= state.rango[1])
        ]
    if state.estados:
        result = result[result["estado_desc"].isin(state.estados)]
    if state.ccaas:
        result = result[result["ccaa"].isin(state.ccaas)]
    if state.organos:
        result = result[result["organo_contratacion"].isin(state.organos)]
    if state.tipos_proy:
        result = result[result["tipo_proyecto"].isin(state.tipos_proy)]
    if state.tecnologias and "tecnologia" in result.columns:
        # tecnologia puede ser multi-valor ("SAP,ORACLE"); usamos regex vectorizado
        # para evitar .apply() con lambda (lento en datasets grandes).
        pattern = "|".join(r"(?:^|,)\s*" + re.escape(t) + r"\s*(?:,|$)" for t in state.tecnologias)
        mask = result["tecnologia"].fillna("").str.contains(pattern, regex=True, na=False)
        result = result[mask]
    if state.importe_min > 0:
        result = result[result["importe"].fillna(0) >= state.importe_min]
    # Anotar si los resultados están ordenados por relevancia FTS
    result.attrs["fts_ranked"] = _fts_used
    return result
