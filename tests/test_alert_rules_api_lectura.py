"""Alertas del camino de LECTURA: 5xx de la API y latencia de lectura en Postgres.

Motivación
----------
Hasta 2026-08 ``observability/alert_rules.yml`` no vigilaba ninguna de las dos
cosas, y el hueco no era teórico: la única alerta ``critical`` era
``PgPoolHealthCheckFailed``, que mira ``up{job="tenderflow-api"}``. Un proceso
que devuelve 500 a todo sigue sirviendo ``/metrics``, así que ``up`` vale 1 y
esa alerta no puede dispararse. ``PgWriteLatencyHigh``, por su parte, sólo mira
escritura. La señal existía —``http_requests_total`` desglosado por status y el
histograma ``db_read_duration_seconds``— y se dibujaba en Grafana, pero ninguna
regla la leía.

Este test no revalida el YAML entero (eso es ``tests/test_alert_rules.py``):
fija que estas dos reglas concretas siguen ahí y que miran la métrica correcta,
que es lo único que impide que se borren "limpiando" el fichero.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_RULES = Path(__file__).resolve().parent.parent / "observability" / "alert_rules.yml"


def _regla(nombre: str) -> dict:
    data = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    for grupo in data.get("groups", []):
        for regla in grupo.get("rules", []):
            if regla.get("alert") == nombre:
                return regla
    pytest.fail(f"alert_rules.yml sin la alerta '{nombre}'")


def test_api_error_rate_high_mira_los_5xx_del_trafico_real() -> None:
    regla = _regla("ApiErrorRateHigh")
    expr = " ".join(regla["expr"].split())

    assert 'http_requests_total{status=~"5.."}' in expr, (
        "ApiErrorRateHigh tiene que contar 5xx de http_requests_total: es la métrica "
        "que emite prometheus-fastapi-instrumentator con should_group_status_codes=False"
    )
    # El denominador clampeado evita que un puñado de errores con tráfico casi
    # nulo dé un ratio de 1.0 y convierta la alerta en ruido permanente.
    assert "clamp_min" in expr, "ApiErrorRateHigh sin clamp_min: alertaría con tráfico ~0"
    assert "> 0.05" in expr, "El umbral acordado es 5% de 5xx"
    assert regla["for"] == "5m"
    assert regla["labels"]["severity"] == "critical", (
        "Una superficie que devuelve 500 no es un warning: es la caída que nadie vio"
    )


def test_pg_read_latency_high_observa_el_histograma_de_lectura() -> None:
    regla = _regla("PgReadLatencyHigh")
    expr = " ".join(regla["expr"].split())

    assert "db_read_duration_seconds_bucket" in expr, (
        "PgReadLatencyHigh tiene que leer el histograma que observa db/connection.py"
    )
    assert "histogram_quantile(0.99" in expr, "El acuerdo es p99, como PgWriteLatencyHigh"
    assert "> 5.0" in expr, "Umbral de lectura: 5s (más permisivo que el 1s de escritura)"
    assert regla["for"] == "10m"
    assert regla["labels"]["severity"] == "warning"


def test_ambas_alertas_llevan_summary_accionable() -> None:
    for nombre in ("ApiErrorRateHigh", "PgReadLatencyHigh"):
        anotaciones = _regla(nombre).get("annotations", {})
        assert anotaciones.get("summary"), f"{nombre} sin summary"
        assert anotaciones.get("description"), f"{nombre} sin description: nadie sabrá qué mirar"
