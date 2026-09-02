"""El DTO de configuración normaliza familias y no admite campos extra."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.dto import OrganizationSettings, OrganizationSettingsOut


def test_normaliza_mayusculas_espacios_y_duplicados_conservando_el_orden() -> None:
    dto = OrganizationSettings(tecnologias=[" sap", "Microsoft", "SAP", "", "oracle "])
    assert dto.tecnologias == ["SAP", "MICROSOFT", "ORACLE"]


def test_vacio_significa_todas_las_familias() -> None:
    assert OrganizationSettings().tecnologias == []
    assert OrganizationSettings(tecnologias=[" ", ""]).tecnologias == []


def test_no_admite_campos_que_el_contrato_no_declara() -> None:
    with pytest.raises(ValidationError):
        OrganizationSettings.model_validate({"tecnologias": [], "otro": 1})


def test_la_salida_lleva_el_catalogo_para_que_el_selector_no_lo_copie() -> None:
    out = OrganizationSettingsOut(
        organization_id=7, tecnologias=["sap"], tecnologias_disponibles=["SAP", "ORACLE"]
    )
    assert out.tecnologias == ["SAP"]
    assert out.tecnologias_disponibles == ["SAP", "ORACLE"]
