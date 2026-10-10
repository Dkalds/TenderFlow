"""Tests de scheduler/jobs/daily_atom.py — el carril diario completo (ADR-012, ADR-033).

Lo que se fija es lo que el plano de cron del worker promete al sustituir a
``scrape-daily.yml``: la misma pasada, en el mismo orden y con el mismo
aislamiento entre fuentes. El test de paridad compara contra el YAML real, así
que mientras existan los dos no pueden divergir.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import textwrap
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from scheduler.jobs import daily_atom
from scheduler.jobs.daily_atom import CONECTORES, Conector

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scrape-daily.yml"


@dataclass(frozen=True)
class _Falso(Conector):
    """Conector de mentira: en vez de importar un módulo, ejecuta ``accion``."""

    accion: Callable[[], object] = field(default=lambda: None)

    def ejecutar(self) -> object:
        return self.accion()


def _falso(nombre: str, accion: Callable[[], object], presupuesto_s: float = 5) -> _Falso:
    return _Falso(nombre, f"tests.{nombre}", presupuesto_s, accion)  # type: ignore[arg-type]


@pytest.fixture
def orden(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Sustituye ingesta, cierre y healthcheck por apuntes en orden de llamada."""
    orden: list[str] = []

    def _ingesta(*, con_cierre: bool) -> dict[str, Any]:
        orden.append(f"ingesta(con_cierre={con_cierre})")
        return {"ingestion_result": {"status": "ok"}, "steps": {}}

    def _cierre(*, lane: str) -> dict[str, Any]:
        orden.append(f"cierre({lane})")
        return {"status": "ok", "steps": {}}

    def _salud() -> dict[str, Any]:
        orden.append("healthcheck")
        return {"status": "healthy"}

    monkeypatch.setattr("scheduler.pipeline_runs.run_daily_pipeline", _ingesta)
    monkeypatch.setattr("scheduler.pipeline_runs.run_post_ingestion_only", _cierre)
    monkeypatch.setattr("scheduler.healthcheck.comprobar_y_alertar", _salud)
    daily_atom._hilos.clear()
    return orden


# ── La pasada ───────────────────────────────────────────────────────────────


def test_la_pasada_sigue_el_orden_del_workflow(orden: list[str]) -> None:
    """Ingesta sin cierre → conectores → cierre → healthcheck.

    El cierre va detrás de los conectores para que la vista pública, los
    agregados y las alertas incluyan su corpus del ciclo.
    """
    conectores = [
        _falso("uno", lambda: orden.append("uno")),
        _falso("dos", lambda: orden.append("dos")),
    ]

    resumen = daily_atom.run(conectores=conectores)

    assert orden == [
        "ingesta(con_cierre=False)",
        "uno",
        "dos",
        "cierre(daily)",
        "healthcheck",
    ]
    assert resumen == {
        "ingesta": "ok",
        "conectores": {"uno": "success", "dos": "success"},
        "cierre": "ok",
        "healthcheck": "healthy",
    }


def test_un_conector_que_falla_no_para_a_los_demas_ni_al_cierre(orden: list[str]) -> None:
    def _revienta() -> None:
        raise RuntimeError("API caída")

    resumen = daily_atom.run(
        conectores=[_falso("roto", _revienta), _falso("sano", lambda: orden.append("sano"))]
    )

    assert resumen["conectores"] == {"roto": "error", "sano": "success"}
    assert orden[-3:] == ["sano", "cierre(daily)", "healthcheck"]


@pytest.mark.parametrize(
    ("resultado", "esperado"),
    [
        (SimpleNamespace(errores=3), "error"),  # ConnectorRunResult con errores
        (SimpleNamespace(errores=0), "success"),
        ({"errores": 2}, "error"),  # TACRC devuelve un dict
        ({"errores": 0}, "success"),
        (None, "success"),  # fuente apagada, o sin NIF vigilados
    ],
)
def test_el_estado_sale_de_los_errores_que_declara_la_pasada(
    orden: list[str], resultado: object, esperado: str
) -> None:
    """Es el código de salida de cada CLI: 1 en cuanto hay un error."""
    resumen = daily_atom.run(conectores=[_falso("fuente", lambda: resultado)])
    assert resumen["conectores"] == {"fuente": esperado}


def test_una_ingesta_que_lanza_no_impide_conectores_ni_cierre(
    orden: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``!cancelled()`` en el workflow: el resto corre, y el error se relanza al final."""

    def _ingesta_rota(*, con_cierre: bool) -> dict[str, Any]:
        raise RuntimeError("PLACSP: status inesperado")

    monkeypatch.setattr("scheduler.pipeline_runs.run_daily_pipeline", _ingesta_rota)

    with pytest.raises(RuntimeError, match="PLACSP"):
        daily_atom.run(conectores=[_falso("ted", lambda: orden.append("ted"))])

    assert orden == ["ted", "cierre(daily)", "healthcheck"]


def test_una_ingesta_con_status_de_error_no_se_relanza(
    orden: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """La pipeline ya avisó; relanzar duplicaría el correo y activaría el backoff."""
    monkeypatch.setattr(
        "scheduler.pipeline_runs.run_daily_pipeline",
        lambda *, con_cierre: {"ingestion_result": {"status": "error_fetch"}},
    )

    resumen = daily_atom.run(conectores=[])

    assert resumen["ingesta"] == "error_fetch"
    assert orden == ["cierre(daily)", "healthcheck"]


def test_el_healthcheck_corre_aunque_el_cierre_lance(
    orden: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _cierre_roto(*, lane: str) -> dict[str, Any]:
        raise RuntimeError("cierre roto")

    monkeypatch.setattr("scheduler.pipeline_runs.run_post_ingestion_only", _cierre_roto)

    with pytest.raises(RuntimeError, match="cierre roto"):
        daily_atom.run(conectores=[])

    assert orden[-1] == "healthcheck"


def test_un_healthcheck_roto_no_tapa_el_resultado(
    orden: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _salud_rota() -> dict[str, Any]:
        raise RuntimeError("sin BD")

    monkeypatch.setattr("scheduler.healthcheck.comprobar_y_alertar", _salud_rota)

    assert daily_atom.run(conectores=[])["healthcheck"] == "error"


# ── Presupuesto y solape ────────────────────────────────────────────────────


def test_un_conector_colgado_agota_su_presupuesto_y_el_cierre_no_lo_espera(
    orden: list[str],
) -> None:
    suelta = threading.Event()
    colgado = _falso("colgado", lambda: suelta.wait(5), presupuesto_s=0.05)
    try:
        resumen = daily_atom.run(conectores=[colgado])
        assert resumen["conectores"] == {"colgado": "timeout"}
        assert orden[-2:] == ["cierre(daily)", "healthcheck"]

        # La pasada siguiente no le apila otro hilo encima mientras siga vivo.
        resumen = daily_atom.run(conectores=[colgado])
        assert resumen["conectores"] == {"colgado": "skipped"}
    finally:
        suelta.set()
        daily_atom._hilos["colgado"].join(5)


def test_un_conector_que_termino_vuelve_a_correr(orden: list[str]) -> None:
    sano = _falso("sano", lambda: orden.append("sano"))
    daily_atom.run(conectores=[sano])
    daily_atom.run(conectores=[sano])
    assert orden.count("sano") == 2


# ── Paridad con scrape-daily.yml ────────────────────────────────────────────


def _steps_de_conectores() -> list[tuple[str, str, int]]:
    """``(id, módulo, presupuesto en s)`` de cada step ``python -m scraper.connectors.*``."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["scrape"]["steps"]
    prefijo = "python -m "
    return [
        (step["id"], step["run"].strip()[len(prefijo) :], int(step["timeout-minutes"]) * 60)
        for step in steps
        if str(step.get("run", "")).strip().startswith(f"{prefijo}scraper.connectors.")
    ]


def test_los_conectores_son_los_del_workflow() -> None:
    """Mismos conectores, mismo orden y mismo presupuesto que ``scrape-daily.yml``.

    Si alguien añade un conector al workflow y no aquí, el cutover lo apagaría
    en silencio: es exactamente el fallo que este job vino a corregir.
    """
    assert [(c.nombre, c.modulo, c.presupuesto_s) for c in CONECTORES] == _steps_de_conectores()


@pytest.mark.parametrize("conector", CONECTORES, ids=lambda c: c.nombre)
def test_cada_conector_expone_ejecutar_sin_argumentos_obligatorios(conector: Conector) -> None:
    ejecutar = importlib.import_module(conector.modulo).ejecutar
    obligatorios = [
        p
        for p in inspect.signature(ejecutar).parameters.values()
        if p.default is inspect.Parameter.empty and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
    ]
    assert obligatorios == []


@pytest.mark.parametrize("conector", CONECTORES, ids=lambda c: c.nombre)
def test_ejecutar_no_cierra_el_pool(conector: Conector) -> None:
    """El worker comparte el pool con la cola: ``close_pool()`` se la llevaría."""
    fuente = textwrap.dedent(inspect.getsource(importlib.import_module(conector.modulo).ejecutar))
    usados = {
        nodo.id if isinstance(nodo, ast.Name) else nodo.attr
        for nodo in ast.walk(ast.parse(fuente))
        if isinstance(nodo, ast.Name | ast.Attribute)
    } | {
        alias.name
        for nodo in ast.walk(ast.parse(fuente))
        if isinstance(nodo, ast.ImportFrom)
        for alias in nodo.names
    }
    assert not usados & {"close_pool", "init_db"}


# ── Pipeline canónica ───────────────────────────────────────────────────────


def test_run_continues_when_analytics_export_raises():
    """Si un paso post-ingesta falla, la pipeline canónica continúa."""
    from scheduler.pipeline_runs import _run_post_ingestion_steps

    with (
        patch(
            "scheduler.pipeline_runs._run_analytics_export",
            side_effect=RuntimeError("boom"),
        ),
        patch("scheduler.pipeline_runs._run_ml_scoring"),
        patch("scheduler.pipeline_runs._run_ml_tecnologias"),
        patch("scheduler.pipeline_runs._run_tech_signal_merge"),
        patch("scheduler.pipeline_runs._run_kpi_precompute"),
        patch("scheduler.pipeline_runs._run_aggregates_precompute"),
        patch("scheduler.pipeline_runs._run_watchlist_notify"),
        patch("scheduler.pipeline_runs._run_dlq_retry"),
        patch("scheduler.pipeline_runs._run_anomaly_checks"),
    ):
        results = _run_post_ingestion_steps()

    assert results["analytics_export"] == "error"
    assert results["kpi_precompute"] == "ok"
