"""Normalización de nombres de empresas y NIFs.

Lógica de dominio pura — sin dependencias de Streamlit ni de la capa web.
Reutilizable desde scraper, API REST y dashboard.

Las funciones públicas son:
    normalize_company(name)  →  str | None
    normalize_nif(nif)       →  str | None
    parse_ute_members(name)  →  list[str]
"""

from __future__ import annotations

import re
import unicodedata

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
    """Normaliza un NIF/CIF: quita espacios, guiones, mayúsculas."""
    if not nif or not isinstance(nif, str):
        return None
    s = re.sub(r"[\s\-\.]", "", nif).upper()
    return s or None


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
