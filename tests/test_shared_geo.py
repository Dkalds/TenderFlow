"""Tests para shared/geo.py — mapeo NUTS3 → CCAA."""

from __future__ import annotations

import pytest


def test_nuts3_exact_match():
    from shared.geo import nuts_to_ccaa

    assert nuts_to_ccaa("ES300") == "Madrid"


def test_nuts3_andalucia():
    from shared.geo import nuts_to_ccaa

    assert nuts_to_ccaa("ES611") == "Andalucía"
    assert nuts_to_ccaa("ES618") == "Andalucía"


def test_nuts3_pais_vasco():
    from shared.geo import nuts_to_ccaa

    assert nuts_to_ccaa("ES211") == "País Vasco"
    assert nuts_to_ccaa("ES213") == "País Vasco"


def test_nuts3_cataluna():
    from shared.geo import nuts_to_ccaa

    assert nuts_to_ccaa("ES511") == "Cataluña"
    assert nuts_to_ccaa("ES514") == "Cataluña"


def test_nuts3_canarias():
    from shared.geo import nuts_to_ccaa

    assert nuts_to_ccaa("ES703") == "Canarias"
    assert nuts_to_ccaa("ES709") == "Canarias"


def test_nuts3_lowercase_normalized():
    from shared.geo import nuts_to_ccaa

    assert nuts_to_ccaa("es300") == "Madrid"


def test_nuts3_with_spaces():
    from shared.geo import nuts_to_ccaa

    assert nuts_to_ccaa("  ES300  ") == "Madrid"


def test_nuts3_none_returns_none():
    from shared.geo import nuts_to_ccaa

    assert nuts_to_ccaa(None) is None


def test_nuts3_empty_returns_none():
    from shared.geo import nuts_to_ccaa

    assert nuts_to_ccaa("") is None


def test_nuts3_unknown_returns_none():
    from shared.geo import nuts_to_ccaa

    assert nuts_to_ccaa("XX999") is None


def test_nuts2_prefix_fallback():
    """Códigos NUTS2 (4 caracteres) resuelven por prefijo."""
    from shared.geo import nuts_to_ccaa

    # ES30 → Madrid (prefijo de ES300)
    result = nuts_to_ccaa("ES30")
    assert result == "Madrid"


def test_all_nuts3_codes_in_map():
    """Todos los códigos definidos en _CCAA_BLOCKS están en el mapa."""
    from shared.geo import _CCAA_BLOCKS, NUTS3_TO_CCAA

    expected_count = sum(len(v) for v in _CCAA_BLOCKS.values())
    assert len(NUTS3_TO_CCAA) == expected_count


def test_all_known_codes_resolve():
    """nuts_to_ccaa resuelve todos los códigos conocidos."""
    from shared.geo import NUTS3_TO_CCAA, nuts_to_ccaa

    for code, expected_ccaa in NUTS3_TO_CCAA.items():
        assert nuts_to_ccaa(code) == expected_ccaa, f"Failed for {code}"


@pytest.mark.parametrize(
    "nuts,expected",
    [
        ("ES111", "Galicia"),
        ("ES120", "Asturias"),
        ("ES130", "Cantabria"),
        ("ES220", "Navarra"),
        ("ES230", "La Rioja"),
        ("ES241", "Aragón"),
        ("ES411", "Castilla y León"),
        ("ES421", "Castilla-La Mancha"),
        ("ES431", "Extremadura"),
        ("ES521", "Comunidad Valenciana"),
        ("ES531", "Baleares"),
        ("ES620", "Murcia"),
        ("ES630", "Ceuta"),
        ("ES640", "Melilla"),
    ],
)
def test_parametrized_nuts_to_ccaa(nuts, expected):
    from shared.geo import nuts_to_ccaa

    assert nuts_to_ccaa(nuts) == expected


@pytest.mark.parametrize(
    ("nuts", "esperado"),
    [
        # NUTS1: siempre agrupa varias provincias.
        ("ES7", True),
        ("ES3", True),
        (" es6 ", True),
        # NUTS2 con varias provincias.
        ("ES70", True),
        ("ES61", True),
        ("ES41", True),
        ("ES11", True),
        # NUTS2 uniprovinciales: el nombre que publica PLACSP es la provincia.
        ("ES30", False),
        ("ES12", False),
        ("ES62", False),
        ("ES63", False),
        ("ES53", False),  # tres NUTS3, pero son islas de una sola provincia
        # Ni NUTS3, ni país, ni otro país, ni código desconocido.
        ("ES300", False),
        ("ES", False),
        ("PT1", False),
        ("ES99", False),
        ("", False),
        (None, False),
    ],
)
def test_es_nuts_supraprovincial(nuts: str | None, esperado: bool) -> None:
    from shared.geo import es_nuts_supraprovincial

    assert es_nuts_supraprovincial(nuts) is esperado
