"""Lecturas reproducibles para las métricas de producto de ``make status``."""

from __future__ import annotations

from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts


class ProductMetricsRepository:
    """Expone filas mínimas; el cálculo y sus denominadores viven en servicio."""

    def pursuit_rows(
        self,
        *,
        period_from: str | None = None,
        period_to: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[object] = []
        if period_from is not None:
            clauses.append("p.identified_at >= %s")
            params.append(period_from)
        if period_to is not None:
            clauses.append("p.identified_at < %s")
            params.append(period_to)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT o.id AS organization_id, o.name AS organization_name, "
                "p.id, p.outcome, p.submitted_at, p.awarded_amount_eur, "
                "p.identified_at, p.decision_at "
                "FROM organizations o "
                "LEFT JOIN pursuits p ON p.organization_id = o.id "
                f"{where} ORDER BY o.id, p.id",
                tuple(params),
            )
            return rows_to_dicts(cur)
