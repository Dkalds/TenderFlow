"""F2.2 — simulador de puntuación de la oferta.

Los puntos están calculados a mano en cada test. Es lo que pide el criterio de
aceptación y lo único que sirve: un test que recalcule la fórmula con el mismo
código que prueba no comprueba nada.

Lo segundo que se fija aquí es la **abstención**: sin fórmula, con una fórmula
que no se sabe calcular o sin puntos que repartir, el simulador dice por qué y
no aproxima. Aproximar acierta casi siempre y falla justo en el pliego raro,
que es donde alguien se juega el margen.
"""

from __future__ import annotations

import pytest

from services.simulador_precio import simular
from shared.tender_facts import EvidenceRef, PriceFormulaFact


def _formula(**kwargs: object) -> PriceFormulaFact:
    """Fórmula con una evidencia válida: ninguna familia viaja sin cita."""
    base: dict[str, object] = {
        "description": "Puntuación del criterio precio",
        "confidence": 0.9,
        "evidence": [
            EvidenceRef(documento_id=1, page_number=3, quote="se valorará la baja ofertada")
        ],
    }
    base.update(kwargs)
    return PriceFormulaFact(**base)  # type: ignore[arg-type]  # kwargs tipados por el modelo


class TestProporcionalInversa:
    def test_puntos_calculados_a_mano(self) -> None:
        """45 puntos, la mayor baja esperada es el 20 %.

        Con una baja del 10 %: 45 × (0,10 / 0,20) = 22,5.
        Con una del 20 %: 45 × 1 = 45.
        """
        sim = simular(
            "EXP-1",
            [_formula(formula_type="proporcional_inversa", max_points=45)],
            bajas=[0.10, 0.20],
            baja_mayor_esperada=0.20,
        )
        assert [e.puntos for e in sim.escenarios] == [22.5, 45.0]

    def test_no_pasa_del_maximo(self) -> None:
        """Bajar más que el rival no da más de lo que reparte el criterio."""
        sim = simular(
            "EXP-1",
            [_formula(formula_type="proporcional_inversa", max_points=45)],
            bajas=[0.40],
            baja_mayor_esperada=0.20,
        )
        assert sim.escenarios[0].puntos == 45.0

    def test_si_nadie_baja_todos_empatan_arriba(self) -> None:
        sim = simular(
            "EXP-1",
            [_formula(formula_type="proporcional_inversa", max_points=45)],
            bajas=[0.0],
            baja_mayor_esperada=0.0,
        )
        assert sim.escenarios[0].puntos == 45.0

    def test_sin_rival_esperado_usa_la_baja_mas_alta_simulada(self) -> None:
        """Supuesto conservador: alguien bajará tanto como el peor escenario."""
        sim = simular(
            "EXP-1",
            [_formula(formula_type="proporcional_inversa", max_points=45)],
            bajas=[0.10, 0.20],
        )
        assert [e.puntos for e in sim.escenarios] == [22.5, 45.0]

    def test_los_escenarios_salen_ordenados(self) -> None:
        sim = simular(
            "EXP-1",
            [_formula(formula_type="proporcional_inversa", max_points=45)],
            bajas=[0.20, 0.05, 0.10],
            baja_mayor_esperada=0.20,
        )
        assert [e.baja for e in sim.escenarios] == [0.05, 0.10, 0.20]


class TestPorTramos:
    def test_escalones(self) -> None:
        """Tramos: ≥5 % → 10 pts, ≥10 % → 20, ≥15 % → 30. Máximo 30."""
        formula = _formula(
            formula_type="lineal_por_tramos",
            max_points=30,
            params={"0.05": 10, "0.10": 20, "0.15": 30},
        )
        sim = simular("EXP-1", [formula], bajas=[0.03, 0.05, 0.12, 0.30])
        assert [e.puntos for e in sim.escenarios] == [0.0, 10.0, 20.0, 30.0]

    def test_por_debajo_del_primer_tramo_no_puntua(self) -> None:
        formula = _formula(formula_type="lineal_por_tramos", max_points=30, params={"0.10": 30})
        sim = simular("EXP-1", [formula], bajas=[0.05])
        assert sim.escenarios[0].puntos == 0.0

    def test_un_tramo_por_encima_del_maximo_se_recorta(self) -> None:
        """El extractor puede leer mal un tramo; el máximo manda."""
        formula = _formula(formula_type="lineal_por_tramos", max_points=30, params={"0.10": 999})
        sim = simular("EXP-1", [formula], bajas=[0.15])
        assert sim.escenarios[0].puntos == 30.0


class TestTemeridad:
    def test_marca_las_bajas_temerarias(self) -> None:
        formula = _formula(
            formula_type="con_umbral_temeridad", max_points=40, umbral_temeridad=0.25
        )
        sim = simular("EXP-1", [formula], bajas=[0.20, 0.30], baja_mayor_esperada=0.30)
        assert [e.temeraria for e in sim.escenarios] == [False, True]

    def test_no_las_excluye_por_su_cuenta(self) -> None:
        """Una temeraria justificada se acepta; decidirlo no le toca al simulador."""
        formula = _formula(
            formula_type="con_umbral_temeridad", max_points=40, umbral_temeridad=0.25
        )
        sim = simular("EXP-1", [formula], bajas=[0.30], baja_mayor_esperada=0.30)
        assert sim.escenarios[0].puntos == 40.0

    def test_sin_umbral_ninguna_es_temeraria(self) -> None:
        sim = simular(
            "EXP-1",
            [_formula(formula_type="proporcional_inversa", max_points=40)],
            bajas=[0.50],
        )
        assert sim.escenarios[0].temeraria is False


class TestHuecoContraElRival:
    def test_ventaja_positiva(self) -> None:
        """Bajo el 20 % contra un rival que baja el 10 %: 45 - 22,5 = +22,5."""
        sim = simular(
            "EXP-1",
            [_formula(formula_type="proporcional_inversa", max_points=45)],
            bajas=[0.20],
            baja_referencia=0.10,
            baja_mayor_esperada=0.20,
        )
        assert sim.hueco_vs_referencia == 22.5

    def test_desventaja_negativa(self) -> None:
        """El signo es lo informativo: hay que compensar en juicio de valor."""
        sim = simular(
            "EXP-1",
            [_formula(formula_type="proporcional_inversa", max_points=45)],
            bajas=[0.10],
            baja_referencia=0.20,
            baja_mayor_esperada=0.20,
        )
        assert sim.hueco_vs_referencia == -22.5

    def test_sin_referencia_no_hay_hueco(self) -> None:
        sim = simular(
            "EXP-1",
            [_formula(formula_type="proporcional_inversa", max_points=45)],
            bajas=[0.10],
        )
        assert sim.hueco_vs_referencia is None


class TestAbstencion:
    def test_sin_formula_extraida(self) -> None:
        sim = simular("EXP-1", [], bajas=[0.10])
        assert sim.sin_calculo == "sin_formula"
        assert sim.escenarios == []
        assert sim.puntos_precio is None

    def test_formula_que_no_se_sabe_calcular(self) -> None:
        """`otra` es la salida honesta del extractor; no se aproxima."""
        sim = simular("EXP-1", [_formula(formula_type="otra", max_points=45)], bajas=[0.10])
        assert sim.sin_calculo == "formula_no_calculable"
        assert sim.escenarios == []

    def test_sin_puntos_de_precio_ni_peso(self) -> None:
        sim = simular("EXP-1", [_formula(formula_type="proporcional_inversa")], bajas=[0.10])
        assert sim.sin_calculo == "sin_puntos_de_precio"

    def test_el_peso_del_precio_sirve_de_respaldo_y_se_declara(self) -> None:
        """Un 45 leído del pliego y un 45 inferido del peso no valen lo mismo."""
        sim = simular(
            "EXP-1",
            [_formula(formula_type="proporcional_inversa")],
            bajas=[0.10],
            baja_mayor_esperada=0.10,
            peso_precio_pct=45,
        )
        assert sim.sin_calculo is None
        assert sim.puntos_precio == 45.0
        assert sim.puntos_precio_origen == "peso_precio"

    def test_el_pliego_manda_sobre_el_peso(self) -> None:
        sim = simular(
            "EXP-1",
            [_formula(formula_type="proporcional_inversa", max_points=60)],
            bajas=[0.10],
            peso_precio_pct=45,
        )
        assert sim.puntos_precio == 60.0
        assert sim.puntos_precio_origen == "pliego"

    @pytest.mark.parametrize("baja", [-0.1, 1.5])
    def test_bajas_fuera_de_rango_se_descartan(self, baja: float) -> None:
        sim = simular(
            "EXP-1",
            [_formula(formula_type="proporcional_inversa", max_points=45)],
            bajas=[baja, 0.10],
            baja_mayor_esperada=0.10,
        )
        assert [e.baja for e in sim.escenarios] == [0.10]


class TestContrato:
    def test_la_formula_no_viaja_sin_cita(self) -> None:
        """Ninguna familia de la ficha se publica sin evidencia (ADR-014)."""
        formula = _formula(formula_type="proporcional_inversa", max_points=45)
        assert formula.evidence
        assert formula.evidence[0].page_number == 3

    def test_el_tipo_se_publica_para_la_telemetria(self) -> None:
        """`simulador_usado.formula_tipo` mide qué fórmulas cubre el extractor."""
        sim = simular(
            "EXP-1",
            [_formula(formula_type="lineal_por_tramos", max_points=30, params={"0.1": 30})],
            bajas=[0.15],
        )
        assert sim.formula_tipo == "lineal_por_tramos"
