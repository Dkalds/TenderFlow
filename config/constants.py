"""Constantes de dominio del proyecto: URLs, prefijos CPV y campos de histórico.

Consumidores: ``scraper.atom_live``, ``scraper.bulk_downloader``, ``db.database``.
"""

from __future__ import annotations

# CPV codes relevantes (servicios TI / software)
CPV_PREFIXES_TI = [
    "72",  # Servicios TI
    "48",  # Paquetes de software
]

# URL base de la Plataforma de Contratación
PLACE_BASE_URL = "https://contrataciondelestado.es"
PLACE_SYNDICATION_BASE = f"{PLACE_BASE_URL}/sindicacion"

# Endpoint de búsqueda (form-based)
PLACE_SEARCH_URL = f"{PLACE_BASE_URL}/wps/portal/plataforma/buscadores/busqueda/"

# User agent identificable (buena práctica scraping ético)
USER_AGENT = "TenderflowBot/1.0"

# Feed ATOM en vivo — sindicación paginada de PLACE
PLACE_LIVE_ATOM_URL = (
    "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/"
    "licitacionesPerfilesContratanteCompleto3.atom"
)

# Campos clave para detección de cambios (historial)
HISTORY_TRACKED_FIELDS = (
    "importe",
    "estado",
    "fecha_fin",
    "fecha_inicio",
    "duracion_valor",
    "duracion_unidad",
    "titulo",
    "descripcion",
)
