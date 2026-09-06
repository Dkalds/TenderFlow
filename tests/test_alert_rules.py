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


# ── C3.3: los dos SLO de latencia dejan de ser una frase sin alerta ──────────

_ALERTAS_DE_LATENCIA = {
    "ApiLatencyP99High": "6",
    "PublicSurfaceSlow": "3",
}


def test_existen_las_alertas_de_latencia() -> None:
    """SLO 3 y SLO 6 tenían «Alerta: No implementada» en su propia ficha."""
    faltan = sorted(_ALERTAS_DE_LATENCIA.keys() - _all_alert_names())
    assert not faltan, f"faltan las reglas de latencia de C3.3: {faltan}"


def _regla(nombre: str) -> dict:
    data = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    for group in data.get("groups", []):
        for rule in group.get("rules", []):
            if rule.get("alert") == nombre:
                return dict(rule)
    raise AssertionError(f"regla {nombre} no encontrada")


@pytest.mark.parametrize("nombre", sorted(_ALERTAS_DE_LATENCIA))
def test_la_alerta_de_latencia_espera_dos_ventanas(nombre: str) -> None:
    """`for: 10m` sobre un rate de 5m: dos ventanas completas.

    Sin `for`, un pico de despliegue o un backfill puntual despertaría a
    alguien. Con menos de 10m, una sola ventana basta y vuelve a ser ruido.
    """
    assert _regla(nombre).get("for") == "10m"


@pytest.mark.parametrize("nombre", sorted(_ALERTAS_DE_LATENCIA))
def test_la_alerta_de_latencia_declara_su_slo(nombre: str) -> None:
    etiquetas = _regla(nombre).get("labels", {})
    assert etiquetas.get("slo") == _ALERTAS_DE_LATENCIA[nombre], (
        f"{nombre} debe declarar a qué SLO de docs/sli-slo.md responde"
    )


@pytest.mark.parametrize("nombre", sorted(_ALERTAS_DE_LATENCIA))
def test_la_alerta_de_latencia_mide_la_metrica_que_dice(nombre: str) -> None:
    """Sobre `http_request_duration_seconds`, que es la que emite la API.

    Una regla sobre una métrica que nadie emite es una alerta muerta: da
    impresión de cobertura y no puede dispararse nunca. Es el mismo error que
    la cabecera de este fichero documenta para la frescura del dato.
    """
    expr = _regla(nombre)["expr"]
    assert "http_request_duration_seconds_bucket" in expr
    assert "histogram_quantile" in expr


def test_la_superficie_publica_se_filtra_por_handler() -> None:
    """`PublicSurfaceSlow` tiene que mirar solo `/api/v1/publico/*`.

    Sin el filtro sería una copia con otro umbral de `ApiLatencyP99High`, y las
    dos se dispararían juntas sin distinguir qué se degradó.
    """
    expr = _regla("PublicSurfaceSlow")["expr"]
    assert "/api/v1/publico" in expr
