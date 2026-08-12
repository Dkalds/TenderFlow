"""Tests del validador compartido de pesos (unit, sin BD).

Los pesos entran por dos puertas —settings global y perfil de usuario— y solo
una estaba defendida. Cada caso de aquí es un perfil que el endpoint aceptaba
y que producía un ranking absurdo sin decir nada.
"""

from __future__ import annotations

import pytest

from shared.scoring_weights import KNOWN_WEIGHT_KEYS, validate_scoring_weights

_VALIDOS = {
    "importe": 20,
    "plazo": 15,
    "competencia": 20,
    "margen": 20,
    "afinidad": 15,
    "senal_tecnica": 10,
}


def test_acepta_el_reparto_por_defecto():
    validate_scoring_weights(_VALIDOS)


def test_acepta_un_perfil_sin_afinidad():
    """La dimensión es opcional: sin ella, las otras cuatro suman 100."""
    validate_scoring_weights({"importe": 30, "plazo": 20, "competencia": 30, "margen": 20})


def test_rechaza_claves_inventadas():
    """`{"foo": 100}` dejaba las cinco dimensiones reales a 0: todo a Descarte."""
    with pytest.raises(ValueError, match="clave desconocida"):
        validate_scoring_weights({"foo": 100})


def test_rechaza_una_clave_inventada_entre_validas():
    """Una dimensión mal escrita entre otras válidas no puede colarse en silencio.

    `afinidadd` está mal escrita **a propósito**: es el caso realista —un dedazo
    en el nombre de una dimensión— que antes pasaba la validación y se llevaba
    esos puntos a ninguna parte.
    """
    with pytest.raises(ValueError, match="clave desconocida"):
        validate_scoring_weights({**_VALIDOS, "afinidad": 5, "afinidadd": 10})


def test_rechaza_pesos_negativos():
    with pytest.raises(ValueError, match="negativo"):
        validate_scoring_weights({"importe": 130, "plazo": -30})


def test_rechaza_una_suma_distinta_de_cien():
    with pytest.raises(ValueError, match="suma 90"):
        validate_scoring_weights({"importe": 50, "plazo": 40})


def test_rechaza_afinidad_al_completo():
    """Con afinidad=100 no queda nada que redistribuir si el perfil no tiene keywords."""
    with pytest.raises(ValueError, match="afinidad"):
        validate_scoring_weights({"afinidad": 100})


def test_el_mensaje_nombra_el_origen():
    """El operador tiene que saber si el problema está en el ENV o en su perfil."""
    with pytest.raises(ValueError, match="SCORING_WEIGHTS"):
        validate_scoring_weights({"foo": 100}, source="SCORING_WEIGHTS")


def test_las_dimensiones_conocidas_son_las_que_puntuan():
    """`riesgo` es penalización fuera de la suma, no una dimensión ponderable."""
    assert "riesgo" not in KNOWN_WEIGHT_KEYS
    assert {
        "importe",
        "plazo",
        "competencia",
        "margen",
        "afinidad",
        "senal_tecnica",
    } == KNOWN_WEIGHT_KEYS


def test_un_perfil_anterior_a_senal_tecnica_sigue_siendo_valido():
    """Los perfiles guardados antes de la dimensión no se invalidan al desplegar."""
    validate_scoring_weights(
        {"importe": 25, "plazo": 15, "competencia": 25, "margen": 20, "afinidad": 15}
    )


def test_settings_globales_pasan_su_propio_validador():
    """Regresión: el reparto por defecto del repo tiene que ser válido."""
    from config import settings

    validate_scoring_weights(settings.SCORING_WEIGHTS, source="SCORING_WEIGHTS")
