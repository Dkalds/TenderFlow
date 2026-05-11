"""Utilidades geográficas compartidas: NUTS3 → Comunidad Autónoma.

Usado por ``scraper.codice_parser`` y ``dashboard.data_loader`` para
mapear códigos NUTS de licitaciones a su CCAA correspondiente.
"""

from __future__ import annotations

# ── NUTS3 (provincia) → Comunidad Autónoma ─────────────────────────────
# Códigos NUTS-2021 a 5 caracteres (ES + 3) para España.
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
for _ccaa, _codes in _CCAA_BLOCKS.items():
    for _c in _codes:
        NUTS3_TO_CCAA[_c] = _ccaa


def nuts_to_ccaa(nuts: str | None) -> str | None:
    """Convierte un código NUTS3 (o NUTS2) a su Comunidad Autónoma.

    Args:
        nuts: Código NUTS (p.ej. ``"ES300"`` → ``"Madrid"``). Admite NUTS2
              (``"ES30"``) resolviendo por prefijo. Insensible a mayúsculas.

    Returns:
        Nombre de la CCAA o ``None`` si no se reconoce el código.
    """
    if not nuts:
        return None
    n = nuts.strip().upper()
    if n in NUTS3_TO_CCAA:
        return NUTS3_TO_CCAA[n]
    if n.startswith("ES") and len(n) >= 4:
        # Fallback por prefijo NUTS2 (ES + 2 dígitos)
        prefix = n[:4]
        for code, ccaa in NUTS3_TO_CCAA.items():
            if code.startswith(prefix):
                return ccaa
    return None
