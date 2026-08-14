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
# Invocado por .github/workflows/{ml-scoring,train-predictivos}.yml. La lógica
# vive aquí y no en un heredoc del YAML para que pase por ruff/mypy/tests como
# el resto del código.

# Estados de `score_predicciones_baja` que NO son fallo: "sin_abiertas" es el
# caso legítimo de no haber licitaciones abiertas que puntuar.
_SCORING_OK_STATUSES = frozenset({"ok", "sin_abiertas"})

# Estados de `entrenar()` que NO son fallo: sin histórico suficiente el modelo
# no se entrena y se sigue sirviendo el baseline (criterio de honestidad del
# RFC 20260611-2), que es distinto de que el entrenamiento reviente.
_RETRAIN_OK_STATUSES = frozenset({"ok", "datos_insuficientes"})

# Edad máxima tolerada de `predicciones_baja` en el step de verificación. El
# cron es diario, así que 26 h cubre la corrida anterior más el desfase típico
# del scheduler de Actions. Por encima de eso las filas son de una corrida que
# ya no existe: el upsert nunca purga, así que sin este control una tabla
# poblada hace semanas pasaba la verificación como si el batch hubiera escrito.
_MAX_EDAD_PREDICCIONES_HORAS = 26.0


def _edad_horas(valor: object) -> float | None:
    """Horas transcurridas desde ``valor`` (ISO-8601 UTC o ``datetime``).

    ``computed_at`` es TEXT en el esquema (lo escribe ``now_utc_iso()``), pero
    se acepta ``datetime`` por si algún backend lo devuelve ya tipado.
    """
    from datetime import UTC, datetime

    if isinstance(valor, datetime):
        instante = valor
    elif isinstance(valor, str) and valor:
        try:
            instante = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=UTC)
    return (datetime.now(UTC) - instante).total_seconds() / 3600.0


def run_scoring_cli() -> int:
    """Ejecuta el batch de scoring y falla si el modelo de baja no completó.

    Falla también cuando el serving quedó **degradado**: hay una versión activa
    en ``model_versions`` pero se sirvió el baseline porque su artefacto no se
    pudo resolver o su layout de features no cuadra. Eso no es el baseline
    honesto del RFC (ese caso es "no hay modelo activo"), es un modelo activo
    que no está llegando a producción, y hasta 2026-08 solo dejaba un
    ``log.warning`` en un job verde.
    """
    from db.database import init_db

    init_db()
    resumen = run_scoring()
    baja = resumen.get("baja", {})
    retencion = resumen.get("retencion", {})
    status = baja.get("status")

    log.info(
        "ml_scoring_cli_done",
        baja_status=status,
        baja_serving=baja.get("serving"),
        retencion_status=retencion.get("status"),
        drift=resumen.get("drift"),
        calibracion=resumen.get("calibracion"),
    )

    if status not in _SCORING_OK_STATUSES:
        log.error("ml_scoring_cli_failed", baja=baja)
        return 1

    degradados = {
        modelo: resultado["degradado"]
        for modelo, resultado in (("baja", baja), ("retencion", retencion))
        if resultado.get("degradado")
    }
    if degradados:
        from observability.alerts import notify

        log.error("ml_scoring_serving_degradado", degradados=degradados)
        notify(
            "error",
            "ML scoring degradado a baseline",
            "Hay una versión activa en model_versions cuyo artefacto no se pudo "
            "servir; las predicciones publicadas son el baseline histórico. "
            "Revisá que train-predictivos.yml haya subido el .pkl a la Release.",
            **degradados,
        )
        return 1
    return 0


def verify_predicciones_cli() -> int:
    """Verifica que ``predicciones_baja`` quedó materializada **y fresca**.

    Comprobar solo que la tabla tiene filas no verifica nada: el upsert de
    ``services/ml/scoring.py`` no purga, así que las filas de corridas
    anteriores sobreviven a un batch que no escribió ninguna.
    """
    from db.repositories.predicciones import PrediccionesRepository

    repo = PrediccionesRepository()
    estado = repo.estado("predicciones_baja")
    edad = _edad_horas(estado["ultimo_computed_at"])
    log.info(
        "ml_scoring_verify",
        tabla="predicciones_baja",
        filas=estado["filas"],
        ultimo_computed_at=estado["ultimo_computed_at"],
        edad_horas=round(edad, 2) if edad is not None else None,
    )
    # Informativo: `predicciones_retencion` puede estar legítimamente vacía
    # (sin vencimientos en la ventana), así que no condiciona el código de
    # salida, pero sin loguearla no se sabe si el segundo modelo escribió.
    retencion = repo.estado("predicciones_retencion")
    log.info(
        "ml_scoring_verify",
        tabla="predicciones_retencion",
        filas=retencion["filas"],
        ultimo_computed_at=retencion["ultimo_computed_at"],
    )

    if not estado["filas"]:
        log.error("ml_scoring_verify_empty", tabla="predicciones_baja")
        return 1
    if edad is None:
        log.error(
            "ml_scoring_verify_sin_timestamp",
            tabla="predicciones_baja",
            ultimo_computed_at=estado["ultimo_computed_at"],
        )
        return 1
    if edad > _MAX_EDAD_PREDICCIONES_HORAS:
        log.error(
            "ml_scoring_verify_stale",
            tabla="predicciones_baja",
            edad_horas=round(edad, 2),
            maximo_horas=_MAX_EDAD_PREDICCIONES_HORAS,
        )
        return 1
    return 0


def run_retrain_cli() -> int:
    """Re-entrena los modelos predictivos y publica sus artefactos.

    Invocado por ``.github/workflows/train-predictivos.yml``. Escribe en
    ``$GITHUB_OUTPUT`` la lista de ficheros que el workflow debe subir a la
    Release: sin ese paso el ``.pkl`` muere con el runner efímero y la fila de
    ``model_versions`` apunta a una ruta que ningún job posterior puede
    resolver (era el motivo por el que ``ml-scoring`` servía baseline para
    siempre).

    La activación de la versión nueva sigue siendo decisión humana vía
    ``db.model_registry`` salvo ``ML_PRED_AUTO_ACTIVATE``.
    """
    import os
    from pathlib import Path

    from db.database import init_db

    init_db()
    resultados = run_retrain()

    artefactos: list[str] = []
    fallidos: dict[str, Any] = {}
    for nombre, resumen in resultados.items():
        if resumen.get("status") not in _RETRAIN_OK_STATUSES:
            fallidos[nombre] = resumen
            continue
        ruta = resumen.get("path")
        if not ruta:
            continue
        pkl = Path(str(ruta))
        # El checksum co-ubicado lo escribe `save()`; viaja con el .pkl para
        # que `verify_model_integrity` pueda validar la carga en destino.
        artefactos.extend(str(p) for p in (pkl, pkl.with_suffix(".sha256")) if p.exists())

    log.info(
        "ml_retrain_cli_done",
        resultados={k: v.get("status") for k, v in resultados.items()},
        artefactos=artefactos,
    )

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write(f"artefactos={' '.join(artefactos)}\n")

    if fallidos:
        log.error("ml_retrain_cli_failed", fallidos=fallidos)
        return 1
    return 0


if __name__ == "__main__":
    import sys

    _cmd = sys.argv[1] if len(sys.argv) > 1 else "scoring"
    if _cmd == "scoring":
        sys.exit(run_scoring_cli())
    elif _cmd == "verify":
        sys.exit(verify_predicciones_cli())
    elif _cmd == "retrain":
        sys.exit(run_retrain_cli())
    else:
        log.error(
            "ml_predicciones_unknown_command",
            cmd=_cmd,
            usage="python -m scheduler.jobs.ml_predicciones [scoring|verify|retrain]",
        )
        sys.exit(2)
