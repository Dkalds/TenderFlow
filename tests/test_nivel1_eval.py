"""Evaluación del modelo de nivel 1, «¿es TI?» (plan de tres niveles, F3, §4).

Lo que se fija aquí, sin BD ni modelos:

- el PR-AUC es el de sklearn (mismos empates), y un puntuador constante da la
  prevalencia, que es lo que hace comparables los baselines 0/1;
- las bandas cumplen su contrato: «TI» con precisión ≥ 0,95 y «no TI» con
  como mucho un 5 % de los positivos;
- el gate exige batir a los dos baselines con la cota inferior del IC de la
  diferencia pareada, y medir aparte «CPV 48/72 sin keyword»;
- en un empate gana el candidato más simple.
"""

from __future__ import annotations

import random

import pytest

from services.ml.nivel1_eval import (
    BASELINE_CPV,
    BASELINE_KEYWORDS,
    MIN_HOLDOUT,
    Bandas,
    CasoEval,
    ap_con_intervalo,
    average_precision,
    diferencia_pareada,
    elegir_bandas,
    evaluar_nivel1,
    metricas_bandas,
    scores_baseline,
)

N_BOOT = 200


class TestAveragePrecision:
    @pytest.mark.parametrize("semilla", [0, 1, 2, 3])
    def test_coincide_con_sklearn_tambien_con_empates(self, semilla: int) -> None:
        from sklearn.metrics import average_precision_score

        rng = random.Random(semilla)
        y = [rng.random() < 0.3 for _ in range(120)]
        y[0] = True
        # Redondeo a una cifra: muchos empates, que es donde dos
        # implementaciones de AP suelen divergir.
        scores = [round(rng.random(), 1) for _ in range(120)]
        esperado = average_precision_score([int(v) for v in y], scores)
        assert average_precision(y, scores) == pytest.approx(esperado)

    def test_un_puntuador_constante_da_la_prevalencia(self) -> None:
        y = [True, False, False, True, False]
        assert average_precision(y, [1.0] * 5) == pytest.approx(0.4)

    def test_sin_positivos_no_esta_definida(self) -> None:
        assert average_precision([False, False], [0.1, 0.9]) is None

    def test_longitudes_distintas_es_un_error(self) -> None:
        with pytest.raises(ValueError):
            average_precision([True], [0.1, 0.2])


class TestBootstrap:
    def test_el_intervalo_contiene_el_valor_y_es_reproducible(self) -> None:
        rng = random.Random(7)
        y = [rng.random() < 0.4 for _ in range(80)]
        y[0] = True
        scores = [0.7 * v + 0.3 * rng.random() for v in y]
        a = ap_con_intervalo(y, scores, n_bootstrap=N_BOOT, semilla=1)
        b = ap_con_intervalo(y, scores, n_bootstrap=N_BOOT, semilla=1)
        assert a is not None
        assert a == b
        assert a.bajo <= a.valor <= a.alto

    def test_la_diferencia_de_un_puntuador_consigo_mismo_es_cero(self) -> None:
        y = [True, False, True, False, False, True]
        s = [0.9, 0.2, 0.6, 0.4, 0.1, 0.8]
        dif = diferencia_pareada(y, s, s, n_bootstrap=N_BOOT)
        assert dif is not None
        assert (dif.valor, dif.bajo, dif.alto) == (0.0, 0.0, 0.0)


class TestBandas:
    def test_umbrales_de_precision_y_de_recall(self) -> None:
        # 20 positivos con score alto, 20 negativos con score bajo, y una zona
        # mezclada en medio.
        y = [True] * 20 + [False] * 20 + [True, False] * 5
        scores = [0.9] * 20 + [0.1] * 20 + [0.5] * 10
        bandas = elegir_bandas(y, scores)
        # Con 0,5 la precisión cae a 25/30: la banda TI empieza en 0,9.
        assert bandas.umbral_ti == 0.9
        # Bajo 0,5 quedaría fuera el 20 % de los positivos (5/25): el umbral
        # de «no TI» es 0,5, y solo lo de 0,1 es «no TI».
        assert bandas.umbral_no_ti == 0.5
        assert bandas.banda(0.95) == "ti"
        assert bandas.banda(0.5) == "dudoso"
        assert bandas.banda(0.1) == "no_ti"

    def test_si_los_umbrales_se_cruzan_no_hay_banda_dudosa(self) -> None:
        y = [True] * 30 + [False] * 30
        scores = [0.8] * 30 + [0.2] * 30
        bandas = elegir_bandas(y, scores)
        assert bandas.umbral_no_ti <= bandas.umbral_ti  # type: ignore[operator]  # no es None aquí
        assert {bandas.banda(p) for p in scores} == {"ti", "no_ti"}

    def test_sin_precision_suficiente_no_hay_banda_ti(self) -> None:
        y = [True, False] * 20
        scores = [0.5] * 40
        bandas = elegir_bandas(y, scores)
        assert bandas.umbral_ti is None
        assert bandas.banda(0.99) == "dudoso"

    def test_sin_positivos_es_un_error(self) -> None:
        with pytest.raises(ValueError, match="sin positivos"):
            elegir_bandas([False, False], [0.1, 0.2])

    def test_metricas_de_las_bandas(self) -> None:
        bandas = Bandas(umbral_no_ti=0.3, umbral_ti=0.8)
        y = [True, True, False, True, False]
        scores = [0.9, 0.85, 0.82, 0.1, 0.5]
        m = metricas_bandas(y, scores, bandas)
        assert m.frac_ti == pytest.approx(3 / 5)
        assert m.precision_ti == pytest.approx(2 / 3)
        assert m.recall_perdido_no_ti == pytest.approx(1 / 3)
        assert m.frac_dudoso == pytest.approx(1 / 5)


# ── Gate ────────────────────────────────────────────────────────────────────


def _holdout(n_por_tipo: int = 15) -> list[CasoEval]:
    """Cuatro tipos de caso, cada uno con ``n_por_tipo`` ejemplos:

    - TI con keyword y CPV 48/72;
    - TI sin keyword y con CPV 48/72 (lo que las reglas no ven);
    - no TI con keyword (falso positivo de las reglas: «SAP» de atención
      primaria) y sin CPV TI;
    - no TI sin keyword y con CPV 72 (revistas, actos).
    """
    return (
        [CasoEval(True, True, True)] * n_por_tipo
        + [CasoEval(True, False, True)] * n_por_tipo
        + [CasoEval(False, True, False)] * n_por_tipo
        + [CasoEval(False, False, True)] * n_por_tipo
    )


def _perfecto(casos: list[CasoEval]) -> list[float]:
    return [0.97 if c.es_ti else 0.03 for c in casos]


_BANDAS = Bandas(umbral_no_ti=0.5, umbral_ti=0.9)


class TestGate:
    def test_los_baselines_valen_lo_que_dicen(self) -> None:
        casos = _holdout()
        assert scores_baseline(casos, BASELINE_KEYWORDS)[:2] == [1.0, 1.0]
        assert scores_baseline(casos, BASELINE_CPV)[-1] == 1.0
        with pytest.raises(ValueError):
            scores_baseline(casos, "otro")

    def test_un_candidato_que_separa_es_apto(self) -> None:
        casos = _holdout()
        informe = evaluar_nivel1(casos, {"A": _perfecto(casos)}, {"A": _BANDAS}, n_bootstrap=N_BOOT)
        assert informe.apto, informe.motivos
        assert informe.ganador == "A"
        assert informe.ap["A"].valor == pytest.approx(1.0)
        assert informe.sobre_baselines["A"][BASELINE_KEYWORDS].bajo > 0
        sub = informe.subpoblacion["A"]
        assert (sub.n, sub.positivos) == (30, 15)
        assert informe.bandas_holdout["A"].precision_ti == pytest.approx(1.0)
        assert informe.as_dict()["ganador"] == "A"

    def test_imitar_a_las_keywords_no_basta(self) -> None:
        casos = _holdout()
        imitador = [0.9 if c.tiene_keyword else 0.1 for c in casos]
        informe = evaluar_nivel1(casos, {"A": imitador}, {"A": _BANDAS}, n_bootstrap=N_BOOT)
        assert not informe.apto
        assert any("no bate a solo_keywords" in m for m in informe.motivos)

    def test_un_holdout_pequeno_no_decide(self) -> None:
        casos = _holdout(n_por_tipo=5)
        assert len(casos) < MIN_HOLDOUT
        informe = evaluar_nivel1(casos, {"A": _perfecto(casos)}, {"A": _BANDAS}, n_bootstrap=N_BOOT)
        assert not informe.apto
        assert any("holdout de 20" in m for m in informe.motivos)

    def test_sin_soporte_en_la_subpoblacion_no_se_promociona(self) -> None:
        # Sin «TI sin keyword»: justo donde el modelo tendría que aportar.
        casos = (
            [CasoEval(True, True, True)] * 40
            + [CasoEval(False, True, False)] * 20
            + [CasoEval(False, False, False)] * 20
        )
        informe = evaluar_nivel1(casos, {"A": _perfecto(casos)}, {"A": _BANDAS}, n_bootstrap=N_BOOT)
        assert any("cpv_48_72_sin_keyword sin soporte" in m for m in informe.motivos)

    def test_sin_banda_ti_no_se_promociona(self) -> None:
        casos = _holdout()
        informe = evaluar_nivel1(
            casos,
            {"A": _perfecto(casos)},
            {"A": Bandas(umbral_no_ti=0.2, umbral_ti=None)},
            n_bootstrap=N_BOOT,
        )
        assert any("ningún umbral llega a precisión" in m for m in informe.motivos)

    def test_en_un_empate_gana_el_mas_simple(self) -> None:
        casos = _holdout()
        s = _perfecto(casos)
        informe = evaluar_nivel1(
            casos, {"A": s, "A+B": list(s)}, {"A": _BANDAS, "A+B": _BANDAS}, n_bootstrap=N_BOOT
        )
        assert informe.ganador == "A"

    def test_si_el_complejo_gana_de_verdad_gana_el_complejo(self) -> None:
        casos = _holdout()
        # A solo acierta donde aciertan las keywords; A+B separa.
        a = [0.9 if c.tiene_keyword else 0.1 for c in casos]
        informe = evaluar_nivel1(
            casos,
            {"A": a, "A+B": _perfecto(casos)},
            {"A": _BANDAS, "A+B": _BANDAS},
            n_bootstrap=N_BOOT,
        )
        assert informe.ganador == "A+B"
        assert informe.apto, informe.motivos

    def test_los_no_entrenados_viajan_al_informe(self) -> None:
        casos = _holdout()
        informe = evaluar_nivel1(
            casos,
            {"A": _perfecto(casos)},
            {"A": _BANDAS},
            sin_evaluar={"B": "sentence-transformers no está instalado"},
            n_bootstrap=N_BOOT,
        )
        assert informe.as_dict()["sin_evaluar"] == {"B": "sentence-transformers no está instalado"}

    def test_scores_que_no_casan_con_el_holdout_son_un_error(self) -> None:
        with pytest.raises(ValueError):
            evaluar_nivel1(_holdout(), {"A": [0.5]}, {}, n_bootstrap=N_BOOT)
