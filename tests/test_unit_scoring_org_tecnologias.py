"""El ámbito de la organización acota el Radar sólo cuando nadie filtra a mano."""

from __future__ import annotations

from unittest.mock import patch

from services.analytics.scoring import _ambito_como_filtros


def test_sin_organizacion_no_acota() -> None:
    assert _ambito_como_filtros(None, None).tecnologia is None


def test_devuelve_csv_normalizado() -> None:
    with patch(
        "db.repositories.organizations.OrganizationRepository.get_settings",
        return_value={"tecnologias": [" sap", "Microsoft", ""]},
    ):
        assert _ambito_como_filtros(7, None).tecnologia == "SAP,MICROSOFT"


def test_el_filtro_manual_manda_sobre_el_ambito() -> None:
    """Quien filtra a mano ha dicho qué quiere ver; el ámbito es el defecto."""
    with patch(
        "db.repositories.organizations.OrganizationRepository.get_settings",
        return_value={"tecnologias": ["SAP"], "ccaas": ["Madrid"]},
    ):
        filtros = _ambito_como_filtros(7, "ORACLE")
    assert filtros.tecnologia == "ORACLE"
    assert filtros.ccaa is None


def test_el_ambito_no_se_queda_en_las_tecnologias() -> None:
    """CCAA, CPV e importe mínimo se resolvían y se tiraban.

    El admin acotaba su mercado, la respuesta lo aceptaba y el Radar seguía
    puntuando el corpus entero sin decir nada.
    """
    with patch(
        "db.repositories.organizations.OrganizationRepository.get_settings",
        return_value={
            "tecnologias": ["SAP"],
            "cpvs": ["72", "48"],
            "ccaas": ["Madrid", "Cataluña"],
            "importe_min": 100_000,
        },
    ):
        filtros = _ambito_como_filtros(7, None)
    assert filtros.tecnologia == "SAP"
    assert filtros.cpv == "72,48"
    assert filtros.ccaa == "Madrid,Cataluña"
    assert filtros.importe_min == 100_000


def test_configuracion_vacia_o_corrupta_degrada_al_universo_entero() -> None:
    with patch(
        "db.repositories.organizations.OrganizationRepository.get_settings",
        return_value={"tecnologias": []},
    ):
        assert _ambito_como_filtros(7, None).tecnologia is None
    with patch(
        "db.repositories.organizations.OrganizationRepository.get_settings",
        return_value={"tecnologias": "SAP"},
    ):
        assert _ambito_como_filtros(7, None).tecnologia is None


def test_una_clave_de_otra_version_no_tira_el_ambito_entero() -> None:
    """``settings_json`` admite claves nuevas y el modelo declara
    ``extra="forbid"``: validar el blob entero dejaba sin Radar acotado a quien
    tuviera guardada una clave que este build ya no conoce."""
    with patch(
        "db.repositories.organizations.OrganizationRepository.get_settings",
        return_value={"tecnologias": ["SAP"], "clave_de_otra_version": 1},
    ):
        assert _ambito_como_filtros(7, None).tecnologia == "SAP"


def test_un_fallo_de_lectura_no_vacia_la_bandeja() -> None:
    with patch(
        "db.repositories.organizations.OrganizationRepository.get_settings",
        side_effect=RuntimeError("sin base de datos"),
    ):
        assert _ambito_como_filtros(7, None).tecnologia is None
