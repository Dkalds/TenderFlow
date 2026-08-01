"""Métricas de resultado que dirigen el producto, no solo su infraestructura."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from statistics import median
from typing import Any

from pydantic import BaseModel, Field

from db.repositories.product_metrics import ProductMetricsRepository


class OrganizationProductMetrics(BaseModel):
    organization_id: int | None = Field(default=None, ge=1)
    organization_name: str
    pursuits_identified: int = Field(ge=0)
    pursuits_submitted: int = Field(ge=0)
    pursuits_won: int = Field(ge=0)
    pursuits_lost: int = Field(ge=0)
    win_rate: float | None = Field(default=None, ge=0, le=1)
    awarded_amount_eur: float = Field(ge=0)
    median_decision_time_hours: float | None = Field(default=None, ge=0)


class ProductStatus(BaseModel):
    generated_at: str
    period_from: str | None = None
    period_to: str | None = None
    organizations: list[OrganizationProductMetrics]
    totals: OrganizationProductMetrics


def _hours(start: object, end: object) -> float | None:
    if not start or not end:
        return None
    try:
        start_dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except ValueError:
        return None
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=UTC)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=UTC)
    elapsed = (end_dt - start_dt).total_seconds() / 3600
    return elapsed if elapsed >= 0 else None


def _aggregate(
    organization_id: int | None,
    organization_name: str,
    rows: list[dict[str, Any]],
) -> OrganizationProductMetrics:
    pursuits = [row for row in rows if row.get("id") is not None]
    won = sum(row.get("outcome") == "won" for row in pursuits)
    lost = sum(row.get("outcome") == "lost" for row in pursuits)
    resolved = won + lost
    decision_hours = [
        elapsed
        for row in pursuits
        if (elapsed := _hours(row.get("identified_at"), row.get("decision_at"))) is not None
    ]
    return OrganizationProductMetrics(
        organization_id=organization_id,
        organization_name=organization_name,
        pursuits_identified=len(pursuits),
        pursuits_submitted=sum(row.get("submitted_at") is not None for row in pursuits),
        pursuits_won=won,
        pursuits_lost=lost,
        win_rate=won / resolved if resolved else None,
        awarded_amount_eur=sum(
            float(row.get("awarded_amount_eur") or 0)
            for row in pursuits
            if row.get("outcome") == "won"
        ),
        median_decision_time_hours=median(decision_hours) if decision_hours else None,
    )


def build_product_status(
    rows: list[dict[str, Any]],
    *,
    period_from: str | None = None,
    period_to: str | None = None,
) -> ProductStatus:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(int(row["organization_id"]), str(row["organization_name"]))].append(row)
    organizations = [
        _aggregate(org_id, name, org_rows) for (org_id, name), org_rows in sorted(grouped.items())
    ]
    all_pursuits = [row for row in rows if row.get("id") is not None]
    totals = _aggregate(None, "Todas las organizaciones", all_pursuits)
    return ProductStatus(
        generated_at=datetime.now(UTC).isoformat(),
        period_from=period_from,
        period_to=period_to,
        organizations=organizations,
        totals=totals,
    )


def get_product_status(
    *,
    period_from: str | None = None,
    period_to: str | None = None,
) -> ProductStatus:
    rows = ProductMetricsRepository().pursuit_rows(
        period_from=period_from,
        period_to=period_to,
    )
    return build_product_status(
        rows,
        period_from=period_from,
        period_to=period_to,
    )
