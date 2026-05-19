"""Clasificadores y diccionarios de referencia para enriquecer los datos.

.. deprecated::
    La lógica ha sido migrada a ``services.classification``.
    Este módulo se mantiene como shim de compatibilidad hacia atrás.
    Importa directamente de ``services.classification`` para código nuevo.
"""

from __future__ import annotations

# Re-export from services layer — backward compatible
from services.classification import (
    CPV_NAMES,
    ESTADO_LABELS,
    NUTS3_TO_CCAA,
    SAP_MODULES,
    TECHNOLOGY_LABELS,
    TIPO_CONTRATO_LABELS,
    cpv_label,
    detect_modules,
    detect_project_type,
    estado_label,
    nuts_to_ccaa,
    tecnologia_label,
    tipo_contrato_label,
)

__all__ = [
    "NUTS3_TO_CCAA",
    "nuts_to_ccaa",
    "CPV_NAMES",
    "cpv_label",
    "SAP_MODULES",
    "detect_modules",
    "TECHNOLOGY_LABELS",
    "tecnologia_label",
    "detect_project_type",
    "ESTADO_LABELS",
    "estado_label",
    "TIPO_CONTRATO_LABELS",
    "tipo_contrato_label",
]

