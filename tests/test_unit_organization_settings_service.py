"""Configuración de la organización: quién lee, quién escribe y qué se valida."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

import services.organizations as mod
from shared.dto import OrganizationSettings


def _membresia(role: str) -> dict[str, Any]:
    return {"organization_id": 7, "user_id": 1, "role": role, "status": "active"}


def test_cualquier_miembro_lee_y_recibe_el_catalogo_de_familias() -> None:
    with (
        patch.object(mod._repo, "get_active_membership", return_value=_membresia("viewer")),
        patch.object(mod._repo, "get_settings", return_value={"tecnologias": ["SAP"]}),
    ):
        out = mod.get_settings(1, 7)
    assert out.organization_id == 7
    assert out.tecnologias == ["SAP"]
    assert "SAP" in out.tecnologias_disponibles and "MICROSOFT" in out.tecnologias_disponibles


def test_una_configuracion_vacia_o_corrupta_se_lee_como_sin_acotar() -> None:
    with (
        patch.object(mod._repo, "get_active_membership", return_value=_membresia("member")),
        patch.object(mod._repo, "get_settings", return_value={"tecnologias": None}),
    ):
        assert mod.get_settings(1, 7).tecnologias == []


def test_solo_owner_o_admin_escriben() -> None:
    with patch.object(mod._repo, "get_active_membership", return_value=_membresia("member")):
        with pytest.raises(mod.OrganizationPermissionError):
            mod.update_settings(1, 7, OrganizationSettings(tecnologias=["SAP"]))
    with patch.object(mod._repo, "get_active_membership", return_value=_membresia("viewer")):
        with pytest.raises(mod.OrganizationPermissionError):
            mod.update_settings(1, 7, OrganizationSettings(tecnologias=["SAP"]))


def test_una_familia_desconocida_se_rechaza_antes_de_escribir() -> None:
    with (
        patch.object(mod._repo, "get_active_membership", return_value=_membresia("admin")),
        patch.object(mod._repo, "update_settings") as escribir,
    ):
        with pytest.raises(ValueError, match="INVENTADA"):
            mod.update_settings(1, 7, OrganizationSettings(tecnologias=["SAP", "inventada"]))
    escribir.assert_not_called()


def test_el_owner_escribe_y_recibe_lo_persistido() -> None:
    with (
        patch.object(mod._repo, "get_active_membership", return_value=_membresia("owner")),
        patch.object(
            mod._repo, "update_settings", return_value={"tecnologias": ["SAP", "ORACLE"]}
        ) as escribir,
    ):
        out = mod.update_settings(1, 7, OrganizationSettings(tecnologias=["sap", "Oracle"]))
    escribir.assert_called_once_with(7, {"tecnologias": ["SAP", "ORACLE"]})
    assert out.tecnologias == ["SAP", "ORACLE"]
    assert out.organization_id == 7
