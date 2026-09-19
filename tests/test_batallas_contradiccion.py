"""«Cerramos perdido y el adjudicatario somos nosotros» no es una derrota.

``construir_batallas`` contaba cualquier ``outcome='lost'`` como ``perdimos``
(o ``ellos_ganaron``). Si la adjudicación observada es a **nuestro** NIF, una
de las dos cosas está mal —el cierre o la adjudicación— y contarla como
derrota era esconder el error en el historial contra un rival. Ahora la fila
queda ``sin_resolver`` con ``contradiccion=True`` y el total se declara.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from services.competitive.batallas import batallas_de_usuario, construir_batallas
from services.pursuit_awards import IdentidadFiscal

_PROPIA = IdentidadFiscal(nifs=frozenset({"Q2826000H"}), empresa_ids=frozenset({42}))


def _cruce(**campos: Any) -> dict[str, Any]:
    return {
        "licitacion_id": "LIC-1",
        "titulo": "Servicio SAP",
        "importe": 100000.0,
        "offer_price_eur": 90000.0,
        "importe_adjudicado": 88000.0,
        "outcome": "lost",
        "adjudicatario_key": "rival",
        "adjudicatario_nif": "A11111111",
        "adjudicatario_empresa_id": 7,
        **campos,
    }


def test_perdido_con_adjudicacion_a_nuestro_nif_se_marca() -> None:
    resultado = construir_batallas(
        "rival",
        [_cruce(adjudicatario_nif="q-2826000-h", adjudicatario_empresa_id=None)],
        nif_propio="Q2826000H",
        identidad=_PROPIA,
    )
    batalla = resultado.batallas[0]
    assert batalla.contradiccion is True
    assert batalla.resultado == "sin_resolver"
    assert resultado.contradicciones == 1
    assert resultado.n == 1  # se cuenta como cruce, no desaparece


def test_perdido_con_adjudicacion_a_nuestro_empresa_id_se_marca() -> None:
    resultado = construir_batallas(
        "rival",
        [_cruce(adjudicatario_nif=None, adjudicatario_empresa_id="42")],
        nif_propio="Q2826000H",
        identidad=_PROPIA,
    )
    assert resultado.batallas[0].contradiccion is True
    assert resultado.batallas[0].resultado == "sin_resolver"


def test_perdido_contra_el_rival_sigue_siendo_ellos_ganaron() -> None:
    resultado = construir_batallas("rival", [_cruce()], identidad=_PROPIA)
    assert resultado.batallas[0].contradiccion is False
    assert resultado.batallas[0].resultado == "ellos_ganaron"
    assert resultado.contradicciones == 0


def test_ganado_con_nuestro_nif_no_es_contradiccion() -> None:
    resultado = construir_batallas(
        "rival",
        [_cruce(outcome="won", adjudicatario_nif="Q2826000H")],
        identidad=_PROPIA,
    )
    assert resultado.batallas[0].contradiccion is False
    assert resultado.batallas[0].resultado == "ganamos"


def test_sin_identidad_no_se_puede_detectar_y_no_se_inventa() -> None:
    resultado = construir_batallas("rival", [_cruce(adjudicatario_nif="Q2826000H")])
    assert resultado.batallas[0].contradiccion is False
    assert resultado.contradicciones == 0


def test_batallas_de_usuario_pasa_la_identidad_completa() -> None:
    with (
        patch("services.organizations.resolve_organization", return_value=(7, "owner")),
        patch(
            "db.repositories.pursuits.PursuitRepository.cruces_con_competidor",
            return_value=[_cruce(adjudicatario_nif="Q2826000H")],
        ),
        patch("services.pursuit_awards.identidad_fiscal", return_value=_PROPIA),
    ):
        resultado = batallas_de_usuario(3, "rival", organization_id=7)

    assert resultado.sin_nif_propio is False
    assert resultado.contradicciones == 1
    assert resultado.batallas[0].resultado == "sin_resolver"
