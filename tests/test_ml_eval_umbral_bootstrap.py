"""El umbral del golden: su elección y su dispersión por bootstrap.

``elegir_umbral`` es el núcleo que comparten el tuning que llega a producción
(``tune_threshold_on_golden``) y el informe de estabilidad del golden
(``scripts/revisar_golden_candidates.py --estado``). Si los dos eligieran
distinto, el informe mediría la estabilidad de un umbral que nadie sirve.
"""

from __future__ import annotations

import random

import pytest
from sklearn.metrics import fbeta_score

from services.ml_eval import UMBRAL_CLAMP, UMBRAL_PASO, elegir_umbral, umbral_bootstrap


def _referencia_sklearn(y: list[int], p: list[float], beta: float) -> tuple[float, float]:
    """El barrido tal como lo hacía ``tune_threshold_on_golden`` antes de
    extraerlo: un ``fbeta_score`` por punto de la rejilla."""
    lo, hi = UMBRAL_CLAMP
    mejor_t, mejor_f = lo, -1.0
    pasos = round((hi - lo) / UMBRAL_PASO)
    for k in range(pasos + 1):
        t = lo + k * UMBRAL_PASO
        f = float(fbeta_score(y, [int(v >= t) for v in p], beta=beta, zero_division=0))
        if f > mejor_f:
            mejor_t, mejor_f = t, f
    return mejor_t, mejor_f


@pytest.mark.parametrize("semilla", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("beta", [1.0, 3.0**0.5])
def test_elige_lo_mismo_que_el_barrido_de_sklearn(semilla: int, beta: float) -> None:
    rng = random.Random(semilla)
    y = [rng.randint(0, 1) for _ in range(60)]
    # Probabilidades redondeadas a 3 decimales: lejos de los puntos de la
    # rejilla, para que la comparación no dependa del redondeo de np.arange.
    p = [round(min(1.0, max(0.0, 0.35 * v + rng.random() * 0.65)), 3) + 0.0005 for v in y]

    t, f = elegir_umbral(y, p, beta=beta)
    t_ref, f_ref = _referencia_sklearn(y, p, beta)
    assert t == pytest.approx(t_ref)
    assert f == pytest.approx(f_ref)


def test_sin_aciertos_el_fbeta_es_cero() -> None:
    """``zero_division=0``: ningún positivo predicho no es un error."""
    t, f = elegir_umbral([1, 0], [0.0, 0.0], beta=1.0)
    assert f == 0.0
    assert t == UMBRAL_CLAMP[0]


class TestUmbralBootstrap:
    def test_una_sola_clase_no_tiene_umbral(self) -> None:
        assert umbral_bootstrap([1, 1, 1], [0.2, 0.5, 0.9], beta=1.0) is None

    def test_longitudes_distintas_es_un_error(self) -> None:
        with pytest.raises(ValueError, match="no miden lo mismo"):
            umbral_bootstrap([1, 0], [0.5], beta=1.0)

    def test_es_reproducible_con_la_misma_semilla(self) -> None:
        rng = random.Random(7)
        y = [rng.randint(0, 1) for _ in range(40)]
        p = [rng.random() for _ in y]
        a = umbral_bootstrap(y, p, beta=1.5, n_bootstrap=100, semilla=11)
        b = umbral_bootstrap(y, p, beta=1.5, n_bootstrap=100, semilla=11)
        assert a == b

    def test_mas_ejemplos_estrechan_el_intervalo(self) -> None:
        """Es la propiedad por la que se amplía el golden: con el mismo
        modelo ruidoso, 400 ejemplos fijan el umbral mejor que 27."""

        def muestra(n: int, semilla: int) -> tuple[list[int], list[float]]:
            rng = random.Random(semilla)
            y = [rng.randint(0, 1) for _ in range(n)]
            p = [min(1.0, max(0.0, rng.gauss(0.65 if v else 0.40, 0.18))) for v in y]
            return y, p

        pequeno = umbral_bootstrap(*muestra(27, 3), beta=1.5, n_bootstrap=300)
        grande = umbral_bootstrap(*muestra(400, 3), beta=1.5, n_bootstrap=300)
        assert pequeno is not None and grande is not None
        assert grande.ancho_p5_p95 < pequeno.ancho_p5_p95

    def test_el_dict_lleva_el_ancho(self) -> None:
        r = umbral_bootstrap([0, 1, 0, 1], [0.1, 0.9, 0.2, 0.8], beta=1.0, n_bootstrap=50)
        assert r is not None
        d = r.as_dict()
        assert d["ancho_p5_p95"] == pytest.approx(float(d["p95"]) - float(d["p5"]), abs=1e-3)
        assert int(d["remuestreos_validos"]) <= 50
