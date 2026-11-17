"""Tests de PU learning (pesos de muestra para negativos ambiguos)."""

from __future__ import annotations

import pandas as pd

from services.ml.classifier_pipeline import build_dataset_rows


def _make_df() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    # 10 positivos (raw_keywords presente)
    for i in range(10):
        rows.append(
            {
                "titulo": f"Implantacion SAP proyecto {i}",
                "descripcion": "ERP financiero",
                "raw_keywords": "SAP",
                "cpv": "72000000",
            }
        )
    # 10 negativos confiables (CPV no-TI)
    for i in range(10):
        rows.append(
            {
                "titulo": f"Obra de reforma {i}",
                "descripcion": "albanileria",
                "raw_keywords": None,
                "cpv": "45000000",
            }
        )
    # 5 negativos ambiguos (CPV TI 48/72 sin keywords): potenciales SAP
    for i in range(5):
        rows.append(
            {
                "titulo": f"Suministro software {i}",
                "descripcion": "licencias",
                "raw_keywords": None,
                "cpv": "48000000",
            }
        )
    return pd.DataFrame(rows)


class TestBuildDatasetPUWeights:
    def test_las_dos_clases_estan(self) -> None:
        assert {f.label for f in build_dataset_rows(_make_df())} == {0, 1}

    def test_positives_have_full_weight(self) -> None:
        for fila in build_dataset_rows(_make_df()):
            if fila.label == 1:
                assert fila.weight == 1.0

    def test_ambiguous_negatives_downweighted(self) -> None:
        # Debe haber al menos un negativo TI con peso reducido (< 1.0).
        filas = build_dataset_rows(_make_df())
        reduced = [f.weight for f in filas if f.label == 0 and f.weight < 1.0]
        assert reduced, "Los negativos ambiguos (CPV TI) deben tener peso < 1.0"
        assert all(w == 0.5 for w in reduced)

    def test_reliable_negatives_full_weight(self) -> None:
        # Los negativos no-TI mantienen peso 1.0.
        filas = build_dataset_rows(_make_df())
        full = [f.weight for f in filas if f.label == 0 and f.weight == 1.0]
        assert full, "Los negativos confiables (CPV no-TI) deben mantener peso 1.0"
