"""Lecturas de adjudicaciones para escenarios descriptivos de precio."""

from __future__ import annotations

from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from db.sql_fragments import TECHNOLOGY_OBSERVED_SQL


class PricingRepository:
    """Repositorio read-only; no materializa modelos ni probabilidades."""

    def get_target(self, licitacion_id: str) -> dict[str, Any] | None:
        with connect_read() as connection:
            rows = rows_to_dicts(
                connection.execute(
                    "SELECT id_externo, titulo, organo_contratacion, cpv, importe "
                    "FROM licitaciones WHERE id_externo = %s",
                    (licitacion_id,),
                )
            )
        return rows[0] if rows else None

    def load_history(self, *, limit: int = 10_000) -> list[dict[str, Any]]:
        """Devuelve adjudicaciones comparables con presupuesto y precio positivos.

        ``importe_licitacion`` es el presupuesto del LOTE cuando la
        adjudicación tiene uno resuelto (v65_lotes), o el del expediente
        completo si no (mismo criterio que
        ``services.sql_fragments.EFFECTIVE_BUDGET_SQL`` -- duplicado aquí
        porque ``db/`` no debe depender de ``services/``, capa superior).
        Antes de v65_lotes esto comparaba siempre contra el expediente
        completo, así que un lote cuyo importe superaba el presupuesto TOTAL
        (aritméticamente imposible si el ratio se calculase bien) se excluía
        como outlier en vez de corregirse -- perdiendo esa fila de la
        distribución en lugar de arreglar el denominador.

        **Base del importe (C1.1, ADR-032).** Prefiere `importe_base_sin_iva`
        cuando la fila la trae y **excluye** las que se sabe que llevan IVA
        (`importe_tipo = 'con_iva'`). Sin eso, la distribución de bajas mezclaba
        denominadores con y sin IVA: una baja del 21 % podía ser exactamente el
        impuesto. El histórico `desconocido` sigue entrando —su base no se puede
        determinar sin volver a parsear el CODICE— y por eso el resultado
        declara `base` en vez de afirmar que es sin IVA.
        """
        # S608 no aplica: el único fragmento interpolado es una constante de
        # ``db/sql_fragments.py``; el valor va con %s.
        sql = (
            "SELECT a.licitacion_id, a.importe_adjudicado, a.n_ofertas_recibidas, "
            "       a.fecha_adjudicacion, l.organo_contratacion, l.cpv, "
            "       COALESCE(lo.importe, l.importe_base_sin_iva, l.importe) AS importe_licitacion "
            "FROM adjudicaciones a "
            "JOIN licitaciones l ON l.id_externo = a.licitacion_id "
            "LEFT JOIN lotes lo ON lo.id = a.lote_id "
            "WHERE a.importe_adjudicado IS NOT NULL "
            "  AND a.importe_adjudicado > 0 "
            "  AND COALESCE(lo.importe, l.importe_base_sin_iva, l.importe) IS NOT NULL "
            "  AND COALESCE(lo.importe, l.importe_base_sin_iva, l.importe) > 0 "
            "  AND a.importe_adjudicado <= COALESCE(lo.importe, l.importe_base_sin_iva, l.importe) "
            "  AND COALESCE(l.importe_tipo, 'desconocido') <> 'con_iva' "
            f"  AND {TECHNOLOGY_OBSERVED_SQL} "
            "ORDER BY a.fecha_adjudicacion DESC "
            "LIMIT %s"
        )
        with connect_read() as connection:
            return rows_to_dicts(connection.execute(sql, (limit,)))
