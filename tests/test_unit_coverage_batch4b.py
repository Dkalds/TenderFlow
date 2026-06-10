"""Unit tests for shared.schemas."""

from __future__ import annotations

import unittest

import pandas as pd


class TestSchemas(unittest.TestCase):
    def test_pandera_installed_flag(self):
        from shared.schemas import _pandera_installed

        self.assertIsInstance(_pandera_installed(), bool)

    def test_validate_licitaciones_returns_df(self):
        from shared.schemas import validate_licitaciones

        df = pd.DataFrame(
            {
                "id_externo": ["1"],
                "titulo": ["T"],
                "organo_contratacion": ["O"],
                "importe": [1.0],
                "estado": ["P"],
                "fecha_publicacion": [pd.Timestamp.now()],
                "ccaa": ["M"],
                "tecnologia": ["S"],
                "tipo_contrato": ["S"],
            }
        )
        result = validate_licitaciones(df, lazy=True)
        self.assertEqual(len(result), 1)

    def test_validate_adjudicaciones_returns_df(self):
        from shared.schemas import validate_adjudicaciones

        df = pd.DataFrame(
            {
                "licitacion_id": ["1"],
                "nombre": ["N"],
                "importe_adjudicado": [1.0],
                "fecha_adjudicacion": [pd.Timestamp.now()],
            }
        )
        result = validate_adjudicaciones(df, lazy=True)
        self.assertEqual(len(result), 1)

    def test_noop_schema_when_pandera_missing(self):
        from shared.schemas import _NoOpSchema

        df = pd.DataFrame({"a": [1]})
        result = _NoOpSchema.validate(df)
        self.assertIs(result, df)

    def test_kpi_snapshot_schema(self):
        from shared.schemas import KpiSnapshotSchema

        df = pd.DataFrame(
            {
                "metric_name": ["total"],
                "metric_value": [42.0],
                "computed_at": ["2024-01-01"],
            }
        )
        result = KpiSnapshotSchema.validate(df, lazy=True)
        self.assertEqual(len(result), 1)
