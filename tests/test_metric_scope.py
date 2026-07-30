"""Los agregados competitivos declaran universo y denominador."""

from __future__ import annotations

from db.database import connect
from services.competitive.mercado import metric_scope


def test_metric_scope_reports_exact_observed_denominator(tmp_db):
    _db_mod, _ = tmp_db
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, cpv, ccaa, fuente, fecha_extraccion, "
            "filter_version, classifier_model_version, inclusion_reason, analysis_universe) "
            "VALUES ('SCOPE-1', 'Contrato', '72000000', 'Madrid', 'placsp', "
            "CURRENT_TIMESTAMP, 'keywords-v1', 'model-v2', 'keyword', 'technology_observed')"
        )
        c.execute(
            "INSERT INTO adjudicaciones "
            "(licitacion_id, nombre, importe_adjudicado, fecha_adjudicacion, fecha_extraccion) "
            "VALUES ('SCOPE-1', 'Empresa A', 250000, '2026-01-02', CURRENT_TIMESTAMP)"
        )

    scope = metric_scope(cpv_prefix="72", ccaa="Madrid", desde="2026-01-01")

    assert scope.denominator_records == 1
    assert scope.denominator_amount_eur == 250000
    assert scope.sources == ["placsp"]
    assert scope.filter_versions == ["keywords-v1"]
    assert scope.model_versions == ["model-v2"]
    assert "no representa todo el mercado" in scope.universe
