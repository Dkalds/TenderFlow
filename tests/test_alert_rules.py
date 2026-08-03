"""Valida que las reglas de alerta de Prometheus son coherentes (ADR-004).

Los tripwires de persistencia (``observability/alert_rules.yml``) son la
materialización de los umbrales de ADR-004. Este test garantiza que el YAML es
parseable, que está cableado en ``prometheus.yml`` vía ``rule_files``, y que las
alertas documentadas siguen presentes — para que no se borren por accidente al
editar la config de observabilidad.

``SQLiteBusyErrorsHigh`` y ``DBWriteLatencyHigh`` (nombres pre-ADR-016) se
retiraron a propósito en 2026-08: la primera monitoreaba
``sqlite_busy_errors_total``, un contador que ya no existe (ADR-021,
Postgres-only) y que ``PgPoolAcquireTimeoutHigh`` cubre de forma nativa para
Postgres; la segunda quedó duplicada por ``PgWriteLatencyHigh`` (mismo
histograma ``db_write_duration_seconds``, umbral ajustado). No van en
``_EXPECTED_ALERTS``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_ROOT = Path(__file__).resolve().parent.parent
_RULES = _ROOT / "observability" / "alert_rules.yml"
_PROM = _ROOT / "observability" / "prometheus.yml"

_EXPECTED_ALERTS = {
    "PgWriteLatencyHigh",
    "PgConcurrentWritersHigh",
}


def _all_alert_names() -> set[str]:
    data = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    names: set[str] = set()
    for group in data.get("groups", []):
        for rule in group.get("rules", []):
            if "alert" in rule:
                names.add(rule["alert"])
    return names


def test_alert_rules_yaml_parses() -> None:
    data = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    assert data.get("groups"), "alert_rules.yml sin grupos"


def test_persistence_tripwires_present() -> None:
    assert _all_alert_names() >= _EXPECTED_ALERTS, (
        "Faltan tripwires de persistencia (ADR-004) en alert_rules.yml: "
        f"{_EXPECTED_ALERTS - _all_alert_names()}"
    )


def test_every_alert_has_expr_and_annotations() -> None:
    data = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    for group in data["groups"]:
        for rule in group.get("rules", []):
            if "alert" not in rule:
                continue
            name = rule["alert"]
            assert rule.get("expr"), f"{name} sin expr"
            assert rule.get("annotations", {}).get("summary"), f"{name} sin summary"


def test_rules_wired_into_prometheus_config() -> None:
    prom = yaml.safe_load(_PROM.read_text(encoding="utf-8"))
    rule_files = prom.get("rule_files", [])
    assert any("alert_rules.yml" in rf for rf in rule_files), (
        "prometheus.yml no referencia alert_rules.yml en rule_files"
    )
