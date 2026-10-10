"""Vista previa del Radar con un perfil sin guardar (``previsualizar_scoring``).

La pregunta que responde es «¿qué cambia si muevo esto?», así que cada test
compara las dos pasadas —perfil de prueba y perfil guardado— sobre el mismo
universo. Sin BD: el repositorio y las señales van doblados con los mismos
helpers que ``test_analytics_scoring``.
"""

from __future__ import annotations

from unittest.mock import patch

import services.analytics.scoring as sc_mod
from services.analytics.scoring import ScoringProfile, previsualizar_scoring
from tests.test_analytics_scoring import _patch_dismissals, _patch_signals, _repo_data, _rows

#: Todo el peso en lo que distingue a las filas impares de `_rows`: su título
#: lleva «consultoría» y el de las pares no.
_PRUEBA = ScoringProfile(
    weights={"afinidad": 70, "importe": 30},
    afinidad_keywords=["consultoría"],
)


def _previa(perfil: ScoringProfile, *, guardado: dict | None = None, filas: int = 30, **kwargs):
    comp, marg = _patch_signals()
    with (
        _repo_data(_rows(filas)),
        comp,
        marg,
        _patch_dismissals(kwargs.pop("descartadas", [])),
        patch("db.repositories.user_profiles.get_own_user_profile", return_value=guardado),
    ):
        return previsualizar_scoring(perfil, user_key="u1", **kwargs)


def test_sin_cambios_cada_fila_conserva_su_puesto_y_su_score():
    """Probar los pesos que ya aplican no mueve nada: no hay salto que enseñar."""
    previa = _previa(ScoringProfile())

    assert len(previa.opportunities) == 10
    assert previa.total_scored == 30
    assert previa.salen == []
    assert [o.posicion for o in previa.opportunities] == list(range(1, 11))
    for oportunidad in previa.opportunities:
        assert oportunidad.posicion_actual == oportunidad.posicion
        assert oportunidad.score_actual == oportunidad.score


def test_el_perfil_de_prueba_reordena_y_dice_quien_sale():
    previa = _previa(_PRUEBA)

    impares = {f"L{i:03d}" for i in range(1, 30, 2)}
    primeras = [o.id_externo for o in previa.opportunities]
    assert set(primeras) <= impares
    assert [o.posicion for o in previa.opportunities] == list(range(1, 11))
    scores = [o.score for o in previa.opportunities]
    assert scores == sorted(scores, reverse=True)
    assert previa.afinidad_origen == "perfil"

    # Hoy (pesos globales, sin palabras clave) manda el importe, que crece con
    # el índice: entre las diez primeras hay pares, y esas son las que salen.
    assert previa.salen
    for desplazada in previa.salen:
        assert desplazada.id_externo not in impares
        assert desplazada.posicion_actual <= 10 < desplazada.posicion
    puestos_actuales = [o.posicion_actual for o in previa.salen]
    assert puestos_actuales == sorted(puestos_actuales)


def test_el_puesto_actual_es_el_del_ranking_que_sirve_el_radar():
    comp, marg = _patch_signals()
    with _repo_data(_rows(30)), comp, marg:
        radar = sc_mod.get_scoring(sc_mod.ScoringFilters(limit=500))
    puesto_en_radar = {o.id_externo: n for n, o in enumerate(radar.opportunities, start=1)}
    score_en_radar = {o.id_externo: o.score for o in radar.opportunities}

    previa = _previa(_PRUEBA)

    for oportunidad in [*previa.opportunities, *previa.salen]:
        assert oportunidad.posicion_actual == puesto_en_radar[oportunidad.id_externo]
        assert oportunidad.score_actual == score_en_radar[oportunidad.id_externo]


def test_se_compara_contra_el_perfil_guardado_no_contra_los_pesos_globales():
    """Con el mismo perfil ya guardado, la prueba no cambia nada."""
    guardado = {
        "weights": dict(_PRUEBA.weights or {}),
        "afinidad_keywords": list(_PRUEBA.afinidad_keywords or []),
        "cpvs": None,
        "importe_min": None,
        "importe_max": None,
    }

    previa = _previa(_PRUEBA, guardado=guardado)

    assert previa.salen == []
    assert all(o.posicion_actual == o.posicion for o in previa.opportunities)
    assert all(o.score_actual == o.score for o in previa.opportunities)


def test_lo_descartado_en_el_radar_no_entra_en_la_vista_previa():
    descartadas = ["L029", "L027", "L025"]

    previa = _previa(_PRUEBA, descartadas=descartadas)

    assert previa.total_scored == 27
    assert not {o.id_externo for o in previa.opportunities} & set(descartadas)


def test_el_limite_acota_las_dos_listas():
    previa = _previa(_PRUEBA, limit=3)

    assert len(previa.opportunities) == 3
    assert len(previa.salen) <= 3


def test_fuera_de_rango_baja_el_score_de_la_prueba_y_no_el_actual():
    """El rango de importe solo existe en el perfil de prueba: resta ahí."""
    previa = _previa(ScoringProfile(importe_max=50_000.0), limit=25)

    por_id = {o.id_externo: o for o in [*previa.opportunities, *previa.salen]}
    # L029 vale 300.000 €: fuera del rango de la prueba, dentro de «sin rango».
    assert por_id["L029"].score < por_id["L029"].score_actual


def test_sin_universo_la_vista_previa_sale_vacia():
    comp, marg = _patch_signals()
    with _repo_data([]), comp, marg:
        previa = previsualizar_scoring(_PRUEBA, user_key="u1")

    assert previa.opportunities == []
    assert previa.salen == []
    assert previa.total_scored == 0
