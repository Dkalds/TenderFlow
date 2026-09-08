"""El historial «contra mí» sabe quiénes somos cuando la organización lo declaró.

`construir_batallas` acepta `nif_propio` desde que se escribió para S2.1, y
`batallas_de_usuario` —su único llamador de producción— no se lo pasaba. El
efecto era que `sin_nif_propio` salía `True` siempre, incluso con el NIF de la
organización declarado en `organization_nifs`: la pantalla avisaba de una
ignorancia que ya no existía, y un aviso permanente es un aviso que nadie lee.

Estos tests fijan el cableado, no la lógica de `construir_batallas`, que ya
cubre `tests/test_guion_batallas_hub.py`.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from services.competitive.batallas import batallas_de_usuario
from services.organizations import OrganizationAccessError
from services.pursuit_awards import IdentidadFiscal

_PROPIA = IdentidadFiscal(nifs=frozenset({"B12345678"}), empresa_ids=frozenset({42}))
_SIN_NIF = IdentidadFiscal()
_REPO = "db.repositories.pursuits.PursuitRepository.cruces_con_competidor"
# `batallas_de_usuario` importa las dos dentro del cuerpo de la función (evita
# un ciclo con `services.organizations`), así que no son atributos del módulo:
# se parchean en su origen.
_RESOLVER = "services.organizations.resolve_organization"
_IDENTIDAD = "services.pursuit_awards.identidad_fiscal"


def _cruces() -> list[dict[str, Any]]:
    return [
        {
            "licitacion_id": "LIC-1",
            "titulo": "Servicio de mantenimiento",
            "organo_contratacion": "Órgano",
            "fecha_adjudicacion": "2026-05-01",
            "importe": 100000.0,
            "offer_price_eur": 90000.0,
            "importe_adjudicado": 85000.0,
            "outcome": "lost",
            "adjudicatario_key": "rival",
        }
    ]


def test_con_nif_declarado_la_pantalla_deja_de_avisar() -> None:
    with (
        patch(_RESOLVER, return_value=(7, "owner")) as resolver,
        patch(_REPO, return_value=_cruces()),
        patch(_IDENTIDAD, return_value=_PROPIA) as identidad,
    ):
        resultado = batallas_de_usuario(3, "rival", organization_id=7)

    resolver.assert_called_once_with(3, 7)
    # La identidad se lee de la organización **resuelta**, no de la pedida.
    identidad.assert_called_once_with(7)
    assert resultado.sin_nif_propio is False
    assert resultado.n == 1


def test_sin_nifs_declarados_el_aviso_se_mantiene() -> None:
    """Una organización que no declaró NIF sigue sin saber quién es: el aviso
    es correcto ahí y solo ahí."""
    with (
        patch(_RESOLVER, return_value=(7, "owner")),
        patch(_REPO, return_value=_cruces()),
        patch(_IDENTIDAD, return_value=_SIN_NIF),
    ):
        resultado = batallas_de_usuario(3, "rival")

    assert resultado.sin_nif_propio is True


def test_un_fallo_leyendo_el_nif_no_tumba_el_historial() -> None:
    """Degradar al aviso es peor que no tener pantalla. Mismo criterio que
    `services/competitive/socios.py::_identidad_de`."""
    with (
        patch(_RESOLVER, return_value=(7, "owner")),
        patch(_REPO, return_value=_cruces()),
        patch(_IDENTIDAD, side_effect=RuntimeError("BD caída")),
    ):
        resultado = batallas_de_usuario(3, "rival")

    assert resultado.sin_nif_propio is True
    assert resultado.n == 1


def test_pedir_una_organizacion_ajena_sigue_siendo_un_403() -> None:
    """El degradado del NIF no puede tragarse un fallo de permisos."""
    with (
        patch(_RESOLVER, side_effect=OrganizationAccessError("No perteneces a esa organización.")),
        pytest.raises(OrganizationAccessError),
    ):
        batallas_de_usuario(3, "rival", organization_id=99)
