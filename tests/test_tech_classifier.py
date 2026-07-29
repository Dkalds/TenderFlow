"""Unit tests para el clasificador multi-tecnología (TechnologyClassifier)."""

from __future__ import annotations

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")
pytest.importorskip("sklearn")

from config.keywords import TECH_LABELS
from scraper.ml_pipeline import (
    _build_multilabel_dataset,
    _keyword_fallback_score,
    _parse_tecnologia_csv,
)
from scraper.tech_classifier import (
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


def _make_synthetic_df() -> pd.DataFrame:
    """Genera un dataset sintético desbalanceado para validar los 3 tiers.

    Usa vocabulario variado para evitar que las probabilidades calibradas
    se agrupen en un rango estrecho y produzcan thresholds sobreajustados.
    """
    rows: list[dict[str, str]] = []

    # SAP: 60 positivos → ml_ready (>= ML_TECH_MIN_POS_READY=50)
    sap_templates = [
        ("SAP S/4HANA migración módulo finanzas", "implantación abap fiori"),
        ("Consultoría SAP ERP recursos humanos", "soporte sap hcm netweaver"),
        ("Licencias SAP plataforma analítica", "sap bw business objects"),
        ("Migración SAP módulo logística", "sap mm sd transporte"),
        ("SAP integración sistemas corporativos", "sap pi po middleware"),
        ("Desarrollo ABAP SAP a medida", "fiori launchpad ui5 netweaver"),
        ("SAP SuccessFactors gestión talento", "rrhh nóminas formación"),
        ("Soporte SAP basis administración", "sap solution manager solman"),
        ("SAP Ariba aprovisionamiento digital", "compras contratos proveedores"),
        ("SAP Analytics Cloud informes", "sac dashboard kpi cuadro mando"),
        ("SAP BTP cloud nativo", "business technology platform apis"),
        ("Actualización SAP ECC a S/4HANA", "upgrade migración datos legacy"),
    ]
    for i in range(60):
        t = sap_templates[i % len(sap_templates)]
        rows.append(
            {
                "titulo": f"{t[0]} {i}",
                "descripcion": t[1],
                "tecnologia": "SAP",
            }
        )
    # SALESFORCE: 25 positivos → fragile (entre 20 y 50)
    sf_templates = [
        ("Salesforce CRM implantación", "sales cloud service cloud"),
        ("Salesforce Einstein analytics", "apex visualforce lightning"),
        ("Salesforce Marketing Cloud campaña", "pardot automatización email"),
        ("Salesforce integración MuleSoft", "api gateway conectores datos"),
        ("Salesforce CPQ presupuestos", "commerce cloud b2b ventas"),
    ]
    for i in range(25):
        t = sf_templates[i % len(sf_templates)]
        rows.append(
            {
                "titulo": f"{t[0]} {i}",
                "descripcion": t[1],
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
    # Negativos genéricos (variados para evitar clustering extremo)
    neg_templates = [
        ("Servicio limpieza edificio", "mantenimiento jardinería"),
        ("Suministro material oficina", "papelería mobiliario equipo"),
        ("Obras reforma instalaciones", "albañilería electricidad fontanería"),
        ("Vigilancia seguridad privada", "control accesos cámaras alarmas"),
        ("Transporte escolar rutas", "autobuses conductores horarios"),
        ("Catering comedor hospital", "alimentación dietas menús"),
        ("Gestión residuos recogida", "reciclaje contenedores vertedero"),
        ("Consultoría medioambiental impacto", "evaluación sostenibilidad huella"),
    ]
    for i in range(80):
        t = neg_templates[i % len(neg_templates)]
        rows.append(
            {
                "titulo": f"{t[0]} {i}",
                "descripcion": t[1],
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


# ── init, predict_one/predict_batch sin entrenar, score_one por tier ─────────


class TestTechnologyClassifierInit:
    def test_init_defaults(self) -> None:
        clf = TechnologyClassifier()
        assert clf._trained is False
        assert isinstance(clf.labels, list)
        assert len(clf._models) == 0

    def test_predict_one_raises_untrained(self) -> None:
        clf = TechnologyClassifier()
        with pytest.raises(RuntimeError, match="no entrenado"):
            clf.predict_one("test text")

    def test_predict_batch_raises_untrained(self) -> None:
        clf = TechnologyClassifier()
        with pytest.raises(RuntimeError, match="no entrenado"):
            clf.predict_batch([{"text": "test"}])

    def test_predict_batch_empty(self) -> None:
        clf = TechnologyClassifier()
        clf._trained = True
        assert clf.predict_batch([]) == []


class TestTechnologyClassifierScoreOne:
    def test_score_one_rules_tier(self) -> None:
        from unittest.mock import patch

        clf = TechnologyClassifier()
        clf._trained = True
        for lbl in clf.labels:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.5

        with patch("scraper.tech_classifier._augment_text", return_value="SAP ERP system"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.8):
                result = clf.predict_one("SAP ERP system")
        assert "scores" in result
        assert "predicted" in result

    def test_score_one_ml_tier(self) -> None:
        from unittest.mock import MagicMock, patch

        clf = TechnologyClassifier()
        clf._trained = True
        label = clf.labels[0]
        clf._tier[label] = "ml_ready"
        clf._thresholds[label] = 0.5
        mock_pipe = MagicMock()
        mock_pipe.predict_proba.return_value = [[0.1, 0.9]]
        clf._models[label] = mock_pipe
        for lbl in clf.labels[1:]:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.5

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.0):
                result = clf.predict_one("text")
        assert result["scores"][label] == 0.9

    def test_score_one_model_none(self) -> None:
        from unittest.mock import patch

        clf = TechnologyClassifier()
        clf._trained = True
        label = clf.labels[0]
        clf._tier[label] = "ml_ready"
        clf._thresholds[label] = 0.5
        clf._models[label] = None
        for lbl in clf.labels[1:]:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.5

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.0):
                result = clf.predict_one("text")
        assert result["scores"][label] == 0.0

    def test_score_one_model_predict_exception(self) -> None:
        from unittest.mock import MagicMock, patch

        clf = TechnologyClassifier()
        clf._trained = True
        label = clf.labels[0]
        clf._tier[label] = "ml_ready"
        clf._thresholds[label] = 0.5
        mock_pipe = MagicMock()
        mock_pipe.predict_proba.side_effect = RuntimeError("boom")
        clf._models[label] = mock_pipe
        for lbl in clf.labels[1:]:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.5

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.0):
                result = clf.predict_one("text")
        assert result["scores"][label] == 0.0

    def test_predict_one_no_predicted_labels(self) -> None:
        from unittest.mock import patch

        clf = TechnologyClassifier()
        clf._trained = True
        for lbl in clf.labels:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.99

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.1):
                result = clf.predict_one("text")
        assert result["principal"] is None
        assert result["max_proba"] == 0.1

    def test_predict_one_low_confidence(self) -> None:
        from unittest.mock import MagicMock, patch

        clf = TechnologyClassifier()
        clf._trained = True
        label = clf.labels[0]
        clf._tier[label] = "fragile"
        clf._thresholds[label] = 0.3
        mock_pipe = MagicMock()
        mock_pipe.predict_proba.return_value = [[0.1, 0.9]]
        clf._models[label] = mock_pipe
        for lbl in clf.labels[1:]:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.99

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.0):
                result = clf.predict_one("text")
        assert label in result["low_confidence_techs"]


class TestTechnologyClassifierThreshold:
    def test_threshold_override(self) -> None:
        from unittest.mock import patch

        clf = TechnologyClassifier()
        with patch("scraper.tech_classifier.settings") as mock_settings:
            mock_settings.ML_TECH_THRESHOLDS = {"SAP": "0.7"}
            mock_settings.ML_TECH_DEFAULT_THRESHOLD = 0.5
            result = clf._threshold_for("SAP")
        assert result == 0.7

    def test_threshold_override_invalid(self) -> None:
        from unittest.mock import patch

        clf = TechnologyClassifier()
        clf._thresholds["SAP"] = 0.6
        with patch("scraper.tech_classifier.settings") as mock_settings:
            mock_settings.ML_TECH_THRESHOLDS = {"SAP": "not_a_number"}
            mock_settings.ML_TECH_DEFAULT_THRESHOLD = 0.5
            result = clf._threshold_for("SAP")
        assert result == 0.6

    def test_threshold_no_override(self) -> None:
        from unittest.mock import patch

        clf = TechnologyClassifier()
        clf._thresholds["SAP"] = 0.65
        with patch("scraper.tech_classifier.settings") as mock_settings:
            mock_settings.ML_TECH_THRESHOLDS = {}
            mock_settings.ML_TECH_DEFAULT_THRESHOLD = 0.5
            result = clf._threshold_for("SAP")
        assert result == 0.65

    def test_threshold_none_overrides(self) -> None:
        from unittest.mock import patch

        clf = TechnologyClassifier()
        with patch("scraper.tech_classifier.settings") as mock_settings:
            mock_settings.ML_TECH_THRESHOLDS = None
            mock_settings.ML_TECH_DEFAULT_THRESHOLD = 0.5
            result = clf._threshold_for("UNKNOWN_LABEL")
        assert result == 0.5


class TestTechnologyClassifierPredictBatch:
    def test_predict_batch_ml_model_exception(self) -> None:
        from unittest.mock import MagicMock, patch

        clf = TechnologyClassifier()
        clf._trained = True
        label = clf.labels[0]
        clf._tier[label] = "ml_ready"
        clf._thresholds[label] = 0.5
        mock_pipe = MagicMock()
        mock_pipe.predict_proba.side_effect = RuntimeError("boom")
        clf._models[label] = mock_pipe
        for lbl in clf.labels[1:]:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.5

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.0):
                results = clf.predict_batch([{"text": "hello"}])
        assert len(results) == 1
        assert results[0]["scores"][label] == 0.0

    def test_predict_batch_no_predicted(self) -> None:
        from unittest.mock import patch

        clf = TechnologyClassifier()
        clf._trained = True
        for lbl in clf.labels:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.99

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.1):
                results = clf.predict_batch([{"text": "nothing"}])
        assert results[0]["principal"] is None
        assert results[0]["max_proba"] == 0.1

    def test_predict_batch_model_none(self) -> None:
        from unittest.mock import patch

        clf = TechnologyClassifier()
        clf._trained = True
        label = clf.labels[0]
        clf._tier[label] = "fragile"
        clf._thresholds[label] = 0.5
        clf._models[label] = None
        for lbl in clf.labels[1:]:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.5

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.0):
                results = clf.predict_batch([{"text": "hello"}])
        assert results[0]["scores"][label] == 0.0

    def test_predict_batch_with_predicted(self) -> None:
        from unittest.mock import MagicMock, patch

        clf = TechnologyClassifier()
        clf._trained = True
        label = clf.labels[0]
        clf._tier[label] = "ml_ready"
        clf._thresholds[label] = 0.3
        mock_pipe = MagicMock()
        mock_pipe.predict_proba.return_value = [[0.1, 0.9]]
        clf._models[label] = mock_pipe
        for lbl in clf.labels[1:]:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.99

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.0):
                results = clf.predict_batch([{"text": "hello"}])
        assert results[0]["principal"] == label
        assert results[0]["max_proba"] == 0.9

    def test_predict_batch_fragile_low_conf(self) -> None:
        from unittest.mock import MagicMock, patch

        clf = TechnologyClassifier()
        clf._trained = True
        label = clf.labels[0]
        clf._tier[label] = "fragile"
        clf._thresholds[label] = 0.3
        mock_pipe = MagicMock()
        mock_pipe.predict_proba.return_value = [[0.1, 0.9]]
        clf._models[label] = mock_pipe
        for lbl in clf.labels[1:]:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.99

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.0):
                results = clf.predict_batch([{"text": "hello"}])
        assert label in results[0]["low_confidence_techs"]


class TestTechnologyClassifierPersistence:
    def test_save(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        clf = TechnologyClassifier()
        clf._trained = True
        target = tmp_path / "model.pkl"

        with patch("joblib.dump") as mock_dump:
            # Write a fake file so sha256 works
            target.write_bytes(b"fake model data")
            clf.save(path=target)
            mock_dump.assert_called_once()
        # Check sha256 sidecar was created
        sha_path = target.with_suffix(".sha256")
        assert sha_path.exists()

    def test_load_missing(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            TechnologyClassifier.load(path=tmp_path / "nope.pkl")

    def test_load_bad_checksum(self, tmp_path: Path) -> None:
        target = tmp_path / "model.pkl"
        target.write_bytes(b"fake model")
        sha_path = target.with_suffix(".sha256")
        sha_path.write_text("wrong_hash", encoding="utf-8")

        with pytest.raises(RuntimeError, match="checksum co-ubicado"):
            TechnologyClassifier.load(path=target)

    def test_load_wrong_type(self, tmp_path: Path, monkeypatch) -> None:
        from unittest.mock import patch

        from config import settings

        target = tmp_path / "model.pkl"
        target.write_bytes(b"fake")
        # No sha file so checksum check is skipped (ENV=dev: no fallo duro)
        monkeypatch.setattr(settings, "ENV", "dev")

        with patch("joblib.load", return_value="not_a_classifier"):
            with pytest.raises(TypeError, match="no contiene"):
                TechnologyClassifier.load(path=target)

    def test_load_valid_no_sha(self, tmp_path: Path, monkeypatch) -> None:
        from unittest.mock import MagicMock, patch

        from config import settings

        target = tmp_path / "model.pkl"
        target.write_bytes(b"fake")
        monkeypatch.setattr(settings, "ENV", "dev")

        mock_clf = MagicMock(spec=TechnologyClassifier)
        type(mock_clf).__name__ = "TechnologyClassifier"

        with patch("joblib.load", return_value=mock_clf):
            result = TechnologyClassifier.load(path=target)
        assert result is mock_clf

    def test_load_pin_detects_tampered_model(self, tmp_path: Path, monkeypatch) -> None:
        """El pin out-of-band ML_TECH_MODEL_SHA256 detecta un .pkl manipulado
        incluso si el .sha256 co-ubicado se regeneró junto con él (release
        comprometido)."""
        import hashlib

        from config import settings

        target = tmp_path / "model.pkl"
        target.write_bytes(b"modelo original")
        original_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        monkeypatch.setattr(settings, "ML_TECH_MODEL_SHA256", original_hash)

        target.write_bytes(b"contenido manipulado")
        tampered_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        target.with_suffix(".sha256").write_text(tampered_hash, encoding="utf-8")

        with pytest.raises(RuntimeError, match="ML_TECH_MODEL_SHA256"):
            TechnologyClassifier.load(path=target)

    def test_load_prod_without_pin_or_checksum_raises(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """En ENV=prod, sin pin ni checksum co-ubicado, load() falla duro."""
        from config import settings

        target = tmp_path / "model.pkl"
        target.write_bytes(b"fake model")
        # Sin .sha256 co-ubicado y sin pin.
        monkeypatch.setattr(settings, "ML_TECH_MODEL_SHA256", "")
        monkeypatch.setattr(settings, "ENV", "prod")

        with pytest.raises(RuntimeError, match="Sin verificación de integridad"):
            TechnologyClassifier.load(path=target)

    def test_is_available(self, tmp_path: Path) -> None:
        assert TechnologyClassifier.is_available(path=tmp_path / "nope.pkl") is False
        f = tmp_path / "model.pkl"
        f.write_bytes(b"x")
        assert TechnologyClassifier.is_available(path=f) is True


class TestTechnologyClassifierTrain:
    def test_missing_tecnologia_column(self) -> None:
        clf = TechnologyClassifier()
        df = pd.DataFrame({"titulo": ["a"], "descripcion": ["b"]})
        result = clf.train(df)
        assert result == {"error": "missing_tecnologia_column"}

    def test_insufficient_data(self) -> None:
        from unittest.mock import patch

        import numpy as np

        with patch("scraper.tech_classifier._build_multilabel_dataset") as mock_build:
            mock_build.return_value = (["t"] * 5, np.zeros((5, 2)), [0, 0])
            clf = TechnologyClassifier()
            df = pd.DataFrame({"titulo": ["a"], "descripcion": ["b"], "tecnologia": ["SAP"]})
            result = clf.train(df)
        assert result["error"] == "insufficient_data"


class TestTechTrainFromDb:
    def test_reads_from_database(self) -> None:
        from unittest.mock import MagicMock, patch

        with (
            patch("scraper.tech_classifier.TechnologyClassifier") as mock_cls,
            patch("db.connection.connect_read") as mock_conn_read,
        ):
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = [
                ("id1", "titulo", "desc", "48000000", 1000, "2024-01-01", "SAP", "sap"),
            ]
            mock_conn_read.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn_read.return_value.__exit__ = MagicMock(return_value=False)

            mock_instance = MagicMock()
            mock_instance.train.return_value = {"f1": 0.9}
            mock_cls.return_value = mock_instance

            from scraper.tech_classifier import train_from_db

            result = train_from_db()
            mock_instance.save.assert_called_once()
