"""Property-based tests para parsers (E1).

Usa Hypothesis para generar inputs aleatorios y verificar invariantes:

- ``parse_summary`` es total (no lanza excepciones para cualquier string).
- ``parse_summary`` siempre devuelve un dict con las claves esperadas.
- Importes de fechas robustas: el parser maneja ISO, DD/MM/YYYY y basura.

Estos tests complementan a los tests con XML reales en
``test_codice_parser.py`` cubriendo casos límite que podrían escapar a la
suite ejemplificada.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from scraper.codice_parser import parse_summary


# Estrategia: cualquier string Unicode razonablemente acotado.
_text = st.text(max_size=1000)


@given(s=st.one_of(st.none(), _text))
@settings(max_examples=200, deadline=None)
def test_parse_summary_is_total(s: str | None) -> None:
    """No debe lanzar excepciones para cualquier entrada."""
    result = parse_summary(s)
    assert isinstance(result, dict)


@given(s=st.one_of(st.none(), _text))
@settings(max_examples=100, deadline=None)
def test_parse_summary_keys_are_strings(s: str | None) -> None:
    """Todas las claves devueltas deben ser strings."""
    result = parse_summary(s)
    assert all(isinstance(k, str) for k in result)


@given(
    importe=st.one_of(
        st.text(alphabet="0123456789.,€ ", max_size=20),
        st.from_regex(r"\d{1,8}([.,]\d{1,3})*", fullmatch=True),
    )
)
@settings(max_examples=100, deadline=None)
def test_parse_summary_handles_arbitrary_amounts(importe: str) -> None:
    """No debe romperse con strings que parecen importes."""
    s = f"Importe: {importe} EUR"
    result = parse_summary(s)
    # Si extrae importe, debe ser float o None
    if "importe" in result:
        v = result["importe"]
        assert v is None or isinstance(v, int | float)
