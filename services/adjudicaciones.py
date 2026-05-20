"""Servicio de adjudicaciones — acceso de lectura enriquecido.

Centraliza la lógica de carga de adjudicaciones. Delega en
``dashboard/data_loader.py`` para la transición gradual.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)


def load_adjudicaciones(
    *,
    limit: int | None = None,
    ccaa_filter: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Carga adjudicaciones enriquecidas."""
    from dashboard.data_loader import load_adjudicaciones as _dl_adj

    return _dl_adj(limit=limit, ccaa_filter=ccaa_filter)


def load_raw_adjudicaciones(
    *,
    limit: int | None = None,
    ccaa_filter: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Carga adjudicaciones raw con datos de la licitación asociada.

    Devuelve lista de dicts para que ``data_loader`` convierta a DataFrame
    y aplique enriquecimiento.
    """
    sql = (
        "SELECT a.*, l.titulo, l.organo_contratacion, l.url AS url_lic, "
        "       l.fecha_publicacion, "
        "       l.importe AS importe_licitacion "
        "FROM adjudicaciones a "
        "LEFT JOIN licitaciones l ON l.id_externo = a.licitacion_id "
    )
    params: list[Any] = []
    if ccaa_filter:
        placeholders = ",".join("?" for _ in ccaa_filter)
        sql += f"WHERE a.ccaa IN ({placeholders}) "
        params.extend(ccaa_filter)
    sql += "ORDER BY a.fecha_adjudicacion DESC"
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(int(limit))
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))


def load_licitadores(
    ccaa_filter: tuple[str, ...] | None = None,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """Carga adjudicaciones con datos para el ranking de licitadores."""
    sql = (
        "SELECT a.id, a.licitacion_id, a.nif, a.nombre, a.ccaa, a.provincia, "
        "       a.importe_adjudicado, a.importe_pagable, a.fecha_adjudicacion, "
        "       a.es_pyme, a.n_ofertas_recibidas, "
        "       l.titulo, l.organo_contratacion, l.cpv, l.tecnologia "
        "FROM adjudicaciones a "
        "JOIN licitaciones l ON l.id_externo = a.licitacion_id "
    )
    params: list[Any] = []
    if ccaa_filter:
        placeholders = ",".join("?" for _ in ccaa_filter)
        sql += f"WHERE a.ccaa IN ({placeholders}) "
        params.extend(ccaa_filter)
    sql += f"ORDER BY a.fecha_adjudicacion DESC LIMIT {int(limit)}"
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))
