"""Unit tests para el clasificador multi-tecnología (TechnologyClassifier)."""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")
pytest.importorskip("sklearn")

from config.keywords import TECH_LABELS  # noqa: E402
from scraper.ml_pipeline import (  # noqa: E402
    _build_multilabel_dataset,
    _keyword_fallback_score,
    _parse_tecnologia_csv,
)
from scraper.tech_classifier import (  # noqa: E402
    _TIER_FRAGILE,
    _TIER_ML_READY,
    _TIER_RULES,
    TechnologyClassifier,
)


# ── Helpers de bajo nivel ──────────────────────────────────────────────────


class TestParseTecnologiaCsv:
    def test_none_returns_empty(self):
        assert _parse_tecnologia_csv(None) == []

    def test_empty_string_returns_empty(self):
        assert _parse_tecnologia_csv("") == []
        assert _parse_tecnologia_csv("   ") == []

    def test_single_label(self):
        assert _parse_tecnologia_csv("SAP") == ["SAP"]

    def test_multiple_labels(self):
        result = _parse_tecnologia_csv("SAP,ORACLE,SALESFORCE")
        assert set(result) == {"SAP", "ORACLE", "SALESFORCE"}

    def test_normalises_whitespace_and_case(self):
        result = _parse_tecnologia_csv(" sap , Oracle ,salesforce ")
        assert set(result) == {"SAP", "ORACLE", "SALESFORCE"}

    def test_drops_unknown_labels(self):
        result = _parse_tecnologia_csv("SAP,FOO,ORACLE")
        # FOO no está en TECH_LABELS → debe descartarse
        assert "FOO" not in result
        assert "SAP" in result and "ORACLE" in result


class TestBuildMultilabelDataset:
    def test_shape_matches_labels(self):
        df = pd.DataFrame(
            {
                "titulo": ["t1", "t2", "t3"],
                "descripcion": ["d1", "d2", "d3"],
                "tecnologia": ["SAP", "SAP,ORACLE", "SALESFORCE"],
            }
        )
        texts, y, positives = _build_multilabel_dataset(df, TECH_LABELS)
        assert len(texts) == 3
        assert y.shape == (3, len(TECH_LABELS))
        assert len(positives) == len(TECH_LABELS)

    def test_multilabel_assignment(self):
        df = pd.DataFrame(
            {
                "titulo": ["a", "b"],
                "descripcion": ["x", "y"],
                "tecnologia": ["SAP,ORACLE", "SAP"],
            }
        )
        _, y, positives = _build_multilabel_dataset(df, TECH_LABELS)
        sap_idx = TECH_LABELS.index("SAP")
        oracle_idx = TECH_LABELS.index("ORACLE")
        assert y[:, sap_idx].sum() == 2
        assert y[:, oracle_idx].sum() == 1
        assert positives[sap_idx] == 2
        assert positives[oracle_idx] == 1


class TestKeywordFallbackScore:
    def test_match_returns_positive(self):
        score = _keyword_fallback_score("Implantación de SAP S/4HANA", ["sap", "s/4hana"])
        assert score > 0.0

    def test_no_match_returns_zero(self):
        score = _keyword_fallback_score("contrato de limpieza", ["sap", "s/4hana"])
        assert score == 0.0

    def test_empty_text_returns_zero(self):
        assert _keyword_fallback_score("", ["sap"]) == 0.0


# ── TechnologyClassifier (entrenamiento ligero) ─────────────────────────────


def _make_synthetic_df() -> "pd.DataFrame":
    """Genera un dataset sintético desbalanceado para validar los 3 tiers."""
    rows: list[dict[str, str]] = []
    # SAP: 60 positivos → ml_ready (>= ML_TECH_MIN_POS_READY=50)
    for i in range(60):
        rows.append(
            {
                "titulo": f"SAP S/4HANA migración módulo {i}",
                "descripcion": "implantación abap fiori netweaver",
                "tecnologia": "SAP",
            }
        )
    # SALESFORCE: 25 positivos → fragile (entre 20 y 50)
    for i in range(25):
        rows.append(
            {
                "titulo": f"salesforce einstein crm proyecto {i}",
                "descripcion": "apex visualforce lightning",
                "tecnologia": "SALESFORCE",
            }
        )
    # META4: 3 positivos → rules
    for i in range(3):
        rows.append(
            {
                "titulo": f"meta4 peoplenet nóminas {i}",
                "descripcion": "rrhh cezanne",
                "tecnologia": "META4",
            }
        )
    # Negativos genéricos
    for i in range(80):
        rows.append(
            {
                "titulo": f"servicio limpieza edificio {i}",
                "descripcion": "mantenimiento jardinería",
                "tecnologia": "",
            }
        )
    return pd.DataFrame(rows)


@pytest.mark.slow
class TestTechnologyClassifierTraining:
    def test_train_assigns_tiers_correctly(self):
        df = _make_synthetic_df()
        clf = TechnologyClassifier()
        metrics = clf.train(df)

        per_tech = metrics.get("per_tech", {})
        assert "SAP" in per_tech
        # SAP debe ser ml_ready
        assert per_tech["SAP"]["tier"] == _TIER_ML_READY
        # SALESFORCE debe ser fragile
        assert per_tech.get("SALESFORCE", {}).get("tier") == _TIER_FRAGILE
        # META4 debe ser rules (fallback por keywords)
        assert per_tech.get("META4", {}).get("tier") == _TIER_RULES

    def test_predict_one_returns_expected_structure(self):
        df = _make_synthetic_df()
        clf = TechnologyClassifier()
        clf.train(df)

        pred = clf.predict_one("Implantación SAP S/4HANA módulo finanzas")
        assert set(pred.keys()) >= {
            "scores",
            "predicted",
            "principal",
            "max_proba",
            "thresholds",
            "low_confidence_techs",
        }
        assert "SAP" in pred["scores"]
        assert pred["scores"]["SAP"] > 0.3
        assert "SAP" in pred["predicted"] or pred["principal"] == "SAP"

    def test_predict_meta4_uses_keyword_rules(self):
        df = _make_synthetic_df()
        clf = TechnologyClassifier()
        clf.train(df)
        # META4 está en tier 'rules' → debe puntuar > 0 si aparece la keyword
        pred = clf.predict_one("Contrato nóminas meta4 peoplenet")
        assert pred["scores"].get("META4", 0.0) > 0.0
