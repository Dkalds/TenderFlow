"""Primitivas del contrato que no pertenecen a ningún recurso: ``PgDateTime`` y ``SafeStr``."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any

from pydantic import BeforeValidator

# Postgres serializa timestamptz a texto sin los minutos del offset cuando son
# cero (p.ej. "2026-08-01 00:45:48.33444+00"), formato que el parser RFC3339
# estricto de pydantic rechaza con `datetime_from_date_parsing`. Todas las
# columnas de fecha llegan como TEXT desde repositories/*.py (ADR-016/021), así
# que cualquier `datetime` de este módulo puede recibir ese formato.
_PG_SHORT_TZ_OFFSET_RE = re.compile(
    r"^(?P<body>.*\d{2}:\d{2}:\d{2}(?:\.\d+)?)(?P<offset>[+-]\d{2})$"
)


def _normalize_pg_datetime(value: Any) -> Any:
    """Completa el offset corto de Postgres (``+00`` → ``+00:00``) antes de parsear."""
    if isinstance(value, str):
        match = _PG_SHORT_TZ_OFFSET_RE.match(value)
        if match:
            return f"{match.group('body')}{match.group('offset')}:00"
    return value


PgDateTime = Annotated[datetime, BeforeValidator(_normalize_pg_datetime)]


def _reject_nul_bytes(value: Any) -> Any:
    """Rechaza el byte NUL en cadenas antes de que llegue a Postgres.

    Postgres no admite ``\\x00`` en columnas de texto: el ``DataError`` que
    lanza escapaba como 500 desde cualquier ruta que persistiera la cadena
    (``POST /licitaciones/bulk-get`` y ``PUT /feature-flags``, congelados en
    ``KNOWN_5XX`` de ``scripts/fuzz_api_contract.py``). Basta un carácter
    enviado por cualquier cliente, así que el saneo va en el contrato, no en
    cada endpoint: como validador de Pydantic, el fallo sale como 422 con la
    ruta del campo, que es lo que un cliente puede corregir.
    """
    if isinstance(value, str) and "\x00" in value:
        raise ValueError("El texto no puede contener el byte NUL (\\x00).")
    return value


#: ``str`` que no admite el byte NUL. Úsalo en todo campo de texto que acabe
#: persistido o comparado contra Postgres.
SafeStr = Annotated[str, BeforeValidator(_reject_nul_bytes)]
