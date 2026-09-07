"""F4.2 (cuadro de dirección), F2.8 (comparar fichas) y F6.3 (export a CRM).

Los tres se apoyan en la misma idea, que es la que estos tests fijan: **no
publicar lo que no se sostiene**. El cuadro deja la celda vacía por debajo del
mínimo en vez de enseñar un win rate del 100 % sobre dos cierres; el
comparador enseña la familia vacía en vez de omitirla; y el export no manda al
CRM nada que no sea del pipeline.
"""

from __future__ import annotations

from typing import Any

import pytest

from services.comparador_fichas import MAX_EXPEDIENTES, comparar
from services.direccion import MINIMO_POR_CORTE, ROLES_DIRECCION, corte_con_minimo
from services.exports_crm import CABECERAS_CSV, ETAPAS_CRM, a_csv_fila, payload_de_pursuit
from shared.tender_facts import EvidenceRef, TenderFactSheet, WeightedCriterion

# ── F4.2 ────────────────────────────────────────────────────────────────────


def _cierre(tecnologia: str, outcome: str) -> dict[str, Any]:
    return {"tender_tecnologia": tecnologia, "outcome": outcome}


class TestCorteConMinimo:
    def test_por_debajo_del_minimo_no_publica_valor(self) -> None:
        """Un win rate del 100 % sobre dos cierres se cree; el hueco se pregunta."""
        filas = [_cierre("SAP", "won")] * (MINIMO_POR_CORTE - 1)
        corte = corte_con_minimo(filas, clave="tender_tecnologia")
        assert corte[0].valor is None
        assert corte[0].n == MINIMO_POR_CORTE - 1

    def test_la_celda_escasa_no_se_omite(self) -> None:
        """Omitirla escondería que hay un segmento donde el equipo empieza."""
        filas = [_cierre("SAP", "won")] * 2
        assert [c.clave for c in corte_con_minimo(filas, clave="tender_tecnologia")] == ["SAP"]

    def test_con_el_minimo_si_publica(self) -> None:
        filas = [_cierre("SAP", "won")] * 3 + [_cierre("SAP", "lost")] * 2
        corte = corte_con_minimo(filas, clave="tender_tecnologia")
        assert corte[0].valor == 0.6
        assert corte[0].n == 5

    def test_solo_cuentan_los_cierres(self) -> None:
        """Una oportunidad abierta no ha ganado ni perdido todavía."""
        filas = [_cierre("SAP", "won")] * 5 + [_cierre("SAP", "pending")] * 10
        assert corte_con_minimo(filas, clave="tender_tecnologia")[0].n == 5

    def test_sin_clave_cae_en_sin_clasificar(self) -> None:
        filas = [{"tender_tecnologia": None, "outcome": "won"}] * 5
        assert corte_con_minimo(filas, clave="tender_tecnologia")[0].clave == "sin clasificar"

    def test_orden_determinista(self) -> None:
        filas = [_cierre("SAP", "won")] * 6 + [_cierre("ORACLE", "won")] * 6
        corte = corte_con_minimo(filas, clave="tender_tecnologia")
        assert [c.clave for c in corte] == ["ORACLE", "SAP"]

    def test_los_roles_de_direccion(self) -> None:
        """Solo owner y admin; el control vive en el servicio, no en el rail."""
        assert frozenset({"owner", "admin"}) == ROLES_DIRECCION
        assert "member" not in ROLES_DIRECCION
        assert "viewer" not in ROLES_DIRECCION


# ── F2.8 ────────────────────────────────────────────────────────────────────


def _ficha_con_criterios() -> TenderFactSheet:
    return TenderFactSheet(
        award_criteria=[
            WeightedCriterion(
                description="Precio",
                confidence=0.9,
                evidence=[EvidenceRef(documento_id=1, page_number=1, quote="precio")],
                name="Precio",
                weight_pct=45,
            )
        ]
    )


class TestComparador:
    def test_una_familia_vacia_se_muestra_vacia(self) -> None:
        """Que uno de los dos no diga nada de solvencia es lo que hay que ver."""
        comparacion = comparar({"A": _ficha_con_criterios(), "B": TenderFactSheet()})
        criterios = next(f for f in comparacion.filas if f.familia == "award_criteria")
        assert [c.n for c in criterios.celdas] == [1, 0]
        assert criterios.vacia_en_todos is False

    def test_una_familia_vacia_en_todos_se_marca_pero_no_se_omite(self) -> None:
        comparacion = comparar({"A": TenderFactSheet(), "B": TenderFactSheet()})
        penalidades = next(f for f in comparacion.filas if f.familia == "penalties")
        assert penalidades.vacia_en_todos is True

    def test_declara_los_expedientes_sin_ficha(self) -> None:
        """Una columna en blanco no puede confundirse con un pliego sin exigencias."""
        comparacion = comparar({"A": _ficha_con_criterios(), "B": None})
        assert comparacion.sin_ficha == ["B"]

    def test_respeta_el_orden_de_quien_pregunta(self) -> None:
        comparacion = comparar({"Z": TenderFactSheet(), "A": TenderFactSheet()})
        assert comparacion.licitacion_ids == ["Z", "A"]

    def test_recorta_al_maximo(self) -> None:
        fichas = {str(i): TenderFactSheet() for i in range(10)}
        assert len(comparar(fichas).licitacion_ids) == MAX_EXPEDIENTES

    def test_el_ejemplo_lleva_el_nombre_del_criterio(self) -> None:
        comparacion = comparar({"A": _ficha_con_criterios()})
        criterios = next(f for f in comparacion.filas if f.familia == "award_criteria")
        assert criterios.celdas[0].ejemplos[0].startswith("Precio")

    def test_no_mas_de_tres_ejemplos_por_celda(self) -> None:
        ficha = TenderFactSheet(
            award_criteria=[
                WeightedCriterion(
                    description=f"C{i}",
                    confidence=0.9,
                    evidence=[EvidenceRef(documento_id=1, page_number=1, quote="q")],
                    name=f"C{i}",
                )
                for i in range(10)
            ]
        )
        comparacion = comparar({"A": ficha})
        criterios = next(f for f in comparacion.filas if f.familia == "award_criteria")
        assert len(criterios.celdas[0].ejemplos) == 3
        assert criterios.celdas[0].n == 10

    def test_compara_las_cuatro_familias_nuevas(self) -> None:
        familias = {f.familia for f in comparar({"A": TenderFactSheet()}).filas}
        assert {"price_formula", "required_documents", "rate_cards", "budget_breakdown"} <= familias


# ── F6.3 ────────────────────────────────────────────────────────────────────


class TestPayloadCRM:
    def test_la_cuenta_es_el_organo(self) -> None:
        """En un CRM, una cuenta se repite entre años; una licitación no."""
        payload = payload_de_pursuit(
            licitacion_id="EXP-1",
            titulo="Servicios SAP",
            organo="Ayuntamiento de Alcalá",
            importe=100_000.0,
            status="submitted",
            fecha_limite="2026-10-01",
            responsable="Ana",
            url="https://ejemplo.test/exp1",
        )
        assert payload.account_name == "Ayuntamiento de Alcalá"
        assert payload.opportunity_name == "Servicios SAP"

    def test_la_clave_es_el_expediente_no_la_oportunidad(self) -> None:
        """Con el id del pursuit, dos organizaciones crearían dos registros."""
        payload = payload_de_pursuit(
            licitacion_id="EXP-1",
            titulo=None,
            organo=None,
            importe=None,
            status="identified",
            fecha_limite=None,
            responsable=None,
            url=None,
        )
        assert payload.external_id == "EXP-1"

    @pytest.mark.parametrize(("estado", "etapa"), list(ETAPAS_CRM.items()))
    def test_todas_las_etapas_se_traducen(self, estado: str, etapa: str) -> None:
        payload = payload_de_pursuit(
            licitacion_id="EXP-1",
            titulo="x",
            organo=None,
            importe=None,
            status=estado,
            fecha_limite=None,
            responsable=None,
            url=None,
        )
        assert payload.stage == etapa

    def test_una_etapa_nueva_no_rompe_la_exportacion(self) -> None:
        """Un CRM con lista cerrada rechazaría el registro entero."""
        payload = payload_de_pursuit(
            licitacion_id="EXP-1",
            titulo="x",
            organo=None,
            importe=None,
            status="etapa_del_futuro",
            fecha_limite=None,
            responsable=None,
            url=None,
        )
        assert payload.stage == "Prospecting"

    def test_la_fecha_de_cierre_es_la_limite_no_la_estimada(self) -> None:
        """La prevista de adjudicación es una estimación nuestra; exportarla la
        convertiría en un compromiso que nadie asumió."""
        payload = payload_de_pursuit(
            licitacion_id="EXP-1",
            titulo="x",
            organo=None,
            importe=None,
            status="submitted",
            fecha_limite="2026-10-01T13:00:00",
            responsable=None,
            url=None,
        )
        assert payload.close_date == "2026-10-01"

    def test_sin_titulo_usa_el_expediente(self) -> None:
        payload = payload_de_pursuit(
            licitacion_id="EXP-1",
            titulo=None,
            organo=None,
            importe=None,
            status="identified",
            fecha_limite=None,
            responsable=None,
            url=None,
        )
        assert payload.opportunity_name == "EXP-1"

    def test_el_importe_ausente_no_es_cero(self) -> None:
        payload = payload_de_pursuit(
            licitacion_id="EXP-1",
            titulo="x",
            organo=None,
            importe=None,
            status="identified",
            fecha_limite=None,
            responsable=None,
            url=None,
        )
        assert payload.amount is None

    def test_no_exporta_score_ni_predicciones(self) -> None:
        """Un CRM es un sistema de terceros: cuanto menos salga, mejor."""
        campos = set(
            payload_de_pursuit(
                licitacion_id="EXP-1",
                titulo="x",
                organo=None,
                importe=None,
                status="identified",
                fecha_limite=None,
                responsable=None,
                url=None,
            ).model_dump()
        )
        assert not {"score", "prediccion_baja", "explicacion", "risk_flags"} & campos


class TestCsvCRM:
    def test_la_fila_sigue_el_orden_de_la_cabecera(self) -> None:
        payload = payload_de_pursuit(
            licitacion_id="EXP-1",
            titulo="Servicios SAP",
            organo="Ayto",
            importe=100_000.0,
            status="submitted",
            fecha_limite="2026-10-01",
            responsable="Ana",
            url="https://ejemplo.test",
        )
        fila = a_csv_fila(payload)
        assert len(fila) == len(CABECERAS_CSV)
        assert fila[CABECERAS_CSV.index("stage")] == "Negotiation"
        assert fila[CABECERAS_CSV.index("account_name")] == "Ayto"

    def test_csv_y_webhook_no_pueden_divergir(self) -> None:
        """La fila se deriva del payload: un solo mapeo que documentar."""
        from services.exports_crm import PayloadCRM

        assert set(CABECERAS_CSV) == set(PayloadCRM.model_fields)
