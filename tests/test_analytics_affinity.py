"""Tests focalizados de afinidad semántica y fallback reproducible."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd

from services.analytics.affinity import build_portfolio, score_affinity_batch


def test_affinity_uses_embeddings_in_one_batch() -> None:
    portfolio = build_portfolio(keywords=["migración de ERP"])
    candidates = pd.DataFrame(
        [
            {"id_externo": "SEM", "titulo": "Conversión de plataforma empresarial"},
            {"id_externo": "OTHER", "titulo": "Servicio de jardinería"},
        ]
    )
    # portfolio, SEM y OTHER: vectores normalizados y deterministas.
    vectors = np.asarray([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]])

    with (
        patch("services.embeddings.embeddings_available", return_value=True),
        patch("services.embeddings.encode_texts", return_value=vectors) as encode,
    ):
        result = score_affinity_batch(candidates, portfolio)

    assert result.method == "semantic_embeddings"
    assert result.scores["SEM"] > result.scores["OTHER"]
    encode.assert_called_once()
    assert len(encode.call_args.args[0]) == 3


def test_affinity_fallback_preserves_keyword_hits_and_cpv() -> None:
    portfolio = build_portfolio(
        keywords=["consultoría", "soporte"],
        cpvs=["72000000"],
    )
    candidates = pd.DataFrame(
        [
            {
                "id_externo": "KW",
                "titulo": "Consultoría y soporte de aplicaciones",
                "cpv": "48000000",
            },
            {"id_externo": "CPV", "titulo": "Texto sin match", "cpv": "72009999"},
        ]
    )

    with patch("services.embeddings.embeddings_available", return_value=False):
        result = score_affinity_batch(candidates, portfolio)

    assert result.method == "keyword_cpv_fallback"
    assert result.scores["KW"] == 0.666667
    assert result.scores["CPV"] == 0.8


def test_affinity_without_explicit_portfolio_is_unavailable() -> None:
    result = score_affinity_batch(
        pd.DataFrame([{"id_externo": "X", "titulo": "SAP"}]),
        build_portfolio(),
    )
    assert result.method == "unavailable"
    assert result.scores == {}
