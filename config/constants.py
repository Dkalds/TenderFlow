"""Constantes de dominio del proyecto: URLs, prefijos CPV y campos de histórico.

Consumidores: ``scraper.atom_live``, ``scraper.bulk_downloader``, ``db.database``.
"""

from __future__ import annotations

# CPV codes relevantes (servicios TI / software). Corroboran las keywords
# ambiguas de la puerta tecnológica y son la población del clasificador: no
# se amplían sin reentrenar.
CPV_PREFIXES_TI = [
    "72",  # Servicios TI
    "48",  # Paquetes de software
]

# Universo de ingesta: un aviso con algún CPV de estas divisiones se guarda
# aunque el título no case con el diccionario (`cpv_ti_universe`, sin
# `tecnologia`), en todas las fuentes con CPV. La 32 (equipos de radio,
# televisión, comunicaciones y telecomunicaciones) entró el 2026-10-30; no
# corrobora keywords ambiguas, porque «seguridad perimetral» con CCTV
# (32323500) es justo el falso positivo que la regla evita.
CPV_PREFIXES_UNIVERSO = [
    *CPV_PREFIXES_TI,
    "32",  # Equipos de radio, TV, comunicaciones y telecomunicaciones
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
    "fecha_limite",
    "duracion_valor",
    "duracion_unidad",
    "titulo",
    "descripcion",
)
