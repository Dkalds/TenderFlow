"""Utilidades geográficas — GeoJSON de CCAA de España."""

from __future__ import annotations

import logging
from typing import Any

import requests
import streamlit as st

logger = logging.getLogger(__name__)

_GEOJSON_URL = (
    "https://raw.githubusercontent.com/codeforamerica/click_that_hood/"
    "master/public/data/spain-communities.geojson"
)

# Mapeo: nombre en GeoJSON → nombre normalizado usado en el dashboard.
# Añade entradas según las diferencias reales entre el GeoJSON y tu columna `ccaa`.
GEOJSON_TO_CCAA: dict[str, str] = {
    "Andalucia": "Andalucía",
    "Aragon": "Aragón",
    "Asturias": "Asturias",
    "Baleares": "Baleares",
    "Canarias": "Canarias",
    "Cantabria": "Cantabria",
    "Castilla-Leon": "Castilla y León",
    "Castilla-La Mancha": "Castilla-La Mancha",
    "Cataluña": "Cataluña",
    "Valencia": "Comunidad Valenciana",
    "Extremadura": "Extremadura",
    "Galicia": "Galicia",
    "Madrid": "Madrid",
    "Murcia": "Murcia",
    "Navarra": "Navarra",
    "Pais Vasco": "País Vasco",
    "La Rioja": "La Rioja",
    "Ceuta": "Ceuta",
    "Melilla": "Melilla",
}


def _normalize_name(name: str) -> str:
    """Devuelve el nombre normalizado de la CCAA, o el original si no hay mapeo."""
    return GEOJSON_TO_CCAA.get(name, name)


@st.cache_data(ttl=86400, show_spinner=False)
def load_spain_ccaa_geojson() -> dict[str, Any] | None:
    """Descarga y cachea el GeoJSON de comunidades autónomas de España.

    Normaliza la propiedad ``name`` de cada feature para que coincida con los
    valores habituales de la columna ``ccaa`` del dataframe del dashboard.

    Returns ``None`` si la descarga falla.
    """
    try:
        resp = requests.get(_GEOJSON_URL, timeout=15)
        resp.raise_for_status()
        geojson: dict[str, Any] = resp.json()

        # Normalizar nombres
        for feature in geojson.get("features", []):
            props = feature.get("properties", {})
            raw_name = props.get("name", "")
            props["name"] = _normalize_name(raw_name)

        return geojson
    except Exception:
        logger.warning("No se pudo descargar el GeoJSON de CCAA", exc_info=True)
        return None
