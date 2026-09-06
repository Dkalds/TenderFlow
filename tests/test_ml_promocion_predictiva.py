"""Criterio de promoción de los modelos predictivos (S6.4).

``baja_model`` v2 y ``retencion_model`` v1 llevaban desde septiembre
registrados y sin activar porque **las métricas no permitían decidir**
(backlog P2):

- baja v2 mejoraba el baseline un 3,3% (``mae_p50`` 0.12494 vs 0.12999, o sea
  0.005) con ``mae_p50_std_folds`` = 0.01287: dos veces y media esa mejora.
- retención v1 no registraba ninguna métrica de baseline: ``pr_auc`` 0.2453
  sobre prevalencia 0.1099, sin nada contra lo que compararlo.

El criterio escrito es uno: la mejora sobre el baseline tiene que superar la
dispersión de esa misma métrica entre folds. Esta suite lo fija con los números
reales del backlog, para que la próxima versión se juzgue con la misma vara.
"""

from __future__ import annotations

from services.ml.promotion import (
    MIN_IMPROVEMENT_OVER_FOLD_DISPERSION,
    evaluar_promocion_predictiva,
)


class TestBajaModel:
    """Métrica de error: mejor es menor."""

    def test_v2_no_se_promociona_porque_la_mejora_cabe_en_el_ruido(self) -> None:
        decision = evaluar_promocion_predictiva(
            metrica=0.12494,
            baseline=0.12999,
            dispersion=0.01287,
            nombre_metrica="mae_p50",
        )
        assert decision.promocionable is False
        assert "indistinguible de ruido" in decision.promotion_reason
        assert round(decision.mejora, 5) == 0.00505
        assert decision.margen_exigido == 0.01287

    def test_una_mejora_que_supera_la_dispersion_si_pasa(self) -> None:
        decision = evaluar_promocion_predictiva(
            metrica=0.10,
            baseline=0.13,
            dispersion=0.01,
            nombre_metrica="mae_p50",
        )
        assert decision.promocionable is True
        assert decision.promotion_reason.startswith("promocionable")

    def test_no_batir_al_baseline_es_el_primer_motivo(self) -> None:
        decision = evaluar_promocion_predictiva(
            metrica=0.14,
            baseline=0.13,
            dispersion=0.001,
            nombre_metrica="mae_p50",
        )
        assert decision.promocionable is False
        assert "no bate al baseline" in decision.promotion_reason

    def test_sin_dispersion_no_se_promociona(self) -> None:
        """Es el caso de retención v1: una mejora sin error asociado no se
        puede distinguir del ruido, así que el gate no da por buena la
        comparación en vez de suponer que la dispersión es cero."""
        decision = evaluar_promocion_predictiva(
            metrica=0.10,
            baseline=0.13,
            dispersion=None,
            nombre_metrica="mae_p50",
        )
        assert decision.promocionable is False
        assert "sin dispersion medida" in decision.promotion_reason
        assert decision.margen_exigido is None

    def test_los_criterios_del_rfc_siguen_bloqueando(self) -> None:
        """Cobertura fuera de rango: por mucho que gane al baseline."""
        decision = evaluar_promocion_predictiva(
            metrica=0.05,
            baseline=0.13,
            dispersion=0.001,
            nombre_metrica="mae_p50",
            motivos_extra=["cobertura del intervalo 80% 0.4200 fuera de (0.75, 0.85)"],
        )
        assert decision.promocionable is False
        assert "cobertura" in decision.promotion_reason

    def test_el_factor_por_defecto_no_promociona_dentro_del_ruido(self) -> None:
        assert MIN_IMPROVEMENT_OVER_FOLD_DISPERSION >= 1.0

    def test_el_factor_es_configurable_por_llamada(self) -> None:
        comun = {
            "metrica": 0.11,
            "baseline": 0.13,
            "dispersion": 0.015,
            "nombre_metrica": "mae_p50",
        }
        assert evaluar_promocion_predictiva(**comun).promocionable is True
        exigente = evaluar_promocion_predictiva(**comun, min_improvement_over_fold_dispersion=2.0)
        assert exigente.promocionable is False


class TestRetencionModel:
    """Métrica de ranking: mejor es mayor, y el baseline es la prevalencia."""

    def test_v1_con_su_prevalencia_como_baseline(self) -> None:
        """PR-AUC 0.2453 sobre prevalencia 0.1099: mejora 0.1354. Con una
        dispersión entre bloques mayor que eso, sigue sin ser decidible."""
        decision = evaluar_promocion_predictiva(
            metrica=0.2453,
            baseline=0.1099,
            dispersion=0.20,
            nombre_metrica="pr_auc",
            mejor_es_mayor=True,
        )
        assert decision.promocionable is False
        assert round(decision.mejora, 4) == 0.1354

    def test_ordenar_al_azar_no_es_promocionable(self) -> None:
        """El PR-AUC esperado del ranking trivial ES la prevalencia."""
        decision = evaluar_promocion_predictiva(
            metrica=0.1099,
            baseline=0.1099,
            dispersion=0.01,
            nombre_metrica="pr_auc",
            mejor_es_mayor=True,
        )
        assert decision.promocionable is False
        assert "no bate al baseline" in decision.promotion_reason

    def test_una_mejora_estable_pasa(self) -> None:
        decision = evaluar_promocion_predictiva(
            metrica=0.45,
            baseline=0.11,
            dispersion=0.03,
            nombre_metrica="pr_auc",
            mejor_es_mayor=True,
            motivos_extra=[],
        )
        assert decision.promocionable is True

    def test_el_veredicto_es_serializable_para_el_registro(self) -> None:
        """El backlog pedía «el número que lo justifica anotado»: la nota va a
        ``model_versions`` y las cifras a ``metrics_json``."""
        decision = evaluar_promocion_predictiva(
            metrica=0.12494,
            baseline=0.12999,
            dispersion=0.01287,
            nombre_metrica="mae_p50",
        )
        volcado = decision.as_dict()
        assert volcado["promotion_reason"] == decision.promotion_reason
        assert volcado["mejora_sobre_baseline"] == 0.00505
        assert volcado["dispersion_entre_folds"] == 0.01287
        assert volcado["margen_exigido"] == 0.01287
        assert volcado["promocionable"] is False


class TestDispersionPorBloques:
    """Retención no hace folds: la dispersión sale de bloques de validación."""

    def test_bloques_con_las_dos_clases_dan_desviacion(self) -> None:
        import numpy as np

        from services.ml.retencion_model import _pr_auc_por_bloques

        n = 90
        y = np.array([float(i % 2) for i in range(n)])
        # El primer tercio se predice bien y el último al revés: la dispersión
        # entre bloques tiene que ser distinta de cero.
        proba = np.concatenate(
            [
                np.array([0.9 if v else 0.1 for v in y[: n // 3]]),
                np.array([0.5] * (n // 3)),
                np.array([0.1 if v else 0.9 for v in y[2 * (n // 3) :]]),
            ]
        )
        desviacion, valores = _pr_auc_por_bloques(y, proba)
        assert desviacion is not None
        assert desviacion > 0
        assert len(valores) == 3

    def test_sin_filas_suficientes_no_hay_dispersion(self) -> None:
        """Y entonces el gate rechaza, en vez de leer la ausencia como cero."""
        import numpy as np

        from services.ml.retencion_model import _pr_auc_por_bloques

        y = np.array([0.0, 1.0] * 10)
        desviacion, valores = _pr_auc_por_bloques(y, np.linspace(0, 1, 20))
        assert desviacion is None
        assert valores == []

    def test_un_bloque_de_una_sola_clase_se_descarta(self) -> None:
        import numpy as np

        from services.ml.retencion_model import _pr_auc_por_bloques

        n = 90
        # Los dos primeros bloques alternan clases; el último es todo negativo.
        y = np.array([float(i % 2) for i in range(2 * (n // 3))] + [0.0] * (n - 2 * (n // 3)))
        proba = np.array([0.6] * n)
        desviacion, valores = _pr_auc_por_bloques(y, proba)
        assert len(valores) == 2
        assert desviacion is not None
