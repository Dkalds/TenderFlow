"""Calibración del modelo de baja en producción (closed-loop).

``drift.py`` cubre el drift de *features* (PSI entrada). Falta cerrar el loop
sobre el *resultado*: ¿el intervalo p10-p90 que servimos cubre de verdad las
bajas que luego se observan? Un intervalo "80%" bien calibrado debe contener
~80% de las bajas reales; una cobertura muy por debajo significa que el modelo
es sobreconfiado y los intervalos engañan al usuario.

Las predicciones se materializan mientras la licitación está *abierta*
(``score_predicciones_baja`` solo puntúa abiertas) y la fila persiste en
``predicciones_baja``. Cuando esa licitación se adjudica, ya tenemos par
predicción↔realidad sin guardar nada nuevo: este monitor lo explota.

Mismo contrato que el monitor de drift: computa, loguea structured y alerta
por el canal existente; fail-open (nunca bloquea el scoring).

El SQL vive en ``db.repositories.ml_dataset`` (ADR-022) y comparte la regla de
denominador con el target de entrenamiento: cobertura y MAE se miden sobre la
misma magnitud que el modelo aprende.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from db.repositories.ml_dataset import MlDatasetRepository
from observability.logging import get_logger

log = get_logger(__name__)

# Cobertura nominal del intervalo servido (p10..p90 = 80%).
_COBERTURA_NOMINAL = 0.80
# Mínimo de pares resueltos para que la cobertura sea informativa.
_MIN_EVALUADAS = 30
# La cobertura empírica puede degradarse hasta estos puntos antes de alertar.
_COBERTURA_WARN = 0.65  # < nominal - 0.15
_COBERTURA_CRIT = 0.50  # < nominal - 0.30


def comprobar_calibracion_baja() -> dict[str, Any]:
    """Cobertura empírica del intervalo p10-p90 vs bajas realizadas.

    Devuelve cobertura (fracción dentro de [p10, p90]), MAE de p50 y sesgo
    (error medio firmado: positivo => el modelo infraestima la baja real).
    Fail-open: cualquier error se loguea y no propaga.
    """
    try:
        # La baja realizada se calcula con la MISMA regla de denominador que el
        # target de entrenamiento (``db.repositories.ml_dataset``): es lo que
        # hace comparable esta cobertura empírica con la nominal. Mientras esta
        # query dividía entre ``l.importe`` y el entrenamiento usaba el
        # presupuesto del lote, se medía una magnitud distinta de la entrenada y
        # la cobertura no significaba nada.
        medido = MlDatasetRepository().calibracion_baja()

        n = int(medido["n"])
        if n < _MIN_EVALUADAS or medido["cobertura"] is None:
            log.info("ml_calibracion_skip", reason="pocas_evaluadas", n=n)
            return {"status": "sin_datos", "n": n}

        cobertura = round(float(medido["cobertura"]), 4)
        mae = round(float(medido["mae"] or 0.0), 4)
        sesgo = round(float(medido["sesgo"] or 0.0), 4)

        if cobertura < _COBERTURA_CRIT:
            severity = "crit"
        elif cobertura < _COBERTURA_WARN:
            severity = "warn"
        else:
            severity = "ok"

        resultado = {
            "status": severity,
            "n": n,
            "cobertura": cobertura,
            "cobertura_nominal": _COBERTURA_NOMINAL,
            "mae_p50": mae,
            "sesgo_p50": sesgo,
        }

        if severity != "ok":
            log.warning("ml_calibracion_degradada", **resultado)
            try:
                from observability.alerts import notify

                notify(
                    "warn" if severity == "warn" else "error",
                    f"Calibración del modelo de baja degradada "
                    f"(cobertura {cobertura:.0%} vs {_COBERTURA_NOMINAL:.0%} nominal)",
                    f"n={n} mae_p50={mae} sesgo_p50={sesgo}",
                )
            except Exception:  # canal de alertas opcional
                log.debug("ml_calibracion_alert_channel_unavailable")
        else:
            log.info("ml_calibracion_ok", **resultado)

        return resultado
    except Exception as e:  # fail-open como el monitor de drift
        log.warning("ml_calibracion_check_failed", error=str(e))
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# DTO para GET /predicciones/calibracion (plan Pliegos+RAG, F11)
# ---------------------------------------------------------------------------


class CalibracionBajaDTO(BaseModel):
    """Vista simplificada de 3 estados para la UI (calidad-datos).

    ``comprobar_calibracion_baja()`` distingue 5 estados internos
    (``ok|warn|crit|sin_datos|error``) para logging/alertas; el contrato
    público solo necesita "todo bien / degradado / no hay datos aún" — el
    matiz warn-vs-crit es ruido para el usuario, no una decisión que tome.
    """

    estado: Literal["ok", "degradado", "insuficiente"]
    cobertura: float | None = None
    cobertura_nominal: float = _COBERTURA_NOMINAL
    mae_p50: float | None = None
    sesgo_p50: float | None = None
    n_evaluadas: int = 0


def calibracion_baja_dto() -> CalibracionBajaDTO:
    """Adapta ``comprobar_calibracion_baja()`` al contrato público de 3 estados."""
    raw = comprobar_calibracion_baja()
    status = raw.get("status")
    n = int(raw.get("n", 0))

    if status == "ok":
        estado: Literal["ok", "degradado", "insuficiente"] = "ok"
    elif status in ("warn", "crit"):
        estado = "degradado"
    else:  # "sin_datos" | "error" -- ambos son "no hay señal fiable todavía"
        estado = "insuficiente"

    return CalibracionBajaDTO(
        estado=estado,
        cobertura=raw.get("cobertura"),
        mae_p50=raw.get("mae_p50"),
        sesgo_p50=raw.get("sesgo_p50"),
        n_evaluadas=n,
    )
