"""S3.3 — pesos propuestos a partir de lo ganado y lo perdido, nunca aplicados solos.

Dos mitades, las dos sin Postgres:

- ``proponer_pesos`` es pura y aquí se le fija **la dirección** del ajuste, que
  es la única propiedad que un usuario puede comprobar a ojo: la dimensión que
  valía más en las ganadas que en las perdidas sube.
- ``get_weights_proposal`` se prueba con el repositorio suplantado, para fijar
  el umbral de veinte cierres y que por debajo no se enseñe ninguna propuesta.

Que aplicar la propuesta quede en ``audit_log`` necesita base y vive en
``tests/test_s3_lotes_api.py``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import services.pursuits as pursuits_svc
from services.pursuits import (
    PESOS_MINIMO_CIERRES,
    PursuitValidationError,
    proponer_pesos,
)
from shared.scoring_weights import WEIGHTS_TOTAL, validate_scoring_weights

_PESOS_BASE = {
    "importe": 20,
    "plazo": 15,
    "competencia": 20,
    "margen": 20,
    "afinidad": 15,
    "senal_tecnica": 10,
}


def _desglose(**dimensiones: float) -> dict[str, float]:
    """Un desglose sellado con todas las dimensiones planas salvo las dadas."""
    base = dict.fromkeys(_PESOS_BASE, 10.0)
    base.update(dimensiones)
    return base


def test_una_dimension_mas_alta_en_ganadas_sube_de_peso() -> None:
    """La dirección del ajuste, que es lo único que se le puede exigir.

    ``margen`` vale el doble en las ganadas que en las perdidas y el resto de
    dimensiones no distingue: su peso tiene que subir, y la subida la tiene que
    pagar el resto — la suma es constante.
    """
    ganadas = [_desglose(margen=20.0) for _ in range(12)]
    perdidas = [_desglose(margen=5.0) for _ in range(10)]

    propuestos, evidencia = proponer_pesos(_PESOS_BASE, ganadas, perdidas)

    assert propuestos["margen"] > _PESOS_BASE["margen"]
    margen = next(d for d in evidencia if d.dimension == "margen")
    assert margen.media_ganadas == 20.0
    assert margen.media_perdidas == 5.0
    assert margen.delta == 15.0
    assert margen.peso_propuesto == propuestos["margen"]
    # Lo que sube margen lo pierden las demás: es una redistribución.
    assert any(propuestos[dim] < _PESOS_BASE[dim] for dim in _PESOS_BASE if dim != "margen")


def test_una_dimension_mas_alta_en_perdidas_baja_de_peso() -> None:
    """El simétrico del anterior: lo que acompaña a perder pesa menos."""
    ganadas = [_desglose(competencia=2.0) for _ in range(12)]
    perdidas = [_desglose(competencia=18.0) for _ in range(10)]

    propuestos, _ = proponer_pesos(_PESOS_BASE, ganadas, perdidas)

    assert propuestos["competencia"] < _PESOS_BASE["competencia"]


def test_la_propuesta_sigue_siendo_un_reparto_valido() -> None:
    """Suma 100, sin negativos y con ``afinidad`` por debajo del total.

    Es la misma validación que aplica ``PUT /me/profile``: una propuesta que no
    la pasara dejaría el Radar mandando el corpus entero a banda Descarte.
    """
    ganadas = [_desglose(afinidad=40.0, margen=25.0) for _ in range(15)]
    perdidas = [_desglose(competencia=30.0, plazo=22.0) for _ in range(15)]

    propuestos, _ = proponer_pesos(_PESOS_BASE, ganadas, perdidas)

    assert sum(propuestos.values()) == WEIGHTS_TOTAL
    validate_scoring_weights(propuestos)


def test_sin_diferencia_entre_ganadas_y_perdidas_no_se_mueve_nada() -> None:
    """Sin evidencia que separe, la propuesta honesta es dejarlo como está."""
    iguales = [_desglose() for _ in range(12)]

    propuestos, evidencia = proponer_pesos(_PESOS_BASE, iguales, iguales)

    assert propuestos == _PESOS_BASE
    assert all(dimension.delta == 0.0 for dimension in evidencia)


def test_el_paso_maximo_acota_cuanto_se_mueve_una_dimension() -> None:
    """Un ajuste es una sugerencia sobre evidencia parcial, no un salto."""
    ganadas = [_desglose(margen=100.0) for _ in range(12)]
    perdidas = [_desglose(margen=0.0) for _ in range(12)]

    propuestos, _ = proponer_pesos(_PESOS_BASE, ganadas, perdidas, paso_max=5)

    for dimension, peso in propuestos.items():
        assert abs(peso - _PESOS_BASE[dimension]) <= 5


# ── El umbral de veinte cierres ─────────────────────────────────────────────


class _RepoFalso:
    """Sustituye a ``PursuitRepository`` para no necesitar Postgres."""

    def __init__(self, filas: list[dict[str, Any]]) -> None:
        self.filas = filas

    def closed_scored_rows(self, organization_id: int, **_kwargs: Any) -> list[dict[str, Any]]:
        return self.filas


def _filas_cerradas(ganadas: int, perdidas: int) -> list[dict[str, Any]]:
    filas = [
        {"id": i, "outcome": "won", "desglose_al_abrir": json.dumps(_desglose(margen=20.0))}
        for i in range(ganadas)
    ]
    filas += [
        {
            "id": 1000 + i,
            "outcome": "lost",
            "desglose_al_abrir": json.dumps(_desglose(margen=5.0)),
        }
        for i in range(perdidas)
    ]
    return filas


@pytest.fixture
def _organizacion_suplantada(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pursuits_svc, "resolve_organization", lambda *_a, **_k: (7, "owner"), raising=True
    )
    monkeypatch.setattr(
        pursuits_svc, "_pesos_vigentes", lambda *_a, **_k: (dict(_PESOS_BASE), "global")
    )


def test_con_menos_de_veinte_cierres_devuelve_insuficiente(
    monkeypatch: pytest.MonkeyPatch, _organizacion_suplantada: None
) -> None:
    """Diecinueve cierres no sostienen un ajuste, y se dice con su base."""
    monkeypatch.setattr(pursuits_svc, "_repo", _RepoFalso(_filas_cerradas(10, 9)))

    propuesta = pursuits_svc.get_weights_proposal(1, user_key="uk", organization_id=7)

    assert propuesta.estado == "insuficiente"
    assert propuesta.pesos_propuestos is None
    assert propuesta.dimensiones == []
    # La base viaja igual: es lo que permite decir "19 de 20".
    assert (propuesta.n_ganadas, propuesta.n_perdidas) == (10, 9)
    assert propuesta.n_cierres == 19
    assert propuesta.minimo_cierres == PESOS_MINIMO_CIERRES


def test_con_veinte_cierres_ya_hay_propuesta(
    monkeypatch: pytest.MonkeyPatch, _organizacion_suplantada: None
) -> None:
    monkeypatch.setattr(pursuits_svc, "_repo", _RepoFalso(_filas_cerradas(10, 10)))

    propuesta = pursuits_svc.get_weights_proposal(1, user_key="uk", organization_id=7)

    assert propuesta.estado == "propuesta"
    assert propuesta.n_cierres == PESOS_MINIMO_CIERRES
    assert propuesta.pesos_propuestos is not None
    assert propuesta.pesos_propuestos["margen"] > _PESOS_BASE["margen"]
    assert propuesta.origen_pesos_actuales == "global"


def test_un_desglose_ilegible_no_entra_ni_en_el_numerador_ni_en_el_denominador(
    monkeypatch: pytest.MonkeyPatch, _organizacion_suplantada: None
) -> None:
    """Contarlo en la base declarada sería mentir sobre la evidencia."""
    filas = _filas_cerradas(10, 10)
    filas.append({"id": 9999, "outcome": "won", "desglose_al_abrir": "{no es json"})
    monkeypatch.setattr(pursuits_svc, "_repo", _RepoFalso(filas))

    propuesta = pursuits_svc.get_weights_proposal(1, user_key="uk", organization_id=7)

    assert propuesta.n_cierres == 20
    assert propuesta.n_ganadas == 10


def test_aplicar_sin_propuesta_no_escribe_nada(
    monkeypatch: pytest.MonkeyPatch, _organizacion_suplantada: None
) -> None:
    """El camino de aplicación se detiene antes de tocar el perfil."""
    monkeypatch.setattr(pursuits_svc, "_repo", _RepoFalso(_filas_cerradas(1, 1)))

    with pytest.raises(PursuitValidationError) as excinfo:
        pursuits_svc.apply_weights_proposal(1, user_key="uk", organization_id=7)

    assert str(PESOS_MINIMO_CIERRES) in str(excinfo.value)
