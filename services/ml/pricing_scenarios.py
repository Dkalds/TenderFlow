"""Escenarios V1 de precio basados exclusivamente en distribuciones observadas.

No estima P(ganar): el histórico solo contiene adjudicatarios y no ofrece
labels de ofertas perdedoras vinculadas al portfolio del usuario. La salida
expone tamaño muestral, cohorte usada y cuantiles para evitar falsa precisión.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

import numpy as np
from pydantic import BaseModel, Field

from db.repositories.pricing import PricingRepository
from observability.logging import get_logger
from shared.tender_facts import RateCardFact

_MIN_INDICATIVE_N = 8

log = get_logger(__name__)


class HistoricalDistribution(BaseModel):
    n: int
    p10_discount: float
    p25_discount: float
    p50_discount: float
    p75_discount: float
    p90_discount: float
    observed_interval: tuple[float, float]


class MargenImplicito(BaseModel):
    """F2.4 — qué margen deja este precio, si el pliego publica tarifas.

    Sólo existe cuando la ficha trae ``rate_cards`` **con tarifa y horas**: el
    coste estimado es la suma de tarifa por horas de cada perfil, y sin las dos
    mitades no hay coste que restar. Por eso no se calcula «con lo que haya»:
    un margen con la mitad de los perfiles es un margen equivocado, y encima
    optimista, que es la dirección peligrosa.
    """

    #: Coste que se deduce de las tarifas máximas del pliego.
    coste_estimado_eur: float = Field(ge=0)
    #: Precio menos coste, en euros. Puede ser negativo: ofertar por debajo de
    #: coste es una decisión que se toma a veces, y esconderla no ayuda.
    margen_eur: float
    #: Sobre el precio ofertado, 0-1. `None` con precio cero.
    margen_pct: float | None = None
    #: De dónde sale el coste. Se declara porque las tarifas del pliego son
    #: **máximos**, no los costes reales de la empresa: el margen es un techo,
    #: no una previsión.
    fuente: str = (
        "Tarifas máximas por perfil publicadas en el pliego y horas estimadas; "
        "es un margen techo, no el coste real de la organización."
    )
    #: Perfiles que sostienen el cálculo.
    perfiles: int = Field(ge=1)


class PriceScenario(BaseModel):
    name: Literal["defensivo", "central", "competitivo"]
    discount: float
    price_eur: float
    basis: str
    #: Campo ADITIVO (F2.4). `None` cuando el pliego no publica tarifas y
    #: horas: la UI no enseña la columna en vez de enseñarla vacía.
    margen_implicito: MargenImplicito | None = None


class WinProbabilityGate(BaseModel):
    """Condiciones pendientes antes de publicar una probabilidad numérica."""

    available: bool = False
    blockers: list[str] = Field(
        default_factory=lambda: [
            "faltan ofertas perdedoras y outcomes propios vinculados al precio ofertado",
            "falta validación temporal fuera de muestra por segmento",
            "falta calibración (Brier score y curva por deciles) frente al baseline",
        ]
    )


class PriceScenariosResult(BaseModel):
    licitacion_id: str
    tender_amount_eur: float
    expected_competition: int | None = None
    cohort: list[str] = Field(default_factory=list)
    sample_quality: Literal["robusta", "indicativa", "insuficiente"]
    distribution: HistoricalDistribution | None = None
    scenarios: list[PriceScenario] = Field(default_factory=list)
    win_probability_gate: WinProbabilityGate = Field(default_factory=WinProbabilityGate)
    methodology: str = "Distribución empírica de bajas en adjudicaciones comparables observadas."
    disclaimer: str = (
        "Estos escenarios NO son una P(ganar) causal ni garantizan adjudicación. "
        "Son referencias descriptivas del histórico observado; no incluyen ofertas perdedoras."
    )


class PricingDataSource(Protocol):
    def get_target(self, licitacion_id: str) -> dict[str, Any] | None: ...

    def load_history(self, *, limit: int = 10_000) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class _HistoryRow:
    organ: str
    cpv4: str
    tender_amount: float
    competition_band: str | None
    discount: float


def _cpv4(value: Any) -> str:
    text = str(value or "").strip()
    return text[:4] if len(text) >= 4 and text[:4].isdigit() else ""


def _competition_band(value: Any) -> str | None:
    try:
        offers = int(value)
    except (TypeError, ValueError):
        return None
    if offers <= 1:
        return "1"
    if offers <= 4:
        return "2-4"
    return "5+"


def _normalise_history(rows: list[dict[str, Any]]) -> list[_HistoryRow]:
    result: list[_HistoryRow] = []
    for row in rows:
        try:
            tender = float(row["importe_licitacion"])
            awarded = float(row["importe_adjudicado"])
        except (KeyError, TypeError, ValueError):
            continue
        if tender <= 0 or awarded <= 0 or awarded > tender:
            continue
        discount = 1.0 - awarded / tender
        if not 0.0 <= discount <= 0.8:
            continue
        result.append(
            _HistoryRow(
                organ=str(row.get("organo_contratacion") or "").strip().casefold(),
                cpv4=_cpv4(row.get("cpv")),
                tender_amount=tender,
                competition_band=_competition_band(row.get("n_ofertas_recibidas")),
                discount=discount,
            )
        )
    return result


def _select_cohort(
    rows: list[_HistoryRow],
    *,
    organ: str,
    cpv4: str,
    amount: float,
    expected_competition: int | None,
) -> tuple[list[_HistoryRow], list[str]]:
    target_band = _competition_band(expected_competition)

    def amount_match(row: _HistoryRow) -> bool:
        return amount * 0.5 <= row.tender_amount <= amount * 2.0

    predicates: list[tuple[list[str], Any]] = [
        (
            ["organo", "cpv4", "importe", "competencia"],
            lambda row: (
                row.organ == organ
                and row.cpv4 == cpv4
                and amount_match(row)
                and row.competition_band == target_band
            ),
        ),
        (
            ["organo", "cpv4", "importe"],
            lambda row: row.organ == organ and row.cpv4 == cpv4 and amount_match(row),
        ),
        (
            ["cpv4", "importe", "competencia"],
            lambda row: (
                row.cpv4 == cpv4 and amount_match(row) and row.competition_band == target_band
            ),
        ),
        (["cpv4", "importe"], lambda row: row.cpv4 == cpv4 and amount_match(row)),
        (["cpv4"], lambda row: row.cpv4 == cpv4),
        (["importe"], amount_match),
        (["global"], lambda _row: True),
    ]
    # No fingir una dimensión ausente.
    predicates = [
        (dimensions, predicate)
        for dimensions, predicate in predicates
        if ("organo" not in dimensions or organ)
        and ("cpv4" not in dimensions or cpv4)
        and ("competencia" not in dimensions or target_band is not None)
    ]
    first_non_empty: tuple[list[_HistoryRow], list[str]] | None = None
    for dimensions, predicate in predicates:
        cohort = [row for row in rows if predicate(row)]
        if cohort and first_non_empty is None:
            first_non_empty = (cohort, dimensions)
        if len(cohort) >= _MIN_INDICATIVE_N:
            return cohort, dimensions
    return first_non_empty or ([], ["global"])


def _distribution(discounts: list[float]) -> HistoricalDistribution:
    p10, p25, p50, p75, p90 = np.quantile(discounts, [0.10, 0.25, 0.50, 0.75, 0.90])
    return HistoricalDistribution(
        n=len(discounts),
        p10_discount=round(float(p10), 4),
        p25_discount=round(float(p25), 4),
        p50_discount=round(float(p50), 4),
        p75_discount=round(float(p75), 4),
        p90_discount=round(float(p90), 4),
        observed_interval=(round(float(p10), 4), round(float(p90), 4)),
    )


def get_price_scenarios(
    licitacion_id: str,
    *,
    expected_competition: int | None = None,
    repository: PricingDataSource | None = None,
) -> PriceScenariosResult | None:
    """Calcula tres referencias de precio; ``None`` significa licitación inexistente."""
    repo = repository or PricingRepository()
    target = repo.get_target(licitacion_id)
    if target is None:
        return None
    amount = float(target.get("importe") or 0.0)
    if amount <= 0:
        return PriceScenariosResult(
            licitacion_id=licitacion_id,
            tender_amount_eur=amount,
            expected_competition=expected_competition,
            sample_quality="insuficiente",
        )

    history = _normalise_history(repo.load_history())
    cohort, dimensions = _select_cohort(
        history,
        organ=str(target.get("organo_contratacion") or "").strip().casefold(),
        cpv4=_cpv4(target.get("cpv")),
        amount=amount,
        expected_competition=expected_competition,
    )
    if not cohort:
        return PriceScenariosResult(
            licitacion_id=licitacion_id,
            tender_amount_eur=amount,
            expected_competition=expected_competition,
            cohort=dimensions,
            sample_quality="insuficiente",
        )

    distribution = _distribution([row.discount for row in cohort])
    quality: Literal["robusta", "indicativa", "insuficiente"]
    quality = (
        "robusta"
        if distribution.n >= 30
        else ("indicativa" if distribution.n >= _MIN_INDICATIVE_N else "insuficiente")
    )
    quantiles: list[tuple[Literal["defensivo", "central", "competitivo"], float, str]] = [
        ("defensivo", distribution.p25_discount, "percentil 25 de la baja observada"),
        ("central", distribution.p50_discount, "mediana de la baja observada"),
        ("competitivo", distribution.p75_discount, "percentil 75 de la baja observada"),
    ]
    # F2.4: el margen implícito sólo aparece si el pliego publicó tarifas Y
    # horas. Se leen una vez —no una por escenario— y una ficha que no exista
    # todavía deja los tres escenarios sin margen, que es lo correcto.
    tarifas = _tarifas_del_pliego(licitacion_id)
    scenarios = [
        PriceScenario(
            name=name,
            discount=discount,
            price_eur=(precio := round(amount * (1.0 - discount), 2)),
            basis=basis,
            margen_implicito=margen_de(precio, tarifas) if tarifas else None,
        )
        for name, discount, basis in quantiles
    ]
    return PriceScenariosResult(
        licitacion_id=licitacion_id,
        tender_amount_eur=amount,
        expected_competition=expected_competition,
        cohort=dimensions,
        sample_quality=quality,
        distribution=distribution,
        scenarios=scenarios,
    )


def coste_de_tarifas(rate_cards: list[RateCardFact]) -> tuple[float, int] | None:
    """``(coste, perfiles)`` a partir de las tarifas del pliego, o ``None``.

    Sólo cuentan los perfiles que traen **tarifa y horas**. Si ninguno las
    trae completas, devuelve ``None`` y no hay margen que enseñar: sumar los
    que sí y ignorar los que no daría un coste bajo y por tanto un margen
    alto, que es exactamente el error que nadie querría cometer fijando un
    precio.
    """
    completos = [
        (float(rc.max_rate_eur_hour), float(rc.estimated_hours))
        for rc in rate_cards
        if rc.max_rate_eur_hour is not None and rc.estimated_hours is not None
    ]
    if not completos:
        return None
    return round(sum(tarifa * horas for tarifa, horas in completos), 2), len(completos)


def margen_de(precio_eur: float, rate_cards: list[RateCardFact]) -> MargenImplicito | None:
    """El margen implícito de un precio, o ``None`` si no se puede calcular."""
    calculado = coste_de_tarifas(rate_cards)
    if calculado is None:
        return None
    coste, perfiles = calculado
    margen = round(precio_eur - coste, 2)
    return MargenImplicito(
        coste_estimado_eur=coste,
        margen_eur=margen,
        margen_pct=round(margen / precio_eur, 4) if precio_eur > 0 else None,
        perfiles=perfiles,
    )


def _tarifas_del_pliego(licitacion_id: str) -> list[RateCardFact]:
    """Las tarifas de la ficha, o lista vacía.

    Best-effort: el margen es información añadida y quedarse sin escenarios de
    precio porque la ficha no se pudo leer sería un mal negocio.
    """
    try:
        from services.rag.fact_sheet import get_fact_sheet

        record = get_fact_sheet(licitacion_id)
    except Exception:
        # Sin traza, «este pliego no publica tarifas» y «la ficha no se pudo
        # leer» serían el mismo hueco en la pantalla, y sólo uno de los dos es
        # un fallo que alguien tiene que arreglar.
        log.warning("pricing_tarifas_ficha_error", licitacion_id=licitacion_id, exc_info=True)
        return []
    return list(record.facts.rate_cards) if record and record.facts else []
