"""Lecturas de adjudicaciones para escenarios descriptivos de precio."""

from __future__ import annotations

from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts


class PricingRepository:
    """Repositorio read-only; no materializa modelos ni probabilidades."""

    def get_target(self, licitacion_id: str) -> dict[str, Any] | None:
        with connect_read() as connection:
            rows = rows_to_dicts(
                connection.execute(
                    "SELECT id_externo, titulo, organo_contratacion, cpv, importe "
                    "FROM licitaciones WHERE id_externo = ?",
                    (licitacion_id,),
                )
            )
        return rows[0] if rows else None

    def load_history(self, *, limit: int = 10_000) -> list[dict[str, Any]]:
        """Devuelve adjudicaciones comparables con presupuesto y precio positivos.

        Se excluyen ratios fuera de [0, 1]: normalmente representan lotes cuyo
        importe adjudicado no es comparable con el presupuesto total publicado.
        """
        sql = (
            "SELECT a.licitacion_id, a.importe_adjudicado, a.n_ofertas_recibidas, "
            "       a.fecha_adjudicacion, l.organo_contratacion, l.cpv, "
            "       l.importe AS importe_licitacion "
            "FROM adjudicaciones a "
            "JOIN licitaciones l ON l.id_externo = a.licitacion_id "
            "WHERE a.importe_adjudicado IS NOT NULL "
            "  AND a.importe_adjudicado > 0 "
            "  AND l.importe IS NOT NULL "
            "  AND l.importe > 0 "
            "  AND a.importe_adjudicado <= l.importe "
            "  AND COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed' "
            "ORDER BY a.fecha_adjudicacion DESC "
            "LIMIT ?"
        )
        with connect_read() as connection:
            return rows_to_dicts(connection.execute(sql, (limit,)))
