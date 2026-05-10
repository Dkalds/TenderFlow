"""Clasificadores y diccionarios de referencia para enriquecer los datos."""

from __future__ import annotations

import re

# ── NUTS3 (provincia) → Comunidad Autónoma ─────────────────────────────
# Códigos NUTS-2021 a 4 caracteres (ES + 3) para España.
NUTS3_TO_CCAA: dict[str, str] = {}
_CCAA_BLOCKS = {
    "Galicia": ["ES111", "ES112", "ES113", "ES114"],
    "Asturias": ["ES120"],
    "Cantabria": ["ES130"],
    "País Vasco": ["ES211", "ES212", "ES213"],
    "Navarra": ["ES220"],
    "La Rioja": ["ES230"],
    "Aragón": ["ES241", "ES242", "ES243"],
    "Madrid": ["ES300"],
    "Castilla y León": [
        "ES411",
        "ES412",
        "ES413",
        "ES414",
        "ES415",
        "ES416",
        "ES417",
        "ES418",
        "ES419",
    ],
    "Castilla-La Mancha": ["ES421", "ES422", "ES423", "ES424", "ES425"],
    "Extremadura": ["ES431", "ES432"],
    "Cataluña": ["ES511", "ES512", "ES513", "ES514"],
    "Comunidad Valenciana": ["ES521", "ES522", "ES523"],
    "Baleares": ["ES531", "ES532", "ES533"],
    "Andalucía": ["ES611", "ES612", "ES613", "ES614", "ES615", "ES616", "ES617", "ES618"],
    "Murcia": ["ES620"],
    "Ceuta": ["ES630"],
    "Melilla": ["ES640"],
    "Canarias": ["ES703", "ES704", "ES705", "ES706", "ES707", "ES708", "ES709"],
}
for ccaa, codes in _CCAA_BLOCKS.items():
    for c in codes:
        NUTS3_TO_CCAA[c] = ccaa


def nuts_to_ccaa(nuts: str | None) -> str | None:
    if not nuts:
        return None
    n = nuts.strip().upper()
    if n in NUTS3_TO_CCAA:
        return NUTS3_TO_CCAA[n]
    if n.startswith("ES") and len(n) >= 4:
        # Por prefijo NUTS2 (ES + 2 dígitos)
        prefix = n[:4]
        for code, ccaa in NUTS3_TO_CCAA.items():
            if code.startswith(prefix):
                return ccaa
    return None


# ── Decoder CPV (códigos más frecuentes en TI/SAP) ──────────────────────
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
    if not code or not isinstance(code, str):
        return "—"
    code = code.strip()
    if code in CPV_NAMES:
        return f"{code} · {CPV_NAMES[code]}"
    # Buscar prefijo
    for length in (8, 7, 6, 5, 4, 3, 2):
        prefix = code[:length].ljust(8, "0")
        if prefix in CPV_NAMES:
            return f"{code} · {CPV_NAMES[prefix]}"
    return code


# ── Clasificador de módulos SAP ─────────────────────────────────────────
SAP_MODULES = {
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
    if not text:
        return []
    found = []
    for name, pat in _SAP_MODULE_PATTERNS.items():
        if pat.search(text):
            found.append(name)
    return found or ["SAP (genérico)"]


# ── Etiquetas de tecnología para el dashboard ───────────────────────────
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
PROJECT_TYPES = {
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
    if not text:
        return "Sin clasificar"
    for name, pat in _PROJECT_TYPE_PATTERNS.items():
        if pat.search(text):
            return name
    return "Sin clasificar"


# ── Decoder estados PLACSP ─────────────────────────────────────────────
ESTADO_LABELS = {
    "PUB": "Publicada",
    "EV": "Evaluación",
    "RES": "Resuelta",
    "ADJ": "Adjudicada",
    "ANUL": "Anulada",
    "PRE": "Anuncio previo",
    "CREA": "Creada",
}


def estado_label(code: str | None) -> str:
    if not code:
        return "Desconocido"
    return ESTADO_LABELS.get(code.strip(), code.strip())


# ── Decoder tipo de contrato ───────────────────────────────────────────
TIPO_CONTRATO_LABELS = {
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
    if not code:
        return "—"
    return TIPO_CONTRATO_LABELS.get(code.strip(), f"Tipo {code}")
