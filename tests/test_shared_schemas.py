"""Tests para shared/schemas.py — validación de DataFrames con pandera."""

from __future__ import annotations

import pytest


def test_schemas_importable():
    """El módulo se importa sin error, incluso si pandera no está instalado."""
    from shared import schemas

    assert hasattr(schemas, "LicitacionSchema")
    assert hasattr(schemas, "AdjudicacionSchema")
    assert hasattr(schemas, "KpiSnapshotSchema")


def test_validate_licitaciones_helper_exists():
    from shared.schemas import validate_licitaciones

    assert callable(validate_licitaciones)


def test_validate_adjudicaciones_helper_exists():
    from shared.schemas import validate_adjudicaciones

    assert callable(validate_adjudicaciones)


def test_validate_licitaciones_no_pandera_passthrough():
    """Sin pandera, validate_licitaciones devuelve el df sin error."""
    pytest.importorskip("pandas")
    import pandas as pd

    from shared.schemas import validate_licitaciones

    df = pd.DataFrame(
        {
            "id_externo": ["TEST-001"],
            "titulo": ["SAP ERP"],
            "organo_contratacion": ["Ministerio"],
            "importe": [100000.0],
            "estado": ["PUB"],
            "fecha_publicacion": ["2024-01-01"],
            "ccaa": ["Madrid"],
            "tecnologia": ["SAP"],
            "tipo_contrato": ["servicios"],
        }
    )
    # Debe funcionar con o sin pandera instalado
    result = validate_licitaciones(df)
    assert result is not None


def test_validate_adjudicaciones_no_pandera_passthrough():
    pytest.importorskip("pandas")
    import pandas as pd

    from shared.schemas import validate_adjudicaciones

    df = pd.DataFrame(
        {
            "licitacion_id": ["TEST-001"],
            "nombre": ["Empresa SA"],
            "importe_adjudicado": [95000.0],
            "fecha_adjudicacion": ["2024-06-01"],
        }
    )
    result = validate_adjudicaciones(df)
    assert result is not None


def test_licitacion_schema_valid():
    """Con pandera disponible, schema valida correctamente un DataFrame válido."""
    pytest.importorskip("pandera")
    import pandas as pd

    from shared.schemas import LicitacionSchema

    if not hasattr(LicitacionSchema, "validate"):
        pytest.skip("LicitacionSchema es NoOp (pandera no disponible)")

    df = pd.DataFrame(
        {
            "id_externo": ["TEST-001", "TEST-002"],
            "titulo": ["SAP ERP", "Oracle DB"],
            "organo_contratacion": ["Min A", "Min B"],
            "importe": [100000.0, 200000.0],
            "estado": ["PUB", "ADJ"],
            "fecha_publicacion": ["2024-01-01", "2024-02-01"],
            "ccaa": ["Madrid", "Cataluña"],
            "tecnologia": ["SAP", "ORACLE"],
            "tipo_contrato": ["servicios", "suministros"],
        }
    )
    # Si pandera está disponible, debe validar sin error
    result = LicitacionSchema.validate(df, lazy=True)
    assert len(result) == 2
