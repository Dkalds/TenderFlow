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
