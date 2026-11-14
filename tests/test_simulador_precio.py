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

from services.simulador_precio import _es_temeraria_art85, simular
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


class TestInversaPrecio:
    def test_puntos_calculados_a_mano(self) -> None:
        """40 puntos, la mejor baja esperada es el 20 %.

        Precio con baja del 10 %: 0,90; el más bajo: 0,80.
        40 × 0,80 / 0,90 = 35,555… → 35,56. Con la del 20 %: 40.
        """
        sim = simular(
            "EXP-1",
            [_formula(formula_type="inversa_precio", max_points=40)],
            bajas=[0.10, 0.20],
            baja_mayor_esperada=0.20,
        )
        assert [e.puntos for e in sim.escenarios] == [35.56, 40.0]

    def test_no_es_la_proporcional_a_la_baja(self) -> None:
        """La misma baja da 20 puntos con `proporcional_inversa`: no son intercambiables."""
        sim = simular(
            "EXP-1",
            [_formula(formula_type="proporcional_inversa", max_points=40)],
            bajas=[0.10],
            baja_mayor_esperada=0.20,
        )
        assert sim.escenarios[0].puntos == 20.0

    def test_mejorar_la_mejor_baja_da_el_maximo(self) -> None:
        sim = simular(
            "EXP-1",
            [_formula(formula_type="inversa_precio", max_points=40)],
            bajas=[0.30, 1.0],
            baja_mayor_esperada=0.20,
        )
        assert [e.puntos for e in sim.escenarios] == [40.0, 40.0]

    def test_sin_baja_frente_a_un_rival(self) -> None:
        """Baja 0 contra un rival al 25 %: 40 × 0,75 / 1 = 30."""
        sim = simular(
            "EXP-1",
            [_formula(formula_type="inversa_precio", max_points=40)],
            bajas=[0.0],
            baja_mayor_esperada=0.25,
        )
        assert sim.escenarios[0].puntos == 30.0

    def test_hueco_contra_el_rival(self) -> None:
        """Bajo el 10 % contra un rival al 20 %: 35,56 − 40 = −4,44."""
        sim = simular(
            "EXP-1",
            [_formula(formula_type="inversa_precio", max_points=40)],
            bajas=[0.10],
            baja_referencia=0.20,
            baja_mayor_esperada=0.20,
        )
        assert sim.hueco_vs_referencia == -4.44


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

    def test_umbral_cero_no_es_un_umbral(self) -> None:
        """Un 0 marcaría temeraria cualquier baja; es el extractor rellenando el campo."""
        formula = _formula(formula_type="proporcional_inversa", max_points=40, umbral_temeridad=0)
        sim = simular("EXP-1", [formula], bajas=[0.05, 0.25])
        assert [e.temeraria for e in sim.escenarios] == [False, False]


class TestArt85Rglcap:
    """Art. 85 RGLCAP (RD 1098/2001), leído en bajas sobre el presupuesto.

    Interpretación que fija este test: el artículo habla de precios, y aquí
    precio = 1 - baja. «Inferior en más de N unidades porcentuales» es una baja
    que supera a la otra (o a la media de bajas) en más de N puntos, estricto:
    justo N puntos no es temeraria. «La oferta de cuantía más elevada» es la de
    menor baja, y «las tres de menor cuantía», las tres de mayor baja.
    """

    def test_un_licitador_mas_de_25_puntos(self) -> None:
        assert _es_temeraria_art85(0.26, []) is True
        assert _es_temeraria_art85(0.25, []) is False

    def test_dos_licitadores_mas_de_20_sobre_la_otra(self) -> None:
        """30 % contra 10 %: 20 puntos justos, no; 31 % contra 10 %: sí."""
        assert _es_temeraria_art85(0.30, [0.10]) is False
        assert _es_temeraria_art85(0.31, [0.10]) is True

    def test_tres_licitadores_contra_la_media(self) -> None:
        """Bajas 8, 10 y 25: media 14,33; 25 − 14,33 = 10,67 > 10.

        El 8 queda 6,33 por debajo de la media: no se excluye.
        """
        assert _es_temeraria_art85(0.25, [0.08, 0.10]) is True
        assert _es_temeraria_art85(0.10, [0.08, 0.25]) is False

    def test_tres_licitadores_excluye_la_mas_cara_de_la_media(self) -> None:
        """Bajas 0, 15 y 25: media 13,33; el 0 queda 13,33 por debajo → fuera.

        Nueva media (15 + 25) / 2 = 20: 25 − 20 = 5, no temeraria. Con la media
        de las tres, 25 − 13,33 = 11,67, lo habría sido.
        """
        assert _es_temeraria_art85(0.25, [0.0, 0.15]) is False

    def test_tres_licitadores_mas_de_25_siempre(self) -> None:
        """Bajas 20, 22 y 27: media 23; 27 − 23 = 4, pero pasa de 25 puntos."""
        assert _es_temeraria_art85(0.27, [0.20, 0.22]) is True

    def test_cuatro_licitadores_contra_la_media(self) -> None:
        """Bajas 10, 12, 14 y 30: media 16,5; ninguna queda >10 por debajo.

        30 − 16,5 = 13,5 > 10 → temeraria; 14 − 16,5 < 0 → no.
        """
        assert _es_temeraria_art85(0.30, [0.10, 0.12, 0.14]) is True
        assert _es_temeraria_art85(0.14, [0.10, 0.12, 0.30]) is False

    def test_cuatro_licitadores_nueva_media_sin_las_caras(self) -> None:
        """Bajas 0, 20, 22 y 31: media 18,25; el 0 queda 18,25 por debajo → fuera.

        Nueva media (20 + 22 + 31) / 3 = 24,33: 31 − 24,33 = 6,67, no temeraria.
        Con la media de todas habría sido 31 − 18,25 = 12,75: sí.
        """
        assert _es_temeraria_art85(0.31, [0.0, 0.20, 0.22]) is False

    def test_cuatro_licitadores_menos_de_tres_restantes_usa_las_tres_mayores(self) -> None:
        """Bajas 0, 0, 30 y 35: media 16,25; los dos 0 quedan >10 por debajo.

        Restan dos (30 y 35), menos de tres: la media es la de las tres de
        mayor baja (0, 30, 35) = 21,67. 35 − 21,67 = 13,33 > 10 → temeraria.
        Con la media de las dos restantes (32,5) no lo sería.
        """
        assert _es_temeraria_art85(0.35, [0.0, 0.0, 0.30]) is True


class TestTemeridadArt85EnLaSimulacion:
    def _art85(self, **kwargs: object) -> PriceFormulaFact:
        return _formula(
            formula_type="inversa_precio",
            max_points=40,
            params={"regla_rglcap_85": 1},
            **kwargs,
        )

    def test_con_rival_mide_contra_su_baja(self) -> None:
        """Rival al 5 %: 20 % no (15 puntos), 30 % sí (25 > 20)."""
        sim = simular("EXP-1", [self._art85()], bajas=[0.20, 0.30], baja_referencia=0.05)
        assert [e.temeraria for e in sim.escenarios] == [False, True]
        assert sim.temeridad_regla == "art85_dos_ofertas"

    def test_ignora_el_umbral_fijo_que_traiga_la_ficha(self) -> None:
        """El 0,25 de la cláusula del art. 85 no es un umbral fijo.

        Rival al 20 %: 30 % no pasa de 20 puntos sobre él, aunque supere el 25 %.
        """
        sim = simular(
            "EXP-1",
            [self._art85(umbral_temeridad=0.25)],
            bajas=[0.30],
            baja_referencia=0.20,
        )
        assert sim.escenarios[0].temeraria is False

    def test_sin_rival_no_marca_nada(self) -> None:
        """Sin otra oferta no hay contra qué medir: ni el 25 % fijo."""
        sim = simular("EXP-1", [self._art85(umbral_temeridad=0.25)], bajas=[0.30])
        assert sim.escenarios[0].temeraria is False
        assert sim.temeridad_regla == "sin_umbral"

    def test_la_clave_no_se_lee_como_tramo(self) -> None:
        """Tramos ≥10 % → 30 pts; la clave del art. 85 no es un umbral de baja."""
        formula = _formula(
            formula_type="lineal_por_tramos",
            max_points=30,
            params={"0.10": 30, "regla_rglcap_85": 1},
        )
        sim = simular("EXP-1", [formula], bajas=[0.15], baja_referencia=0.10)
        assert sim.escenarios[0].puntos == 30.0

    def test_sin_la_clave_la_regla_es_el_umbral_fijo(self) -> None:
        formula = _formula(
            formula_type="con_umbral_temeridad", max_points=40, umbral_temeridad=0.25
        )
        sim = simular("EXP-1", [formula], bajas=[0.30], baja_referencia=0.05)
        assert sim.escenarios[0].temeraria is True
        assert sim.temeridad_regla == "umbral_fijo"


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

    def test_el_rival_que_baja_mas_es_la_mejor_oferta(self) -> None:
        """Como llama la ruta: sin `baja_mayor_esperada`, solo tu baja y la del rival.

        Bajo el 10 % y el rival el 20 %: la mejor oferta es la suya.
        Inversa al precio: 40 × 0,80 / 0,90 = 35,56; el rival, 40; hueco −4,44.
        Antes la mejor baja era la mía y salía 40 contra 40, hueco 0.
        """
        sim = simular(
            "EXP-1",
            [_formula(formula_type="inversa_precio", max_points=40)],
            bajas=[0.10],
            baja_referencia=0.20,
        )
        assert sim.escenarios[0].puntos == 35.56
        assert sim.hueco_vs_referencia == -4.44

    def test_el_rival_cuenta_tambien_en_la_proporcional_a_la_baja(self) -> None:
        """45 × 0,10 / 0,20 = 22,5 contra 45 del rival: hueco −22,5."""
        sim = simular(
            "EXP-1",
            [_formula(formula_type="proporcional_inversa", max_points=45)],
            bajas=[0.10],
            baja_referencia=0.20,
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
