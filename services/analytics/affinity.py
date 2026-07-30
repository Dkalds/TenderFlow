"""Afinidad semántica entre oportunidades y el portfolio explícito del usuario.

El portfolio se construye únicamente con señales declaradas: keywords, CPVs y
referencias/contratos aportados por el perfil. Nunca se infiere una empresa por
nombre. Si el motor de embeddings no está disponible (o falla), se conserva el
fallback determinista histórico de coincidencias de keywords.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from observability.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class AffinityPortfolio:
    """Señales explícitas que describen el trabajo que una organización sabe hacer."""

    keywords: tuple[str, ...] = ()
    cpvs: tuple[str, ...] = ()
    contracts: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return bool(self.keywords or self.cpvs or self.contracts)


@dataclass(frozen=True)
class AffinityBatch:
    """Resultado reproducible para un lote de oportunidades."""

    scores: dict[str, float] = field(default_factory=dict)
    method: str = "unavailable"


def _clean(values: list[Any] | tuple[Any, ...] | None) -> tuple[str, ...]:
    if not values:
        return ()
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def build_portfolio(
    *,
    keywords: list[str] | None = None,
    cpvs: list[str] | None = None,
    contracts: list[Any] | None = None,
) -> AffinityPortfolio:
    """Normaliza un perfil, aceptando contratos como texto o mappings tipados."""
    contract_texts: list[str] = []
    for contract in contracts or []:
        if isinstance(contract, str):
            contract_texts.append(contract)
            continue
        if isinstance(contract, dict):
            parts = [
                str(contract.get(key) or "").strip() for key in ("titulo", "descripcion", "cpv")
            ]
            text = " · ".join(part for part in parts if part)
            if text:
                contract_texts.append(text)
    return AffinityPortfolio(
        keywords=_clean(keywords),
        cpvs=_clean(cpvs),
        contracts=_clean(contract_texts),
    )


def _candidate_text(row: pd.Series) -> str:
    parts = [
        str(row.get("titulo") or "").strip(),
        str(row.get("descripcion") or "").strip(),
        str(row.get("cpv") or "").strip(),
    ]
    return " · ".join(part for part in parts if part)


def _cpv_similarity(candidate: Any, portfolio_cpvs: tuple[str, ...]) -> float:
    candidate_cpv = str(candidate or "").strip()
    if not candidate_cpv:
        return 0.0
    for portfolio_cpv in portfolio_cpvs:
        if candidate_cpv == portfolio_cpv:
            return 1.0
    if len(candidate_cpv) >= 4 and any(
        len(portfolio_cpv) >= 4 and candidate_cpv[:4] == portfolio_cpv[:4]
        for portfolio_cpv in portfolio_cpvs
    ):
        return 0.8
    return 0.0


def _fallback_score(row: pd.Series, portfolio: AffinityPortfolio) -> float:
    """Fallback histórico: ``min(hits/3, 1)``; CPV explícito añade match exacto."""
    title = str(row.get("titulo") or "").casefold()
    hits = sum(1 for keyword in portfolio.keywords if keyword.casefold() in title)
    keyword_score = min(hits / 3.0, 1.0)
    return max(keyword_score, _cpv_similarity(row.get("cpv"), portfolio.cpvs))


def score_affinity_batch(df: pd.DataFrame, portfolio: AffinityPortfolio) -> AffinityBatch:
    """Puntúa afinidad 0..1 en lote, con embeddings normalizados y fallback estable."""
    if df.empty or not portfolio.available:
        return AffinityBatch()

    ids = [str(value) for value in df.get("id_externo", pd.Series(dtype=str)).tolist()]
    rows = [row for _, row in df.iterrows()]
    fallback = {
        row_id: round(_fallback_score(row, portfolio), 6)
        for row_id, row in zip(ids, rows, strict=True)
    }

    try:
        from services.embeddings import embeddings_available, encode_texts

        if not embeddings_available():
            return AffinityBatch(scores=fallback, method="keyword_cpv_fallback")

        portfolio_items = [
            *portfolio.keywords,
            *(f"CPV {cpv}" for cpv in portfolio.cpvs),
            *portfolio.contracts,
        ]
        candidates = [_candidate_text(row) for row in rows]
        vectors = encode_texts([*portfolio_items, *candidates])
        split = len(portfolio_items)
        portfolio_vectors = np.asarray(vectors[:split], dtype=float)
        candidate_vectors = np.asarray(vectors[split:], dtype=float)
        if (
            portfolio_vectors.ndim != 2
            or candidate_vectors.ndim != 2
            or len(candidate_vectors) != len(rows)
        ):
            raise ValueError("shape de embeddings inesperada")

        similarities = candidate_vectors @ portfolio_vectors.T
        semantic_scores = similarities.max(axis=1)
        scores = {
            row_id: round(
                max(
                    0.0,
                    min(1.0, float(semantic)),
                    _cpv_similarity(row.get("cpv"), portfolio.cpvs),
                ),
                6,
            )
            for row_id, row, semantic in zip(ids, rows, semantic_scores, strict=True)
        }
        return AffinityBatch(scores=scores, method="semantic_embeddings")
    except Exception as exc:
        log.warning("scoring_affinity_fallback", error=str(exc))
        return AffinityBatch(scores=fallback, method="keyword_cpv_fallback")
