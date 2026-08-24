"""Gate de promoción único y evaluación honesta del golden set.

Fija tres invariantes que el código violaba:

- El gate comparaba ``f1``/``pr_auc``/``brier`` de dos modelos medidos **cada
  uno sobre su propio test split**, recalculado en cada reentrenamiento sobre
  un dataset que crece. Eso no compara modelos: compara conjuntos de
  evaluación. Ahora la decisión la toma el golden set humano, que es fijo.
- Gateaba sobre etiquetas derivadas del filtro de keywords, así que un modelo
  que se limita a reproducir el regex pasaba con nota. ``recall_no_keyword``
  —lo único que mide valor incremental— se guardaba pero no bloqueaba.
- El umbral se elegía y se reportaba sobre el mismo golden set de 27 ejemplos.
"""

from __future__ import annotations

from services.ml.promotion import MIN_RECALL_NO_KEYWORD, evaluar_gate
from services.ml_eval import (
    SPLIT_HOLDOUT,
    SPLIT_TUNE,
    GoldenExample,
    asignar_splits,
    evaluate_probas,
    filtrar_split,
    metricas_operativas,
)

_METRICAS_OK: dict[str, object] = {
    "f1": 0.90,
    "pr_auc": 0.92,
    "brier": 0.08,
    "n_test": 400,
    "n_positive_test": 120,
    "metrics_reliable": True,
    "split_strategy": "temporal",
}


def _golden(recall_no_kw: float, n_no_kw_pos: int = 20) -> object:
    """Construye un GoldenEvalResult con el recall incremental pedido."""
    y_true = [1] * n_no_kw_pos + [0] * n_no_kw_pos
    aciertos = round(recall_no_kw * n_no_kw_pos)
    y_proba = [0.9] * aciertos + [0.1] * (n_no_kw_pos - aciertos) + [0.1] * n_no_kw_pos
    kw = [False] * n_no_kw_pos + [False] * n_no_kw_pos
    return evaluate_probas(y_true, y_proba, keyword_match=kw, threshold=0.5)


class TestGateDeCalidad:
    def test_un_modelo_bueno_pasa(self) -> None:
        assert evaluar_gate(_METRICAS_OK, metricas_activas=None, golden=_golden(0.60)) == []

    def test_bloquea_si_no_aporta_sobre_las_keywords(self) -> None:
        # Un modelo que solo replica matches_sap() tiene recall_no_keyword ≈ 0:
        # servir el regex es más barato que servir un pickle que hace lo mismo.
        motivos = evaluar_gate(_METRICAS_OK, metricas_activas=None, golden=_golden(0.0))
        assert any("recall_no_keyword" in m for m in motivos), motivos

    def test_el_umbral_de_aporte_minimo_es_el_documentado(self) -> None:
        justo_debajo = _golden(MIN_RECALL_NO_KEYWORD / 2, n_no_kw_pos=20)
        assert any(
            "recall_no_keyword" in m
            for m in evaluar_gate(_METRICAS_OK, metricas_activas=None, golden=justo_debajo)
        )

    def test_bloquea_si_las_metricas_no_son_fiables(self) -> None:
        # Un f1 a cuatro decimales sobre 8 filas de test no es una medición.
        metricas = {**_METRICAS_OK, "metrics_reliable": False, "n_test": 8}
        motivos = evaluar_gate(metricas, metricas_activas=None, golden=_golden(0.60))
        assert any("metricas_no_fiables" in m for m in motivos), motivos

    def test_bloquea_sin_golden_set(self) -> None:
        motivos = evaluar_gate(_METRICAS_OK, metricas_activas=None, golden=None)
        assert any("sin_golden_set" in m for m in motivos), motivos

    def test_bloquea_si_el_golden_no_tiene_zona_de_desacuerdo(self) -> None:
        vacio = evaluate_probas([1, 0], [0.9, 0.1], keyword_match=[True, True], threshold=0.5)
        motivos = evaluar_gate(_METRICAS_OK, metricas_activas=None, golden=vacio)
        assert any("zona_de_desacuerdo" in m for m in motivos), motivos

    def test_bloquea_si_el_recall_incremental_cae_frente_al_activo(self) -> None:
        motivos = evaluar_gate(
            _METRICAS_OK,
            metricas_activas=None,
            golden=_golden(0.30),
            golden_activo=_golden(0.70),
        )
        assert any("cae" in m for m in motivos), motivos

    def test_detecta_regresion_en_el_test_split(self) -> None:
        motivos = evaluar_gate(
            {**_METRICAS_OK, "f1": 0.70},
            metricas_activas={"f1": 0.90, "pr_auc": 0.92, "brier": 0.08},
            golden=_golden(0.60),
        )
        assert any(m.startswith("f1") for m in motivos), motivos


class TestSplitDelGoldenSet:
    def _ejemplos(self, n: int) -> list[GoldenExample]:
        return [
            GoldenExample(id=f"ej-{i}", titulo=f"t{i}", descripcion="", label=i % 2)
            for i in range(n)
        ]

    def test_tune_y_holdout_son_disjuntos_y_cubren_todo(self) -> None:
        asignados = asignar_splits(self._ejemplos(200))
        tune = {e.id for e in filtrar_split(asignados, SPLIT_TUNE)}
        holdout = {e.id for e in filtrar_split(asignados, SPLIT_HOLDOUT)}
        assert not (tune & holdout)
        assert len(tune) + len(holdout) == 200

    def test_la_asignacion_es_estable(self) -> None:
        primera = {e.id: e.split for e in asignar_splits(self._ejemplos(100))}
        segunda = {e.id: e.split for e in asignar_splits(self._ejemplos(100))}
        assert primera == segunda

    def test_añadir_ejemplos_no_reasigna_los_existentes(self) -> None:
        # Si ampliar el golden set reasignara las mitades, cada ampliación
        # invalidaría la comparación con las métricas anteriores.
        antes = {e.id: e.split for e in asignar_splits(self._ejemplos(100))}
        despues = {e.id: e.split for e in asignar_splits(self._ejemplos(300))}
        for ident, split in antes.items():
            assert despues[ident] == split

    def test_el_split_explicito_del_jsonl_se_respeta(self) -> None:
        ejemplos = [
            GoldenExample(id="a", titulo="t", descripcion="", label=1, split=SPLIT_TUNE),
            GoldenExample(id="b", titulo="t", descripcion="", label=0, split=SPLIT_HOLDOUT),
        ]
        asignados = {e.id: e.split for e in asignar_splits(ejemplos)}
        assert asignados == {"a": SPLIT_TUNE, "b": SPLIT_HOLDOUT}

    def test_el_reparto_es_aproximadamente_mitad_y_mitad(self) -> None:
        asignados = asignar_splits(self._ejemplos(1000))
        n_tune = len(filtrar_split(asignados, SPLIT_TUNE))
        assert 400 <= n_tune <= 600, n_tune


class TestMetricasOperativas:
    def test_precision_at_k_mira_la_cabeza_de_la_cola(self) -> None:
        # 5 relevantes en las 5 primeras posiciones → precision@5 = 1.0
        y = [1] * 5 + [0] * 15
        proba = [0.9 - i * 0.01 for i in range(20)]
        out = metricas_operativas(y, proba, ks=(5, 10))
        assert out["precision_at_5"] == 1.0
        assert out["precision_at_10"] == 0.5

    def test_recall_a_precision_fija(self) -> None:
        y = [1, 1, 1, 0, 0, 0]
        proba = [0.9, 0.8, 0.7, 0.2, 0.1, 0.05]
        out = metricas_operativas(y, proba, precisiones_objetivo=(0.9,))
        assert out["recall_at_precision_90"] == 1.0

    def test_el_coste_esperado_usa_la_asimetria_configurada(self) -> None:
        # Con FN mucho más caro que FP, el umbral de coste mínimo baja.
        y = [1, 1, 0, 0]
        proba = [0.6, 0.4, 0.35, 0.1]
        caro_fn = metricas_operativas(y, proba, cost_fp=1.0, cost_fn=10.0)
        caro_fp = metricas_operativas(y, proba, cost_fp=10.0, cost_fn=1.0)
        assert caro_fn["coste_esperado_min_threshold"] <= caro_fp["coste_esperado_min_threshold"]

    def test_conjunto_vacio_no_revienta(self) -> None:
        assert metricas_operativas([], []) == {}
