"""Lecturas de adjudicaciones para escenarios descriptivos de precio."""

from __future__ import annotations

from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from db.sql_fragments import (
    BASE_COMPARABLE_SQL,
    CON_PRESUPUESTO_BASE_SQL,
    SIN_IVA_CONOCIDO_SQL,
    TECHNOLOGY_OBSERVED_SQL,
    exclude_duplicados_sql,
)


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

    def get_lote_target(self, licitacion_id: str, lote_id: int) -> dict[str, Any] | None:
        """El lote ``lote_id`` **si pertenece** a ``licitacion_id``, o ``None``.

        La comprobación de pertenencia va en el mismo WHERE que la búsqueda,
        igual que en ``PursuitRepository.lote_by_id``: el cliente manda el id
        que tiene en pantalla y sin ese filtro se serviría el escenario de
        precio del lote de otro expediente.

        ``importe`` es el del lote y **no** se rellena con el del expediente:
        un lote sin importe propio no tiene denominador, y repartir el
        presupuesto total entre sus lotes sería inventarlo (ADR-014). El CPV
        sí se devuelve por partida doble —el del lote y el del expediente— para
        que la capa de dominio pueda declarar cuál usó: un lote sin CPV propio
        sigue siendo el mismo objeto de contrato que su expediente, y quedarse
        sin la dimensión más informativa de la cohorte por eso empobrece el
        resultado sin ganar honestidad.
        """
        with connect_read() as connection:
            rows = rows_to_dicts(
                connection.execute(
                    "SELECT l.id_externo, lo.id AS lote_id, lo.numero AS lote_numero, "
                    "       lo.titulo AS lote_titulo, l.organo_contratacion, "
                    "       lo.cpv AS cpv_lote, l.cpv AS cpv_expediente, lo.importe "
                    "FROM lotes lo "
                    "JOIN licitaciones l ON l.id_externo = lo.licitacion_id "
                    "WHERE lo.id = %s AND lo.licitacion_id = %s",
                    (lote_id, licitacion_id),
                )
            )
        return rows[0] if rows else None

    def load_history(self, *, limit: int = 10_000) -> list[dict[str, Any]]:
        """Devuelve adjudicaciones comparables con presupuesto y precio positivos.

        ``importe_licitacion`` es el presupuesto del LOTE cuando la
        adjudicación tiene uno resuelto (v65_lotes), o el del expediente
        completo si no (mismo criterio que
        ``db.sql_fragments.EFFECTIVE_BUDGET_SQL`` -- duplicado aquí
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

        **Una fila por precio, no por adjudicatario.** Se agrega por expediente
        y lote: tres adjudicaciones sin lote de un mismo expediente se suman
        contra su presupuesto, en vez de dar tres bajas del 67 % por tercios.
        Fuera los duplicados confirmados entre fuentes (pesaban doble en la
        cohorte) y TED, que no publica presupuesto base. Un lote cuyos
        adjudicatarios declaran cada uno el importe total (acuerdo marco
        multiadjudicatario) suma más que su base y sale de la cohorte: antes
        entraba como N bajas de 0.
        """
        # S608 no aplica: solo se interpolan constantes de
        # ``db/sql_fragments.py``; el valor va con %s.
        base = BASE_COMPARABLE_SQL
        sql = (
            "SELECT a.licitacion_id, SUM(a.importe_adjudicado) AS importe_adjudicado, "
            "       MAX(a.n_ofertas_recibidas) AS n_ofertas_recibidas, "
            "       MAX(a.fecha_adjudicacion) AS fecha_adjudicacion, "
            f"      l.organo_contratacion, l.cpv, {base} AS importe_licitacion "
            "FROM adjudicaciones a "
            "JOIN licitaciones l ON l.id_externo = a.licitacion_id "
            "LEFT JOIN lotes lo ON lo.id = a.lote_id "
            "WHERE a.importe_adjudicado > 0 "
            f"  AND {base} > 0 "
            f"  AND {SIN_IVA_CONOCIDO_SQL} "
            f"  AND {TECHNOLOGY_OBSERVED_SQL} "
            f"  AND {CON_PRESUPUESTO_BASE_SQL} "
            f"  AND {exclude_duplicados_sql('a.licitacion_id')} "
            "GROUP BY a.licitacion_id, a.lote_id, l.organo_contratacion, l.cpv, "
            "         lo.importe, l.importe_base_sin_iva, l.importe "
            f"HAVING SUM(a.importe_adjudicado) <= {base} "
            "ORDER BY MAX(a.fecha_adjudicacion) DESC, a.licitacion_id, a.lote_id "
            "LIMIT %s"
        )
        with connect_read() as connection:
            return rows_to_dicts(connection.execute(sql, (limit,)))
