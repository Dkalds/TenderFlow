"""Severidad por paso del cierre de pasada (O0.2).

El 2026-09-01 el canary del catálogo NIM (``llm_models_canary``) tumbó el
cierre entero de ``scrape-daily`` durante días: los otros 14 pasos —incluido el
refresco de la superficie pública— terminaron ``ok`` y el job salía rojo igual.
Estos tests fijan qué pasos pueden hacer eso y cuáles no.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scheduler.pipeline_runs import (
    CANONICAL_STEPS,
    STEP_TIER,
    pasos_bloqueantes_fallidos,
    step_tier,
)

# Los cuatro pasos que informan sobre el sistema en vez de entregar algo de lo
# que dependa una superficie. Su fallo notifica por email y se ve en el
# resumen, pero no puede poner el job en rojo.
PASOS_ADVISORY = {
    "llm_models_canary",
    "anomaly_checks",
    "drift_checks",
    "sap_active_learning",
}

PASOS_BLOQUEANTES = {
    "ml_scoring",
    "ml_tecnologias",
    "tech_signal_merge",
    "llm_tech_labeling",
    "analytics_export",
    "kpi_precompute",
    "aggregates_precompute",
    "watchlist_notify",
    "digests",
    "dlq_retry",
    "retention_cleanup",
}

_TODOS_LOS_PASOS = {f"scheduler.pipeline_runs._run_{name}": None for name in CANONICAL_STEPS}


def _patch_todos(**overrides: object) -> object:
    """Parchea los 15 pasos canónicos; ``overrides`` sustituye alguno."""
    objetivos = {name.split(".")[-1]: MagicMock() for name in _TODOS_LOS_PASOS}
    for nombre, valor in overrides.items():
        objetivos[f"_run_{nombre}"] = valor
    return patch.multiple("scheduler.pipeline_runs", **objetivos)


# ---------------------------------------------------------------------------
# El mapa en sí
# ---------------------------------------------------------------------------


def test_todo_paso_canonico_declara_tier() -> None:
    """Mismo contrato que tener implementación ``_run_<name>``."""
    assert set(STEP_TIER) == set(CANONICAL_STEPS)


def test_el_reparto_de_severidad_es_el_declarado() -> None:
    """Fija los dos conjuntos: cambiarlos exige tocar este test a propósito."""
    advisory = {n for n, tier in STEP_TIER.items() if tier == "advisory"}
    bloqueantes = {n for n, tier in STEP_TIER.items() if tier == "bloqueante"}

    assert advisory == PASOS_ADVISORY
    assert bloqueantes == PASOS_BLOQUEANTES
    assert advisory | bloqueantes == set(CANONICAL_STEPS)


def test_step_tier_no_inventa_severidad_para_un_paso_desconocido() -> None:
    with pytest.raises(RuntimeError, match="sin tier declarado"):
        step_tier("un_paso_que_nadie_declaró")


def test_un_paso_sin_tier_no_se_ejecuta() -> None:
    """Un paso nuevo en CANONICAL_STEPS sin severidad aborta el cierre.

    Es deliberado: el default —cualquiera de los dos— sería una decisión
    tomada por omisión sobre si el job puede salir rojo.
    """
    from scheduler import pipeline_runs

    with (
        patch.object(pipeline_runs, "CANONICAL_STEPS", ["ml_scoring", "paso_sin_tier"]),
        patch.object(pipeline_runs, "_run_ml_scoring", MagicMock()),
        patch.object(pipeline_runs, "_run_paso_sin_tier", MagicMock(), create=True),
        pytest.raises(RuntimeError, match="sin tier declarado"),
    ):
        pipeline_runs._run_post_ingestion_steps()


# ---------------------------------------------------------------------------
# Efecto sobre el resumen y sobre el exit code
# ---------------------------------------------------------------------------


def test_fallo_advisory_sale_como_error_en_el_resumen_pero_no_es_bloqueante() -> None:
    from scheduler.pipeline_runs import _run_post_ingestion_steps

    with (
        _patch_todos(llm_models_canary=MagicMock(side_effect=RuntimeError("catálogo"))),
        patch("scheduler.pipeline_runs._notify_step_failure") as notificar,
    ):
        results = _run_post_ingestion_steps()

    # Sigue viéndose como error en `cierre_pasada_completado`…
    assert results["llm_models_canary"] == "error"
    # …y sigue mandando su email.
    notificar.assert_called_once()
    assert notificar.call_args[0][0] == "llm_models_canary"
    # Pero no entra en los fallos que ponen el job en rojo.
    assert pasos_bloqueantes_fallidos(results) == []


def test_fallo_bloqueante_si_cuenta() -> None:
    from scheduler.pipeline_runs import _run_post_ingestion_steps

    with (
        _patch_todos(kpi_precompute=MagicMock(side_effect=RuntimeError("boom"))),
        patch("scheduler.pipeline_runs._notify_step_failure"),
    ):
        results = _run_post_ingestion_steps()

    assert results["kpi_precompute"] == "error"
    assert pasos_bloqueantes_fallidos(results) == ["kpi_precompute"]


def test_un_paso_desconocido_en_el_resumen_cuenta_como_bloqueante() -> None:
    """Si alguien mete un paso por fuera del contrato, su fallo se ve."""
    assert pasos_bloqueantes_fallidos({"paso_no_declarado": "error"}) == ["paso_no_declarado"]


def test_skipped_no_es_un_fallo() -> None:
    assert pasos_bloqueantes_fallidos({"ml_scoring": "skipped"}) == []


def test_fallo_advisory_no_cambia_el_exit_code() -> None:
    """El caso del 2026-09-01, end to end sobre el exit code del proceso."""
    from scheduler.run_update import _apply_step_failures

    steps = {name: "ok" for name in CANONICAL_STEPS}
    steps["llm_models_canary"] = "error"

    assert _apply_step_failures({"steps": steps}, 0, MagicMock()) == 0


def test_fallo_bloqueante_si_eleva_el_exit_code() -> None:
    from scheduler.run_update import _apply_step_failures

    steps = {name: "ok" for name in CANONICAL_STEPS}
    steps["aggregates_precompute"] = "error"

    assert _apply_step_failures({"steps": steps}, 0, MagicMock()) == 1


def test_un_paso_skipped_no_pone_el_job_en_rojo() -> None:
    """Regresión de la comparación anterior (``status != "ok"``).

    Los pasos periódicos fuera de su ventana, un feature flag apagado o un
    precompute sin modelo devuelven ``skipped``; con la comparación vieja cada
    uno de ellos habría hecho fallar el run.
    """
    from scheduler.run_update import _apply_step_failures

    steps = {name: "ok" for name in CANONICAL_STEPS}
    steps["retention_cleanup"] = "skipped"
    steps["drift_checks"] = "skipped"
    steps["ml_scoring"] = "skipped"

    assert _apply_step_failures({"steps": steps}, 0, MagicMock()) == 0


def test_el_exit_code_de_la_ingesta_nunca_se_baja() -> None:
    from scheduler.run_update import _apply_step_failures

    steps = {name: "ok" for name in CANONICAL_STEPS}

    assert _apply_step_failures({"steps": steps}, 1, MagicMock()) == 1


# ---------------------------------------------------------------------------
# O0.6 — ml_scoring deja de reportar "ok" cuando no hay modelo
# ---------------------------------------------------------------------------


def test_ml_scoring_reporta_skipped_si_el_precompute_no_encuentra_modelo() -> None:
    """La clave leída es ``skipped_no_model`` (contrato con scraper/ml_training)."""
    from scheduler.pipeline_runs import _run_ml_scoring

    with patch(
        "scraper.ml_training.precompute_ml_proba",
        return_value={"updated": 0, "skipped_no_model": True},
    ):
        assert _run_ml_scoring() == "skipped"


def test_ml_scoring_reporta_ok_cuando_si_hay_modelo() -> None:
    from scheduler.pipeline_runs import _run_ml_scoring

    with patch(
        "scraper.ml_training.precompute_ml_proba",
        return_value={"updated": 42, "skipped_no_model": False},
    ):
        assert _run_ml_scoring() == "ok"


def test_ml_tecnologias_reporta_skipped_sin_modelo() -> None:
    from scheduler.pipeline_runs import _run_ml_tecnologias

    with (
        patch("config.settings.ML_TECH_ENABLED", True, create=True),
        patch(
            "scraper.ml_training.precompute_ml_tecnologias",
            return_value={"updated": 0, "scores_inserted": 0, "skipped_no_model": True},
        ),
    ):
        assert _run_ml_tecnologias() == "skipped"


def test_ml_tecnologias_reporta_skipped_con_el_flag_apagado() -> None:
    from scheduler.pipeline_runs import _run_ml_tecnologias

    with patch("config.settings.ML_TECH_ENABLED", False, create=True):
        assert _run_ml_tecnologias() == "skipped"


def test_el_resumen_del_cierre_propaga_el_skipped_de_ml_scoring() -> None:
    """Es el punto del ítem: que el estado se VEA en el resumen de la pasada."""
    from scheduler.pipeline_runs import _run_post_ingestion_steps

    with _patch_todos(ml_scoring=MagicMock(return_value="skipped")):
        results = _run_post_ingestion_steps()

    assert results["ml_scoring"] == "skipped"
