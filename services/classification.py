"""Clasificación de licitaciones: CPV, módulos SAP, tecnología, tipo de proyecto.

Lógica de dominio pura — sin dependencias de Streamlit ni de la capa web.
Reutilizable desde scraper, API REST y dashboard.

Exports principales:
    cpv_label(code)          →  str
    detect_modules(text)     →  list[str]
    tecnologia_label(code)   →  str
    detect_project_type(text) →  str
    estado_label(code)       →  str
    tipo_contrato_label(code) →  str
    CPV_NAMES                →  dict[str, str]
    SAP_MODULES              →  dict[str, list[str]]
    TECHNOLOGY_LABELS        →  dict[str, str]
    ESTADO_LABELS            →  dict[str, str]
    TIPO_CONTRATO_LABELS     →  dict[str, str]
"""

from __future__ import annotations

import re

# Re-export geo helpers for convenience
from shared.geo import NUTS3_TO_CCAA, nuts_to_ccaa

__all__ = [
    "NUTS3_TO_CCAA",
    "nuts_to_ccaa",
    "CPV_NAMES",
    "cpv_label",
    "SAP_MODULES",
    "detect_modules",
    "TECHNOLOGY_LABELS",
    "tecnologia_label",
    "PROJECT_TYPES",
    "detect_project_type",
    "ESTADO_LABELS",
    "estado_label",
    "TIPO_CONTRATO_LABELS",
    "tipo_contrato_label",
]

# ── Decoder CPV ─────────────────────────────────────────────────────────
CPV_NAMES: dict[str, str] = {
    "48000000": "Software y sistemas información",
    "48100000": "Software industria específica",
    "48200000": "Software de redes/internet",
    "48300000": "Software creación documentos",
    "48400000": "Software transacciones/asuntos personales",
    "48440000": "Software financiero/análisis",
    "48450000": "Software facturación",
    "48460000": "Software gestión",
    "48490000": "Software gestión de proyectos",
    "48500000": "Software comunicaciones/multimedia",
    "48600000": "Software bases de datos/sistemas operativos",
    "48700000": "Utilidades de software",
    "48800000": "Sistemas de información y servidores",
    "48900000": "Diversos paquetes de software",
    "72000000": "Servicios TI: consultoría, desarrollo, internet",
    "72100000": "Consultoría de hardware",
    "72200000": "Servicios de programación de software",
    "72210000": "Programación de paquetes de software",
    "72220000": "Consultoría de sistemas y técnica",
    "72230000": "Desarrollo de software personalizado",
    "72240000": "Análisis sistemas y programación",
    "72250000": "Servicios mantenimiento sistemas",
    "72260000": "Servicios relacionados con software",
    "72261000": "Servicios de apoyo al software",
    "72262000": "Servicios de desarrollo de software",
    "72263000": "Servicios de implantación de software",
    "72265000": "Servicios de configuración de software",
    "72266000": "Servicios consultoría sobre software",
    "72267000": "Mantenimiento y reparación de software",
    "72267100": "Mantenimiento software TI",
    "72268000": "Servicios de suministro de software",
    "72300000": "Servicios de datos",
    "72400000": "Servicios de internet",
    "72500000": "Servicios informáticos",
    "72510000": "Servicios gestión relacionados con informática",
    "72600000": "Servicios apoyo y consultoría informática",
    "72700000": "Servicios de redes informáticas",
    "72800000": "Servicios auditoría/pruebas informáticas",
    "72900000": "Servicios de copia de seguridad",
    "51000000": "Servicios de instalación",
    "92000000": "Servicios esparcimiento/cultura/deporte",
}


def cpv_label(code: str | None) -> str:
    """Devuelve etiqueta legible para un código CPV."""
    if not code or not isinstance(code, str):
        return "—"
    code = code.strip()
    if code in CPV_NAMES:
        return f"{code} · {CPV_NAMES[code]}"
    for length in (8, 7, 6, 5, 4, 3, 2):
        prefix = code[:length].ljust(8, "0")
        if prefix in CPV_NAMES:
            return f"{code} · {CPV_NAMES[prefix]}"
    return code


# ── Clasificador de módulos SAP ─────────────────────────────────────────
SAP_MODULES: dict[str, list[str]] = {
    "S/4HANA": [r"\bs/?4\s*hana\b", r"\bs4\s*hana\b"],
    "HANA DB": [r"\bhana\b(?!\s*[a-z])"],
    "SuccessFactors": [r"\bsuccessfactors?\b", r"\bsf\s+ec\b"],
    "Ariba": [r"\bariba\b"],
    "Concur": [r"\bconcur\b"],
    "BW/4HANA": [r"\bbw[/-]?4\s*hana\b", r"\bbi\s+sap\b", r"\bsap\s+bi\b"],
    "BusinessObjects": [r"\bbusinessobjects?\b", r"\bsap\s+bo\b"],
    "Business One": [r"\bbusiness\s+one\b", r"\bsap\s+b1\b"],
    "Fiori/UI5": [r"\bfiori\b", r"\bui5\b"],
    "ABAP": [r"\babap\b"],
    "NetWeaver": [r"\bnetweaver\b"],
    "Solution Mgr": [r"\bsolution\s+manager\b"],
    "FI (Finanzas)": [r"\bsap\s+fi\b", r"\bm[óo]dulo\s+fi\b"],
    "CO (Costes)": [r"\bsap\s+co\b", r"\bm[óo]dulo\s+co\b"],
    "MM (Materiales)": [r"\bsap\s+mm\b", r"\bm[óo]dulo\s+mm\b"],
    "SD (Ventas)": [r"\bsap\s+sd\b", r"\bm[óo]dulo\s+sd\b"],
    "HCM/HR": [r"\bsap\s+hcm\b", r"\bsap\s+hr\b"],
    "PM (Mant.)": [r"\bsap\s+pm\b"],
    "PS (Proyectos)": [r"\bsap\s+ps\b"],
    "QM (Calidad)": [r"\bsap\s+qm\b"],
    "WM/EWM": [r"\bsap\s+e?wm\b"],
    "TM (Transporte)": [r"\bsap\s+tm\b"],
    "SRM": [r"\bsap\s+srm\b"],
    "CRM": [r"\bsap\s+crm\b", r"\bsap\s+cx\b"],
    "PI/PO": [r"\bsap\s+p[io]\b"],
    "Basis": [r"\bsap\s+basis\b", r"\bbasis\s+sap\b"],
    "ERP genérico": [r"\bsap\s+erp\b", r"\berp\s+sap\b"],
}
_SAP_MODULE_PATTERNS = {
    name: re.compile("|".join(p), re.IGNORECASE) for name, p in SAP_MODULES.items()
}


def detect_modules(text: str | None) -> list[str]:
    """Detecta módulos SAP mencionados en *text*."""
    if not text:
        return []
    found = []
    for name, pat in _SAP_MODULE_PATTERNS.items():
        if pat.search(text):
            found.append(name)
    return found or ["SAP (genérico)"]


# ── Etiquetas de tecnología ─────────────────────────────────────────────
TECHNOLOGY_LABELS: dict[str, str] = {
    "SAP": "SAP",
    "SALESFORCE": "Salesforce",
    "ORACLE": "Oracle",
    "MICROSOFT": "Microsoft Dynamics / Azure",
    "SERVICENOW": "ServiceNow",
    "WORKDAY": "Workday",
    "IBM": "IBM",
    "OPENTEXT": "OpenText",
    "UNIT4": "Unit4",
    "META4": "Meta4",
    "SOPRA": "Sopra",
    "SAGE": "Sage",
    "INFOR": "Infor",
}


def tecnologia_label(code: str | None) -> str:
    """Devuelve etiqueta legible para un código de tecnología."""
    if not code:
        return "Sin clasificar"
    return TECHNOLOGY_LABELS.get(code.strip(), code.strip())


# ── Clasificador de tipo de proyecto ────────────────────────────────────
PROJECT_TYPES: dict[str, list[str]] = {
    "Mantenimiento": [r"\bmantenimien", r"\bsoporte\b", r"\bmantenance\b"],
    "Implantación": [
        r"\bimplant",
        r"\bdespliegue\b",
        r"\bmigraci[óo]n\b",
        r"\binstalaci[óo]n\b",
        r"\bpuesta en marcha\b",
    ],
    "Licencias": [
        r"\blicencia",
        r"\bsuscripci[óo]n\b",
        r"\bsubscripci[óo]n\b",
        r"\bsuministro.*licen",
    ],
    "Consultoría": [r"\bconsultor", r"\basistencia t[ée]cnica\b", r"\banalista\b"],
    "Desarrollo": [r"\bdesarroll", r"\bevoluci[óo]n\b", r"\bevolutiv", r"\bprogramaci[óo]n\b"],
    "Formación": [r"\bformaci[óo]n\b", r"\bdocencia\b", r"\bm[áa]ster\b", r"\bcurso\b"],
}
_PROJECT_TYPE_PATTERNS = {
    name: re.compile("|".join(p), re.IGNORECASE) for name, p in PROJECT_TYPES.items()
}


def detect_project_type(text: str | None) -> str:
    """Detecta el tipo de proyecto a partir del texto de la licitación."""
    if not text:
        return "Sin clasificar"
    for name, pat in _PROJECT_TYPE_PATTERNS.items():
        if pat.search(text):
            return name
    return "Sin clasificar"


# ── Decoder estados PLACSP ─────────────────────────────────────────────
ESTADO_LABELS: dict[str, str] = {
    "PUB": "Publicada",
    "EV": "Evaluación",
    "RES": "Resuelta",
    "ADJ": "Adjudicada",
    "ANUL": "Anulada",
    "PRE": "Anuncio previo",
    "CREA": "Creada",
}


def estado_label(code: str | None) -> str:
    """Devuelve etiqueta legible para un código de estado PLACSP."""
    if not code:
        return "Desconocido"
    return ESTADO_LABELS.get(code.strip(), code.strip())


# ── Decoder tipo de contrato ───────────────────────────────────────────
TIPO_CONTRATO_LABELS: dict[str, str] = {
    "1": "Suministros",
    "2": "Servicios",
    "3": "Obras",
    "21": "Gestión servicios públicos",
    "31": "Concesión obras públicas",
    "40": "Patrimonial",
    "50": "Privado",
    "999": "Otro",
}


def tipo_contrato_label(code: str | None) -> str:
    """Devuelve etiqueta legible para un código de tipo de contrato."""
    if not code:
        return "—"
    return TIPO_CONTRATO_LABELS.get(code.strip(), f"Tipo {code}")
