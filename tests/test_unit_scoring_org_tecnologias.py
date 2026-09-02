"""Las familias de la organización acotan el Radar sólo cuando nadie filtra a mano."""

from __future__ import annotations

from unittest.mock import patch

from services.analytics.scoring import _tecnologias_de_organizacion


def test_sin_organizacion_no_acota() -> None:
    assert _tecnologias_de_organizacion(None) is None


def test_devuelve_csv_normalizado() -> None:
    with patch(
        "db.repositories.organizations.OrganizationRepository.get_settings",
        return_value={"tecnologias": [" sap", "Microsoft", ""]},
    ):
        assert _tecnologias_de_organizacion(7) == "SAP,MICROSOFT"


def test_configuracion_vacia_o_corrupta_degrada_al_universo_entero() -> None:
    with patch(
        "db.repositories.organizations.OrganizationRepository.get_settings",
        return_value={"tecnologias": []},
    ):
        assert _tecnologias_de_organizacion(7) is None
    with patch(
        "db.repositories.organizations.OrganizationRepository.get_settings",
        return_value={"tecnologias": "SAP"},
    ):
        assert _tecnologias_de_organizacion(7) is None


def test_un_fallo_de_lectura_no_vacia_la_bandeja() -> None:
    with patch(
        "db.repositories.organizations.OrganizationRepository.get_settings",
        side_effect=RuntimeError("sin base de datos"),
    ):
        assert _tecnologias_de_organizacion(7) is None
