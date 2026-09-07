"""Afinidad semántica entre oportunidades y el portfolio explícito del usuario.

El portfolio se construye únicamente con señales declaradas: keywords, CPVs y
referencias/contratos aportados por el perfil. Nunca se infiere una empresa por
nombre. Si el motor de embeddings no está disponible (o falla), se conserva el
fallback determinista histórico de coincidencias de keywords.

**S2.4 — de dónde sale el portfolio.** Hasta 2026-09 solo había una fuente: el
perfil personal de quien mira el Radar. Quien no lo había rellenado —la
mayoría— veía la afinidad neutral en todas las filas, aunque su organización
tuviera declaradas referencias y tecnologías desde S2.2. Ahora hay dos fuentes
y un orden: el perfil personal manda, y la capacidad de la organización lo
suple cuando no lo hay (:func:`resolve_portfolio`). Cuál de las dos se usó no
se calla: viaja en ``PortfolioResolution.origen`` para que el desglose del
Radar pueda decirlo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from observability.logging import get_logger
from shared.dto import OrganizationCapabilities

log = get_logger(__name__)

#: De dónde salió el portfolio con el que se puntuó la afinidad. ``ninguno``
#: significa que no había ninguna señal declarada —ni personal ni corporativa—
#: y la afinidad es la que dan las keywords globales de configuración, que no
#: describen a nadie en particular.
PortfolioOrigen = Literal["perfil", "organizacion", "ninguno"]


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


@dataclass(frozen=True)
class PortfolioResolution:
    """El portfolio con el que se puntúa y de dónde salió."""

    portfolio: AffinityPortfolio
    origen: PortfolioOrigen


def build_portfolio_from_capabilities(
    capabilities: OrganizationCapabilities,
    tecnologias: list[str] | None = None,
) -> AffinityPortfolio:
    """Portfolio derivado del perfil de capacidad de la organización (S2.2).

    Las referencias entran por dos caminos porque miden cosas distintas: su
    ``tecnologia`` es una *keyword* (casa por palabra en título y descripción,
    igual que las del perfil personal) y su texto completo —órgano, tecnología
    y expediente— es un *contract*, que es lo que el motor de embeddings
    compara semánticamente. Las familias declaradas en la configuración de la
    organización se suman como keywords: son lo que dice que vende, aunque
    todavía no tenga una referencia que lo acredite.
    """
    keywords: list[str] = [
        referencia.tecnologia for referencia in capabilities.referencias if referencia.tecnologia
    ]
    keywords.extend(tecnologias or [])
    contracts: list[str] = []
    for referencia in capabilities.referencias:
        partes = [
            referencia.organo,
            referencia.tecnologia or "",
            referencia.expediente_id or "",
        ]
        texto = " · ".join(parte for parte in partes if parte)
        if texto:
            contracts.append(texto)
    return AffinityPortfolio(
        keywords=_clean(keywords),
        cpvs=(),
        contracts=_clean(contracts),
    )


def build_organization_portfolio(organization_id: int) -> AffinityPortfolio:
    """Lee capacidad y familias declaradas de la organización y las convierte.

    Import diferido: ``services/analytics/*`` se importa desde el scorer, que
    corre en caliente en cada request del Radar, y arrastrar los repositorios
    en el import del módulo encarecería incluso a quien no tenga organización.
    """
    from db.repositories.organization_capabilities import OrganizationCapabilitiesRepository
    from db.repositories.organizations import OrganizationRepository

    capabilities = OrganizationCapabilities.model_validate(
        OrganizationCapabilitiesRepository().get(organization_id)
    )
    ajustes = OrganizationRepository().get_settings(organization_id)
    crudas = ajustes.get("tecnologias")
    tecnologias = [str(valor) for valor in crudas] if isinstance(crudas, list) else []
    return build_portfolio_from_capabilities(capabilities, tecnologias)


def resolve_portfolio(
    *,
    keywords: list[str] | None = None,
    cpvs: list[str] | None = None,
    organization_id: int | None = None,
    tiene_perfil: bool = False,
) -> PortfolioResolution:
    """Decide con qué portfolio se puntúa y declara de dónde salió.

    Orden: perfil personal → capacidad de la organización → nada. El perfil
    manda porque es la señal más específica —quien lo rellenó dijo a qué se
    dedica *él*—, y la organización lo suple en vez de mezclarse con él: una
    mezcla haría que el Radar de un especialista se pareciera al de su empresa
    sin que él lo hubiera pedido.

    ``tiene_perfil`` distingue las keywords del usuario de las de
    ``settings.SCORING_AFINIDAD_KEYWORDS``, que el scorer usa como valor por
    defecto. Sin esa distinción, cualquier instalación con keywords globales
    reportaría origen ``perfil`` para todo el mundo.
    """
    personal = build_portfolio(keywords=keywords, cpvs=cpvs)
    if tiene_perfil and personal.available:
        return PortfolioResolution(portfolio=personal, origen="perfil")
    if organization_id is not None:
        try:
            corporativo = build_organization_portfolio(organization_id)
        except Exception as exc:
            log.warning("scoring_affinity_org_portfolio_error", error=str(exc)[:200])
            corporativo = AffinityPortfolio()
        if corporativo.available:
            return PortfolioResolution(portfolio=corporativo, origen="organizacion")
    return PortfolioResolution(portfolio=personal, origen="ninguno")


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


def _keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str] | None:
    """Alternancia con límites de palabra, compilada una vez por lote.

    El fallback comparaba con ``in``: "sap" daba positivo dentro de
    "pasaporte" y "erp" dentro de "superposición", así que la afinidad —cuyo
    peso por defecto es 15— premiaba coincidencias que no existen. Es el mismo
    patrón que ya usa ``scraper/filters.py`` para decidir qué entra a la BD.
    """
    limpias = [kw.strip() for kw in keywords if kw.strip()]
    if not limpias:
        return None
    return re.compile(
        r"\b(" + "|".join(re.escape(kw) for kw in limpias) + r")\b",
        flags=re.IGNORECASE,
    )


def _fallback_score(
    row: pd.Series,
    portfolio: AffinityPortfolio,
    pattern: re.Pattern[str] | None,
) -> float:
    """Fallback histórico: ``min(hits/3, 1)``; CPV explícito añade match exacto.

    Se busca en título **y descripción**: el título de un pliego español dice
    "servicios de mantenimiento del sistema de gestión económica" mucho más a
    menudo de lo que nombra la tecnología.
    """
    hits = 0
    if pattern is not None:
        texto = " ".join(
            part
            for part in (str(row.get("titulo") or ""), str(row.get("descripcion") or ""))
            if part
        )
        hits = len({match.group(0).casefold() for match in pattern.finditer(texto)})
    keyword_score = min(hits / 3.0, 1.0)
    return max(keyword_score, _cpv_similarity(row.get("cpv"), portfolio.cpvs))


def score_affinity_batch(df: pd.DataFrame, portfolio: AffinityPortfolio) -> AffinityBatch:
    """Puntúa afinidad 0..1 en lote, con embeddings normalizados y fallback estable."""
    if df.empty or not portfolio.available:
        return AffinityBatch()

    ids = [str(value) for value in df.get("id_externo", pd.Series(dtype=str)).tolist()]
    rows = [row for _, row in df.iterrows()]
    pattern = _keyword_pattern(portfolio.keywords)
    fallback = {
        row_id: round(_fallback_score(row, portfolio, pattern), 6)
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
