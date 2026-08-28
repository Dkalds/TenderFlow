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
        # El recorte de periodo va en el ``ON`` del LEFT JOIN, nunca en el
        # ``WHERE``. Es la diferencia entre "no abrió ningún pursuit" y "no
        # existe": en las organizaciones sin match, las columnas de ``p`` valen
        # NULL, así que ``p.identified_at >= %s`` en el WHERE evalúa a UNKNOWN,
        # descarta la fila y degenera el LEFT JOIN en INNER JOIN. El informe con
        # periodo enseñaba entonces sólo a quien usó el producto, que es
        # exactamente al revés de para qué se mira: la señal accionable es el
        # cliente que dejó de abrir pursuits este trimestre, y esa organización
        # tiene que salir con ceros, no desaparecer.
        join_conditions: list[str] = ["p.organization_id = o.id"]
        params: list[object] = []
        if period_from is not None:
            join_conditions.append("p.identified_at >= %s")
            params.append(period_from)
        if period_to is not None:
            join_conditions.append("p.identified_at < %s")
            params.append(period_to)
        on_clause = " AND ".join(join_conditions)
        with connect_read() as conn:
            cur = conn.execute(
                # `on_clause` lo compone este mismo método a partir de
                # literales; los valores del periodo viajan con %s.
                "SELECT o.id AS organization_id, o.name AS organization_name, "
                "p.id, p.outcome, p.submitted_at, p.awarded_amount_eur, "
                "p.identified_at, p.decision_at "
                "FROM organizations o "
                f"LEFT JOIN pursuits p ON {on_clause} "
                "ORDER BY o.id, p.id",
                tuple(params),
            )
            return rows_to_dicts(cur)
