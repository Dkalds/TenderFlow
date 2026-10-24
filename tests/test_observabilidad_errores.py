"""Los errores capturados en los módulos calientes cuentan y pueden alertar.

``observability/errores.py`` da a cada módulo un ``<modulo>_errores_total{paso}``
y un evento ``error_capturado:<modulo>:<paso>`` en ``ops_events``. Aquí se
comprueba el helper, que el umbral es el mismo en Prometheus y en el
healthcheck, y que cada camino instrumentado incrementa su contador.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

yaml = pytest.importorskip("yaml")
prometheus_client = pytest.importorskip("prometheus_client")

_RULES = Path(__file__).resolve().parent.parent / "observability" / "alert_rules.yml"


def _valor(metrica: str, paso: str) -> float:
    valor = prometheus_client.REGISTRY.get_sample_value(metrica, {"paso": paso})
    return float(valor or 0.0)


def _eventos(prefijo: str) -> list[dict[str, Any]]:
    import observability.ops_events as oe

    with oe._lock:
        return [e for e in oe._buffer if str(e["event_type"]).startswith(prefijo)]


# ── El helper ────────────────────────────────────────────────────────────────


def test_el_contador_suma_por_paso_y_deja_el_evento() -> None:
    from observability.errores import ContadorDeErrores
    from observability.runtime_metrics import db_connection_errores_total

    contar = ContadorDeErrores("db_connection", db_connection_errores_total)
    antes = _valor("db_connection_errores_total", "prueba_helper")

    contar("prueba_helper")

    assert _valor("db_connection_errores_total", "prueba_helper") == antes + 1
    eventos = _eventos("error_capturado:db_connection:prueba_helper")
    assert len(eventos) == 1
    assert eventos[0]["value"] == 1.0


def test_los_eventos_tienen_tope_por_paso_pero_el_contador_no() -> None:
    """Diez mil documentos fallando igual no son diez mil filas de ops_events."""
    from observability import errores
    from observability.runtime_metrics import db_connection_errores_total

    contar = errores.ContadorDeErrores("db_connection", db_connection_errores_total)
    antes = _valor("db_connection_errores_total", "prueba_tope")
    veces = errores._TOPE_EVENTOS_POR_PASO + 7

    for _ in range(veces):
        contar("prueba_tope")

    assert _valor("db_connection_errores_total", "prueba_tope") == antes + veces
    eventos = _eventos("error_capturado:db_connection:prueba_tope")
    assert len(eventos) == errores._TOPE_EVENTOS_POR_PASO
    assert errores._TOPE_EVENTOS_POR_PASO > errores.UMBRAL_REPETIDO


def test_errores_repetidos_aplica_el_umbral_y_quita_el_prefijo() -> None:
    from observability.errores import UMBRAL_REPETIDO, errores_repetidos

    conteos = {
        "write_slow": 99,
        "error_capturado:scraper_conector:dedupe": UMBRAL_REPETIDO,
        "error_capturado:pipeline_runs:avisos_competidores": UMBRAL_REPETIDO - 1,
    }

    assert errores_repetidos(conteos) == {"scraper_conector:dedupe": UMBRAL_REPETIDO}


# ── Las reglas de Prometheus ─────────────────────────────────────────────────


def _reglas_del_grupo(nombre: str) -> dict[str, dict[str, Any]]:
    data = yaml.safe_load(_RULES.read_text(encoding="utf-8"))
    for group in data["groups"]:
        if group["name"] == nombre:
            return {r["alert"]: r for r in group["rules"]}
    raise AssertionError(f"alert_rules.yml sin el grupo {nombre}")


def test_solo_hay_regla_para_los_contadores_que_la_api_emite() -> None:
    """Los de los procesos efímeros serían alertas muertas: los vigila el healthcheck."""
    reglas = _reglas_del_grupo("errores_capturados")
    exprs = " ".join(r["expr"] for r in reglas.values())

    assert set(reglas) == {"DbConnectionErroresCapturados", "LlmClientErroresCapturados"}
    assert "db_connection_errores_total" in exprs
    assert "llm_client_errores_total" in exprs
    for efimero in (
        "scraper_conector_errores_total",
        "pipeline_runs_errores_total",
        "documentos_embeddings_errores_total",
    ):
        assert efimero not in exprs


@pytest.mark.parametrize("alerta", ["DbConnectionErroresCapturados", "LlmClientErroresCapturados"])
def test_la_regla_usa_el_umbral_del_codigo(alerta: str) -> None:
    """El umbral vive en dos sitios (Python y la regla); si cambia uno, mienten."""
    from observability.errores import UMBRAL_REPETIDO

    regla = _reglas_del_grupo("errores_capturados")[alerta]
    assert regla["expr"].rstrip().endswith(f">= {UMBRAL_REPETIDO}")
    assert "sum by (paso)" in regla["expr"]
    assert regla["annotations"]["summary"]
