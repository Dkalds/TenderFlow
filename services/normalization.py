"""Normalización de nombres de empresas y NIFs.

Lógica de dominio pura y reutilizable desde distintas capas de la aplicación.
Reutilizable desde scraper, API REST y otros servicios.

Las funciones públicas son:
    normalize_company(name)  →  str | None
    normalize_nif(nif)       →  str | None
    clasificar_nif(nif)      →  "dni" | "nie" | "cif" | "invalido"
    nif_valido(nif)          →  bool
    parse_ute_members(name)  →  list[str]
    fold_text(text)          →  str
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

# Sufijos societarios (España + frecuentes UE) — se eliminan al final
_LEGAL_SUFFIXES = [
    r"S\.?\s?A\.?\s?U\.?",
    r"S\.?\s?L\.?\s?U\.?",
    r"S\.?\s?A\.?\s?S\.?",
    r"S\.?\s?L\.?\s?P\.?",
    r"S\.?\s?L\.?\s?N\.?\s?E\.?",
    r"S\.?\s?C\.?\s?P\.?",
    r"S\.?\s?A\.?",
    r"S\.?\s?L\.?",
    r"S\.?\s?C\.?",
    r"S\.?\s?COOP\.?",
    r"SOCIEDAD\s+AN[OÓ]NIMA(\s+UNIPERSONAL)?",
    r"SOCIEDAD\s+LIMITADA(\s+UNIPERSONAL)?",
    r"SOCIEDAD\s+COOPERATIVA",
    r"COMPA[ÑN][ÍI]A",
    r"\bGMBH\b",
    r"\bLTD\b",
    r"\bLLC\b",
    r"\bINC\b",
    r"\bAG\b",
    r"\bBV\b",
    r"\bN\.?V\.?",
    r"\bU\.?T\.?E\.?",  # UTE: las marcamos aparte
]

_SUFFIX_RE = re.compile(
    r"(?:^|[\s,\.\-])(" + "|".join(_LEGAL_SUFFIXES) + r")\s*$",
    flags=re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+")


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def fold_text(text: str) -> str:
    """Pliega texto para matching accent/case-insensitive (sin tildes + casefold).

    Pensado para búsquedas de usuario: ``fold_text("Informática") == fold_text("INFORMATICA")``.
    """
    return _strip_accents(text).casefold()


def normalize_company(name: str | None) -> str | None:
    """Normaliza un nombre de empresa para agrupar duplicados.

    Pasos: mayúsculas → sin tildes → quita sufijos societarios →
    strip puntuación → quita sufijos descubiertos tras puntuación → colapsa espacios.

    La función es idempotente: normalize(normalize(x)) == normalize(x).
    """
    if not name or not isinstance(name, str):
        return None
    s = name.strip().upper()
    s = _strip_accents(s).upper()
    # Pass 1: remove terminal legal suffixes before punctuation normalization
    while True:
        new = _SUFFIX_RE.sub("", s).strip(" ,.-")
        if new == s:
            break
        s = new
    # Normalize punctuation (replace with spaces) and collapse whitespace
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    # Pass 2: punctuation removal may expose suffixes that were 'hidden' in pass 1
    while True:
        new = _SUFFIX_RE.sub("", s).strip()
        if new == s:
            break
        s = new
    s = _WS_RE.sub(" ", s).strip()
    return s or None


def normalize_nif(nif: str | None) -> str | None:
    """Normaliza un NIF/CIF: quita espacios, guiones, mayúsculas.

    Solo normaliza, no valida: TED trae identificadores de empresas de toda la
    UE (IVA intracomunitario, registros mercantiles extranjeros) que no son
    NIF españoles y que hay que conservar tal cual. Quien necesite saber si el
    valor es un NIF español válido usa :func:`nif_valido` o
    :func:`clasificar_nif`.
    """
    if not nif or not isinstance(nif, str):
        return None
    s = re.sub(r"[\s\-\.]", "", nif).upper()
    return s or None


# ── Validación de NIF español (DNI, NIE, CIF) ────────────────────────────
#
# Hasta 2026-09-14 no existía: cualquier cadena pasaba por «NIF canónico» y el
# maestro de empresas, la ingesta por NIF vigilado, los NIF de la organización y
# el cierre de oportunidades por adjudicación descansaban sobre una clave que
# nadie comprobaba. Una letra de control mal tecleada no fallaba: creaba una
# empresa nueva o vigilaba un NIF que ninguna adjudicación va a traer.
#
# Las tres reglas son las del Ministerio del Interior (DNI/NIE) y la Orden
# EHA/451/2008 (CIF). No se inventa ninguna: se implementan y se prueban con
# valores calculados.

#: ``invalido`` es un valor con FORMA española y letra de control incorrecta.
#: ``extranjero`` no encaja en ninguna forma española (IVA intracomunitario,
#: registros mercantiles de otros países que trae TED): no es un NIF válido,
#: pero tampoco es un error de tecleo, y el maestro de empresas lo conserva
#: como identificador opaco para poder casar dos adjudicaciones del mismo
#: licitador extranjero.
TipoNif = Literal["dni", "nie", "cif", "invalido", "extranjero"]

# La tabla oficial de letras de control del DNI, fijada por norma y pública.
# detect-secrets la ve como base64 de alta entropía.
_LETRAS_DNI = "TRWAGMYFPDXBNJZSQVHLCKE"  # pragma: allowlist secret
_LETRAS_CIF = "JABCDEFGHI"
_DNI_RE = re.compile(r"^(\d{8})([A-Z])$")
_NIE_RE = re.compile(r"^([XYZ])(\d{7})([A-Z])$")
_CIF_RE = re.compile(r"^([ABCDEFGHJNPQRSUVW])(\d{7})([0-9A-J])$")
#: Letra de organización cuyo control es obligatoriamente una LETRA.
_CIF_CONTROL_LETRA = frozenset("KPQSNW")
#: Letra de organización cuyo control es obligatoriamente un DÍGITO.
_CIF_CONTROL_DIGITO = frozenset("ABEH")


def _control_cif(digitos: str) -> int:
    """Dígito de control de un CIF a partir de sus siete dígitos centrales.

    Suma de los dígitos en posición par (2.ª, 4.ª, 6.ª) más la suma de las
    cifras del doble de los dígitos en posición impar; el control es lo que
    falta para la siguiente decena (10 → 0).
    """
    pares = sum(int(d) for d in digitos[1::2])
    impares = 0
    for d in digitos[0::2]:
        doble = int(d) * 2
        impares += doble // 10 + doble % 10
    return (10 - (pares + impares) % 10) % 10


def clasificar_nif(nif: str | None) -> TipoNif:
    """Clasifica un identificador como DNI, NIE, CIF, inválido o extranjero.

    Normaliza antes de mirar (espacios, guiones, minúsculas no cuentan). Un
    valor vacío es ``invalido``: no hay nada que clasificar.
    """
    s = normalize_nif(nif)
    if s is None:
        return "invalido"
    if (m := _DNI_RE.match(s)) is not None:
        numero, letra = m.groups()
        return "dni" if _LETRAS_DNI[int(numero) % 23] == letra else "invalido"
    if (m := _NIE_RE.match(s)) is not None:
        prefijo, numero, letra = m.groups()
        base = int(str("XYZ".index(prefijo)) + numero)
        return "nie" if _LETRAS_DNI[base % 23] == letra else "invalido"
    if (m := _CIF_RE.match(s)) is not None:
        organizacion, digitos, control = m.groups()
        esperado = _control_cif(digitos)
        control_valido: bool
        if organizacion in _CIF_CONTROL_LETRA:
            control_valido = control == _LETRAS_CIF[esperado]
        elif organizacion in _CIF_CONTROL_DIGITO:
            control_valido = control == str(esperado)
        else:
            control_valido = control in {str(esperado), _LETRAS_CIF[esperado]}
        return "cif" if control_valido else "invalido"
    return "extranjero"


def nif_valido(nif: str | None) -> bool:
    """``True`` si el valor es un DNI, NIE o CIF español con control correcto."""
    return clasificar_nif(nif) in {"dni", "nie", "cif"}


def nif_espanol_malformado(nif: str | None) -> bool:
    """``True`` si tiene forma española y la letra de control no cuadra.

    Es la pregunta que hace la resolución de entidades: un identificador
    extranjero se conserva como clave opaca, pero un CIF con la letra mal no
    puede servir para casar adjudicaciones, porque casaría un error de tecleo
    con otro error de tecleo o crearía una empresa que no existe.
    """
    return clasificar_nif(nif) == "invalido" and normalize_nif(nif) is not None


# ── UTE member extraction ────────────────────────────────────────────────
_UTE_PREFIX_RE = re.compile(
    r"^\s*U\.?\s*T\.?\s*E\.?\s*[:\-\s]*",
    flags=re.IGNORECASE,
)
_UTE_TAIL_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")
_UTE_SPLIT_RE = re.compile(
    r"\s*(?:\s-\s|\s\u2013\s|\s\u2014\s|\s/\s|/|,\s|;\s|\sY\s|\sAND\s)\s*",
    flags=re.IGNORECASE,
)


def parse_ute_members(name: str | None) -> list[str]:
    """Extrae los miembros de una UTE a partir del campo ``nombre``.

    Acepta formatos como ``"UTE EMPRESA1 - EMPRESA2"``,
    ``"U.T.E. A, B y C"`` o ``"Ute A-B (Lote 3)"``.

    Devuelve una lista de nombres normalizados (vía :func:`normalize_company`),
    sin duplicados y conservando el orden de aparición. Lista vacía si no es
    una UTE o no se pueden extraer miembros.
    """
    if not name or not isinstance(name, str):
        return []
    raw = name.strip()
    if not _UTE_PREFIX_RE.match(raw):
        if not re.search(r"\bU\.?T\.?E\.?\s*$", raw, flags=re.IGNORECASE):
            return []
        body = re.sub(r"\bU\.?T\.?E\.?\s*$", "", raw, flags=re.IGNORECASE).strip(" ,.-")
    else:
        body = _UTE_PREFIX_RE.sub("", raw).strip()

    body = _UTE_TAIL_PAREN_RE.sub("", body).strip(" ,.-")
    if not body:
        return []

    parts = [p.strip(" ,.-") for p in _UTE_SPLIT_RE.split(body) if p and p.strip(" ,.-")]
    members: list[str] = []
    seen: set[str] = set()
    for p in parts:
        norm = normalize_company(p)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        members.append(norm)
    return members
