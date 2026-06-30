"""Tests de PU learning (pesos de muestra para negativos ambiguos)."""

from __future__ import annotations

import pandas as pd

from scraper.ml_pipeline import _build_dataset


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


class TestBuildDatasetBackwardCompat:
    def test_returns_two_tuple_by_default(self) -> None:
        texts, labels = _build_dataset(_make_df())
        assert len(texts) == len(labels)
        assert set(labels) == {0, 1}


class TestBuildDatasetPUWeights:
    def test_returns_weights_aligned(self) -> None:
        texts, labels, weights = _build_dataset(_make_df(), return_weights=True)
        assert len(texts) == len(labels) == len(weights)

    def test_positives_have_full_weight(self) -> None:
        _texts, labels, weights = _build_dataset(_make_df(), return_weights=True)
        for lbl, w in zip(labels, weights, strict=True):
            if lbl == 1:
                assert w == 1.0

    def test_ambiguous_negatives_downweighted(self) -> None:
        # Debe haber al menos un negativo TI con peso reducido (< 1.0).
        _texts, labels, weights = _build_dataset(_make_df(), return_weights=True)
        reduced = [w for lbl, w in zip(labels, weights, strict=True) if lbl == 0 and w < 1.0]
        assert reduced, "Los negativos ambiguos (CPV TI) deben tener peso < 1.0"
        assert all(w == 0.5 for w in reduced)

    def test_reliable_negatives_full_weight(self) -> None:
        # Los negativos no-TI mantienen peso 1.0.
        _texts, labels, weights = _build_dataset(_make_df(), return_weights=True)
        full = [w for lbl, w in zip(labels, weights, strict=True) if lbl == 0 and w == 1.0]
        assert full, "Los negativos confiables (CPV no-TI) deben mantener peso 1.0"
