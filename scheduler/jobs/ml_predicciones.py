"""Jobs de modelos predictivos (Fase 6, RFC 20260611-2).

- ``run_scoring``: batch nocturno que materializa ``predicciones_baja`` para
  licitaciones abiertas (serving = lectura de tabla, patrón ``ml_proba``).
- ``run_retrain``: re-entrenamiento mensual; registra la versión nueva en
  ``model_versions`` SIN activar (salvo ``ML_PRED_AUTO_ACTIVATE`` y criterios
  del RFC cumplidos). La activación es decisión humana vía model_registry.
"""

from __future__ import annotations

from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)


def run_scoring() -> dict[str, Any]:
    from services.ml.calibration import comprobar_calibracion_baja
    from services.ml.drift import comprobar_drift_baja
    from services.ml.scoring import score_predicciones_baja, score_predicciones_retencion

    baja = score_predicciones_baja()
    retencion = score_predicciones_retencion()
    drift = comprobar_drift_baja()
    calibracion = comprobar_calibracion_baja()
    return {"baja": baja, "retencion": retencion, "drift": drift, "calibracion": calibracion}


def run_retrain() -> dict[str, Any]:
    from services.ml.baja_model import entrenar as entrenar_baja
    from services.ml.retencion_model import entrenar as entrenar_retencion

    resultados = {"baja": entrenar_baja(), "retencion": entrenar_retencion()}
    for nombre, resumen in resultados.items():
        if resumen.get("status") == "ok" and not resumen.get("activado"):
            log.info(
                "ml_retrain_pending_activation",
                modelo=nombre,
                version=resumen.get("version"),
                cumple_criterios=resumen.get("cumple_criterios"),
            )
    return resultados


# ── CLI ───────────────────────────────────────────────────────────────────────
#
# Invocado por .github/workflows/ml-scoring.yml. La lógica vive aquí y no en un
# heredoc del YAML para que pase por ruff/mypy/tests como el resto del código.

# Estados de `score_predicciones_baja` que NO son fallo: "sin_abiertas" es el
# caso legítimo de no haber licitaciones abiertas que puntuar.
_SCORING_OK_STATUSES = frozenset({"ok", "sin_abiertas"})


def run_scoring_cli() -> int:
    """Ejecuta el batch de scoring y falla si el modelo de baja no completó."""
    from db.database import init_db

    init_db()
    resumen = run_scoring()
    baja = resumen.get("baja", {})
    status = baja.get("status")

    log.info(
        "ml_scoring_cli_done",
        baja_status=status,
        retencion_status=resumen.get("retencion", {}).get("status"),
        drift=resumen.get("drift"),
        calibracion=resumen.get("calibracion"),
    )

    if status not in _SCORING_OK_STATUSES:
        log.error("ml_scoring_cli_failed", baja=baja)
        return 1
    return 0


def verify_predicciones_cli() -> int:
    """Verifica que ``predicciones_baja`` quedó materializada tras el scoring."""
    from db.repositories.predicciones import PrediccionesRepository

    estado = PrediccionesRepository().estado("predicciones_baja")
    log.info(
        "ml_scoring_verify",
        tabla="predicciones_baja",
        filas=estado["filas"],
        ultimo_computed_at=estado["ultimo_computed_at"],
    )
    if not estado["filas"]:
        log.error("ml_scoring_verify_empty", tabla="predicciones_baja")
        return 1
    return 0


if __name__ == "__main__":
    import sys

    _cmd = sys.argv[1] if len(sys.argv) > 1 else "scoring"
    if _cmd == "scoring":
        sys.exit(run_scoring_cli())
    elif _cmd == "verify":
        sys.exit(verify_predicciones_cli())
    else:
        log.error(
            "ml_predicciones_unknown_command",
            cmd=_cmd,
            usage="python -m scheduler.jobs.ml_predicciones [scoring|verify]",
        )
        sys.exit(2)
