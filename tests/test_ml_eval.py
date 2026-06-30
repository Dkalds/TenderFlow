"""Tests de la evaluación honesta contra el golden set (services/ml_eval.py)."""

from __future__ import annotations

from services.ml_eval import (
    GoldenExample,
    evaluate_classifier,
    evaluate_probas,
    load_golden_set,
)


class TestLoadGoldenSet:
    def test_loads_seed_fixture(self) -> None:
        examples = load_golden_set()
        assert len(examples) >= 20, "El golden set seed debe tener ejemplos suficientes"
        assert all(ex.label in (0, 1) for ex in examples)
        # Debe incluir casos SAP que las keywords NO detectan (el valor del ML).
        no_kw_pos = [ex for ex in examples if ex.keyword_match is False and ex.label == 1]
        assert no_kw_pos, "Faltan ejemplos SAP-sin-keyword (zona de desacuerdo)"

    def test_missing_file_returns_empty(self, tmp_path) -> None:
        assert load_golden_set(tmp_path / "no_existe.jsonl") == []

    def test_ignores_comments_and_blanks(self, tmp_path) -> None:
        f = tmp_path / "g.jsonl"
        f.write_text(
            '# comentario\n\n{"id": "a", "titulo": "SAP", "descripcion": "x", "label": 1}\n',
            encoding="utf-8",
        )
        examples = load_golden_set(f)
        assert len(examples) == 1
        assert examples[0].id == "a"

    def test_invalid_json_raises(self, tmp_path) -> None:
        f = tmp_path / "bad.jsonl"
        f.write_text("{no es json}\n", encoding="utf-8")
        try:
            load_golden_set(f)
        except ValueError as exc:
            assert "línea 1" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("Debía lanzar ValueError")


class TestEvaluateProbas:
    def test_perfect_predictions(self) -> None:
        y_true = [1, 1, 0, 0]
        y_proba = [0.9, 0.8, 0.1, 0.2]
        result = evaluate_probas(y_true, y_proba, threshold=0.5)
        assert result.precision == 1.0
        assert result.recall == 1.0
        assert result.f1 == 1.0
        assert result.n_positive == 2
        assert result.n_negative == 2

    def test_recall_no_keyword_isolates_disagreement_zone(self) -> None:
        # 2 SAP sin keyword: uno detectado (0.8), otro perdido (0.2).
        y_true = [1, 1, 0]
        y_proba = [0.8, 0.2, 0.1]
        keyword_match = [False, False, False]
        result = evaluate_probas(
            y_true, y_proba, keyword_match=keyword_match, threshold=0.5
        )
        assert result.n_no_keyword_positive == 2
        assert result.n_no_keyword_caught == 1
        assert result.recall_no_keyword == 0.5

    def test_keyword_positives_excluded_from_no_keyword_recall(self) -> None:
        # SAP CON keyword no cuenta en recall_no_keyword.
        y_true = [1, 1]
        y_proba = [0.9, 0.9]
        keyword_match = [True, False]
        result = evaluate_probas(
            y_true, y_proba, keyword_match=keyword_match, threshold=0.5
        )
        assert result.n_no_keyword_positive == 1
        assert result.recall_no_keyword == 1.0

    def test_empty_input(self) -> None:
        result = evaluate_probas([], [], threshold=0.5)
        assert result.n == 0
        assert result.recall == 0.0


class _StubClassifier:
    """Clasificador fake: SAP si el texto contiene 'sap' o 'abap' (case-insensitive)."""

    _threshold = 0.5

    def predict(
        self, text: str, *, cpv: str | None = None, importe: float | None = None
    ) -> tuple[bool, float]:
        low = text.lower()
        proba = 0.9 if ("sap" in low or "abap" in low) else 0.1
        return proba >= self._threshold, proba


class TestEvaluateClassifier:
    def test_stub_against_provided_examples(self) -> None:
        examples = [
            GoldenExample("a", "Soporte SAP ECC", "", 1, keyword_match=True),
            GoldenExample("b", "Desarrollo ABAP del ERP", "", 1, keyword_match=False),
            GoldenExample("c", "Suministro de mobiliario", "", 0, keyword_match=False),
        ]
        result = evaluate_classifier(_StubClassifier(), examples)
        assert result.n == 3
        # El stub pesca el caso ABAP-sin-keyword → recall_no_keyword == 1.0
        assert result.n_no_keyword_positive == 1
        assert result.recall_no_keyword == 1.0

    def test_uses_classifier_threshold_when_none(self) -> None:
        examples = [GoldenExample("a", "SAP", "", 1, keyword_match=True)]
        result = evaluate_classifier(_StubClassifier(), examples, threshold=None)
        assert result.threshold == 0.5
