"""Tests de la evaluación honesta multi-label (services/ml/eval_tech.py).

El foco no es "que las métricas salgan altas" sino que ``recall_no_keyword``
sea capaz de suspender a un modelo que se limita a imitar a
``matches_technology``: ese es el fallo que las métricas internas del
entrenamiento no pueden detectar.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config.keywords import TECH_LABELS
from services.ml.eval_tech import (
    GoldenTechExample,
    evaluate_tech_classifier,
    evaluate_tech_predictions,
    keyword_labels_for,
    load_golden_tech_set,
)


class TestLoadGoldenTechSet:
    def test_loads_seed_fixture(self) -> None:
        examples = load_golden_tech_set()
        assert len(examples) >= 10, "El golden set semilla debe tener ejemplos suficientes"
        assert all(set(ex.labels) <= set(TECH_LABELS) for ex in examples)

    def test_seed_tiene_positivos_sin_keyword(self) -> None:
        """Sin positivos fuera del alcance del regex, recall_no_keyword no mide nada."""
        examples = load_golden_tech_set()
        sin_kw = [ex for ex in examples if set(ex.labels) - set(ex.keyword_labels)]
        assert sin_kw, "Faltan ejemplos con tecnología que las keywords NO detectan"
        # Y varias tecnologías distintas, no todo SAP.
        techs = {t for ex in sin_kw for t in set(ex.labels) - set(ex.keyword_labels)}
        assert len(techs) >= 3

    def test_seed_tiene_negativos_revisados(self) -> None:
        """Sin negativos no se puede medir precisión."""
        examples = load_golden_tech_set()
        assert [ex for ex in examples if not ex.labels]

    def test_keyword_labels_se_derivan_del_filtro_real(self) -> None:
        examples = load_golden_tech_set()
        for ex in examples:
            assert ex.keyword_labels == keyword_labels_for(ex.titulo, ex.descripcion)

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_golden_tech_set(tmp_path / "no_existe.jsonl") == []

    def test_ignores_comments_and_blanks(self, tmp_path: Path) -> None:
        f = tmp_path / "g.jsonl"
        f.write_text(
            '# comentario\n\n{"id": "a", "titulo": "SAP ECC", "descripcion": "x", '
            '"labels": ["SAP"]}\n',
            encoding="utf-8",
        )
        examples = load_golden_tech_set(f)
        assert len(examples) == 1
        assert examples[0].id == "a"
        assert examples[0].labels == ["SAP"]
        assert examples[0].keyword_labels == ["SAP"]

    def test_keyword_labels_explicitas_ganan(self, tmp_path: Path) -> None:
        f = tmp_path / "g.jsonl"
        f.write_text(
            '{"id": "a", "titulo": "SAP ECC", "descripcion": "", "labels": ["SAP"], '
            '"keyword_labels": []}\n',
            encoding="utf-8",
        )
        assert load_golden_tech_set(f)[0].keyword_labels == []

    def test_labels_admite_csv(self, tmp_path: Path) -> None:
        f = tmp_path / "g.jsonl"
        f.write_text(
            '{"id": "a", "titulo": "t", "descripcion": "", "labels": "sap, oracle"}\n',
            encoding="utf-8",
        )
        assert load_golden_tech_set(f)[0].labels == ["SAP", "ORACLE"]

    def test_etiqueta_desconocida_falla(self, tmp_path: Path) -> None:
        """Un typo convertiría un positivo humano en negativo sin avisar."""
        f = tmp_path / "g.jsonl"
        f.write_text(
            '{"id": "a", "titulo": "t", "descripcion": "", "labels": ["SALEFORCE"]}\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="desconocida"):
            load_golden_tech_set(f)

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.jsonl"
        f.write_text("{no es json}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="línea 1"):
            load_golden_tech_set(f)

    def test_falta_labels_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.jsonl"
        f.write_text('{"id": "a", "titulo": "t"}\n', encoding="utf-8")
        with pytest.raises(ValueError, match="labels"):
            load_golden_tech_set(f)


class TestEvaluateTechPredictions:
    def test_prediccion_perfecta(self) -> None:
        y_true = [["SAP"], ["ORACLE", "SAP"], []]
        result = evaluate_tech_predictions(y_true, y_true, labels=["SAP", "ORACLE"])
        assert result.micro_f1 == 1.0
        assert result.macro_f1_all_labels == 1.0
        assert result.per_label["SAP"].support == 2

    def test_macro_all_labels_penaliza_las_etiquetas_sin_datos(self) -> None:
        """Promediar sólo las etiquetas con soporte es un promedio de aprobados."""
        y_true = [["SAP"], ["SAP"]]
        result = evaluate_tech_predictions(y_true, y_true, labels=["SAP", "ORACLE", "WORKDAY"])
        assert result.macro_f1_labels_con_soporte == 1.0
        assert result.macro_f1_all_labels == pytest.approx(1 / 3)
        assert result.n_labels_sin_soporte == 2

    def test_recall_no_keyword_suspende_al_imitador_del_regex(self) -> None:
        """Un modelo que replica exactamente las keywords: F1 alto, valor cero."""
        y_true = [["SAP"], ["SAP"], ["ORACLE"]]
        kw = [["SAP"], [], ["ORACLE"]]  # el 2º es SAP que el regex NO pesca
        result = evaluate_tech_predictions(y_true, kw, keyword_labels=kw, labels=["SAP", "ORACLE"])
        assert result.micro_f1 > 0.75  # se ve bien...
        assert result.recall_no_keyword == 0.0  # ...y no aporta nada
        assert result.per_label["SAP"].n_no_keyword_positive == 1
        assert result.per_label["SAP"].n_no_keyword_caught == 0

    def test_recall_no_keyword_premia_al_que_pesca_sin_keyword(self) -> None:
        y_true = [["SAP"], ["SAP"]]
        kw = [["SAP"], []]
        y_pred = [["SAP"], ["SAP"]]
        result = evaluate_tech_predictions(y_true, y_pred, keyword_labels=kw, labels=["SAP"])
        assert result.recall_no_keyword == 1.0
        assert result.per_label["SAP"].n_no_keyword_caught == 1

    def test_recall_no_keyword_es_por_etiqueta(self) -> None:
        y_true = [["SAP"], ["ORACLE"]]
        kw = [[], []]
        y_pred = [["SAP"], []]
        result = evaluate_tech_predictions(
            y_true, y_pred, keyword_labels=kw, labels=["SAP", "ORACLE"]
        )
        assert result.per_label["SAP"].recall_no_keyword == 1.0
        assert result.per_label["ORACLE"].recall_no_keyword == 0.0
        assert result.recall_no_keyword == 0.5

    def test_falsos_positivos_bajan_precision(self) -> None:
        result = evaluate_tech_predictions([[], []], [["SAP"], ["SAP"]], labels=["SAP"])
        assert result.per_label["SAP"].fp == 2
        assert result.micro_precision == 0.0

    def test_sin_ejemplos(self) -> None:
        result = evaluate_tech_predictions([], [], labels=["SAP"])
        assert result.n == 0
        assert result.micro_f1 == 0.0
        assert result.n_labels_sin_soporte == 1

    def test_sin_keyword_labels_no_rompe(self) -> None:
        result = evaluate_tech_predictions([["SAP"]], [["SAP"]], labels=["SAP"])
        assert result.recall_no_keyword == 0.0
        assert result.n_no_keyword_positive == 0

    def test_as_dict_y_as_rows_serializan(self) -> None:
        result = evaluate_tech_predictions([["SAP"]], [["SAP"]], labels=["SAP", "ORACLE"])
        assert result.as_dict()["micro_f1"] == 1.0
        rows = result.as_rows()
        assert rows[0]["label"] == "SAP"  # ordenado por soporte descendente


class _FakeClassifier:
    """Clasificador mínimo que devuelve etiquetas fijas por texto."""

    def __init__(self, respuestas: dict[str, list[str]]) -> None:
        self.labels = ["SAP", "ORACLE"]
        self._respuestas = respuestas

    def predict_one(
        self, text: str, *, cpv: str | None = None, importe: float | None = None
    ) -> dict[str, object]:
        return {"predicted": self._respuestas.get(text, [])}


class TestEvaluateTechClassifier:
    def _examples(self) -> list[GoldenTechExample]:
        return [
            GoldenTechExample(
                id="1", titulo="SAP ECC", descripcion="", labels=["SAP"], keyword_labels=["SAP"]
            ),
            GoldenTechExample(
                id="2",
                titulo="ERP de Walldorf",
                descripcion="",
                labels=["SAP"],
                keyword_labels=[],
            ),
        ]

    def test_usa_predicted_del_modelo(self) -> None:
        clf = _FakeClassifier({"SAP ECC": ["SAP"], "ERP de Walldorf": ["SAP"]})
        result = evaluate_tech_classifier(clf, self._examples())
        assert result.per_label["SAP"].recall == 1.0
        assert result.recall_no_keyword == 1.0

    def test_modelo_que_solo_imita_keywords(self) -> None:
        clf = _FakeClassifier({"SAP ECC": ["SAP"], "ERP de Walldorf": []})
        result = evaluate_tech_classifier(clf, self._examples())
        assert result.per_label["SAP"].recall == 0.5
        assert result.recall_no_keyword == 0.0

    def test_universo_de_etiquetas_por_defecto_es_el_del_modelo(self) -> None:
        clf = _FakeClassifier({})
        result = evaluate_tech_classifier(clf, self._examples())
        assert set(result.per_label) == {"SAP", "ORACLE"}

    def test_sin_ejemplos_devuelve_resultado_vacio(self) -> None:
        clf = _FakeClassifier({})
        result = evaluate_tech_classifier(clf, [])
        assert result.n == 0
