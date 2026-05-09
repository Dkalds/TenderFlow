from __future__ import annotations

import html as _html
import re

import pandas as pd


def fmt_eur(x: float | None) -> str:
    if x is None or pd.isna(x):
        return "—"
    if abs(x) >= 1e9:
        return f"{x / 1e9:.2f} B€"
    if abs(x) >= 1e6:
        return f"{x / 1e6:.2f} M€"
    if abs(x) >= 1e3:
        return f"{x / 1e3:.1f} k€"
    return f"{x:,.0f} €"


def highlight_match(text: str, query: str) -> str:
    """Envuelve las coincidencias de *query* en ``<mark class="search-hl">``.

    - Escapa el texto completo antes de insertar el marcador.
    - Búsqueda case-insensitive, multi-token (cada palabra del query se marca
      de forma independiente).
    - Devuelve el texto escapado sin marcadores si query está vacío.
    """
    escaped = _html.escape(str(text))
    if not query or not query.strip():
        return escaped

    for token in query.strip().split():
        if len(token) < 2:
            continue
        pattern = re.compile(re.escape(_html.escape(token)), re.IGNORECASE)
        escaped = pattern.sub(lambda m: f'<mark class="search-hl">{m.group(0)}</mark>', escaped)
    return escaped
