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

Dos granularidades, un solo default
-----------------------------------
Desde v86 el monitor sabe medir a dos granularidades: por **expediente** (lo
que se sirve hoy) y por **lote** (la unidad sobre la que se puja de verdad).
La segunda existe porque sustituir el modelo agregado por uno por lote está
condicionado a comprobar antes que su ``mae_p50`` mejora -- y esa comprobación
necesitaba una regla para medirlo. :func:`comparar_mae_p50` la ejecuta.

Lo que **no** hace este módulo es decidir: ``granularidad="expediente"`` sigue
siendo el default en todas las entradas (job nocturno, endpoint, DTO), y solo
esa granularidad alerta. Alertar por la granularidad que no se sirve sería
despertar a alguien por un número que ningún usuario ve.
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

Granularidad = Literal["expediente", "lote"]

# Granularidad servida hoy. Cambiarla es exactamente la decisión que el backlog
# condiciona a que `comparar_mae_p50()` muestre mejora: no se toca sin esa
# medida sobre datos reales.
GRANULARIDAD_SERVIDA: Granularidad = "expediente"


def comprobar_calibracion_baja(granularidad: Granularidad = GRANULARIDAD_SERVIDA) -> dict[str, Any]:
    """Cobertura empírica del intervalo p10-p90 vs bajas realizadas.

    Devuelve cobertura (fracción dentro de [p10, p90]), MAE de p50 y sesgo
    (error medio firmado: positivo => el modelo infraestima la baja real).
    Fail-open: cualquier error se loguea y no propaga.

    Args:
        granularidad: ``"expediente"`` (default, lo que se sirve) o ``"lote"``.
            Con ``"lote"`` cada lote adjudicado es un par y el resultado añade
            ``n_prediccion_por_lote`` -- cuántos de esos pares se evaluaron
            contra una predicción propia del lote en vez de contra la del
            expediente. Mientras el serving sea agregado ese contador es 0 y lo
            medido es "el modelo actual visto a granularidad de lote".
    """
    try:
        # La baja realizada se calcula con la MISMA regla de denominador que el
        # target de entrenamiento (``db.repositories.ml_dataset``): es lo que
        # hace comparable esta cobertura empírica con la nominal. Mientras esta
        # query dividía entre ``l.importe`` y el entrenamiento usaba el
        # presupuesto del lote, se medía una magnitud distinta de la entrenada y
        # la cobertura no significaba nada.
        repo = MlDatasetRepository()
        medido = (
            repo.calibracion_baja()
            if granularidad == "expediente"
            else repo.calibracion_baja_por_lote()
        )

        n = int(medido["n"])
        if n < _MIN_EVALUADAS or medido["cobertura"] is None:
            log.info(
                "ml_calibracion_skip", reason="pocas_evaluadas", n=n, granularidad=granularidad
            )
            return {"status": "sin_datos", "n": n, "granularidad": granularidad}

        cobertura = round(float(medido["cobertura"]), 4)
        mae = round(float(medido["mae"] or 0.0), 4)
        sesgo = round(float(medido["sesgo"] or 0.0), 4)

        if cobertura < _COBERTURA_CRIT:
            severity = "crit"
        elif cobertura < _COBERTURA_WARN:
            severity = "warn"
        else:
            severity = "ok"

        resultado: dict[str, Any] = {
            "status": severity,
            "n": n,
            "cobertura": cobertura,
            "cobertura_nominal": _COBERTURA_NOMINAL,
            "mae_p50": mae,
            "sesgo_p50": sesgo,
            "granularidad": granularidad,
        }
        if granularidad == "lote":
            resultado["n_prediccion_por_lote"] = int(medido.get("n_prediccion_por_lote") or 0)

        # Solo la granularidad servida alerta: una degradación medida por lote
        # describe un modelo que nadie está viendo todavía, y una alerta que no
        # corresponde a nada que el usuario vea es ruido de guardia.
        if severity != "ok" and granularidad == GRANULARIDAD_SERVIDA:
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
        elif severity != "ok":
            log.info("ml_calibracion_degradada_no_servida", **resultado)
        else:
            log.info("ml_calibracion_ok", **resultado)

        return resultado
    except Exception as e:  # fail-open como el monitor de drift
        log.warning("ml_calibracion_check_failed", error=str(e), granularidad=granularidad)
        return {"status": "error", "error": str(e), "granularidad": granularidad}


def comparar_mae_p50() -> dict[str, Any]:
    """Mide ``mae_p50`` a las dos granularidades y devuelve la comparación.

    Es el gate que el backlog impone antes de sustituir el modelo agregado por
    uno por lote: *si no mejora, se documenta y se queda el agregado*. Esta
    función **no sustituye nada** -- ni cambia :data:`GRANULARIDAD_SERVIDA`, ni
    escribe, ni activa versiones. Solo produce el número que hace falta para
    tomar la decisión, que sigue siendo humana.

    ``delta_mae_p50`` es ``lote - expediente``: negativo significa que medir por
    lote da menos error. ``comparable`` es False cuando alguna de las dos
    granularidades no reunió ``_MIN_EVALUADAS`` pares o falló -- comparar un MAE
    con un ``None`` y quedarse con el que existe es como se justifican los
    cambios que empeoran las cosas.
    """
    expediente = comprobar_calibracion_baja("expediente")
    lote = comprobar_calibracion_baja("lote")

    mae_exp = expediente.get("mae_p50")
    mae_lote = lote.get("mae_p50")

    # `mae_p50` solo existe cuando la granularidad reunió pares suficientes;
    # en "sin_datos"/"error" la clave no está y el delta no se puede calcular.
    delta: float | None = (
        round(mae_lote - mae_exp, 4)
        if isinstance(mae_exp, float) and isinstance(mae_lote, float)
        else None
    )
    comparable = delta is not None
    mejora = delta < 0 if delta is not None else None

    if not comparable:
        recomendacion = "sin_datos_suficientes"
    elif mejora:
        recomendacion = "candidato_a_sustituir"
    else:
        recomendacion = "mantener_agregado"

    resultado = {
        "expediente": expediente,
        "lote": lote,
        "comparable": comparable,
        "delta_mae_p50": delta,
        "mejora_lote": mejora,
        # Incluso "candidato_a_sustituir" es una lectura, no un cambio: el
        # switch de granularidad toca el esquema (v86 documenta el DROP de la
        # PK y el ON CONFLICT de scoring.py) y no se hace desde un monitor.
        "recomendacion": recomendacion,
    }
    log.info(
        "ml_calibracion_comparacion_granularidad",
        comparable=comparable,
        delta_mae_p50=delta,
        recomendacion=recomendacion,
        n_expediente=expediente.get("n"),
        n_lote=lote.get("n"),
        n_prediccion_por_lote=lote.get("n_prediccion_por_lote"),
    )
    return resultado


# ---------------------------------------------------------------------------
# DTO para GET /predicciones/calibracion (plan Pliegos+RAG, F11)
# ---------------------------------------------------------------------------


_EstadoPublico = Literal["ok", "degradado", "insuficiente"]


def _estado_publico(status: object) -> _EstadoPublico:
    if status == "ok":
        return "ok"
    if status in ("warn", "crit"):
        return "degradado"
    # "sin_datos" | "error" -- ambos son "no hay señal fiable todavía"
    return "insuficiente"


class CalibracionPorLoteDTO(BaseModel):
    """Calibración medida sobre lotes en vez de sobre expedientes.

    Bloque **de diagnóstico**, no la cifra que se sirve: mientras
    ``predicciones_baja`` almacene una predicción por expediente,
    ``n_prediccion_por_lote`` vale 0 y esto es el modelo agregado evaluado a
    granularidad de lote. Ese número es precisamente el baseline contra el que
    hay que comparar un futuro modelo por lote, y por eso viaja en el contrato:
    sin él, un lector no puede distinguir "el modelo por lote va mejor" de "aún
    no hay modelo por lote".
    """

    estado: _EstadoPublico
    cobertura: float | None = None
    mae_p50: float | None = None
    sesgo_p50: float | None = None
    n_evaluadas: int = 0
    n_prediccion_por_lote: int = 0


class CalibracionBajaDTO(BaseModel):
    """Vista simplificada de 3 estados para la UI (calidad-datos).

    ``comprobar_calibracion_baja()`` distingue 5 estados internos
    (``ok|warn|crit|sin_datos|error``) para logging/alertas; el contrato
    público solo necesita "todo bien / degradado / no hay datos aún" — el
    matiz warn-vs-crit es ruido para el usuario, no una decisión que tome.

    Los campos de primer nivel siguen describiendo la granularidad **servida**
    (expediente). ``por_lote`` es aditivo y opcional: ausente salvo que se pida
    explícitamente, de modo que el consumidor actual ve exactamente la misma
    respuesta que antes de v86.
    """

    estado: _EstadoPublico
    cobertura: float | None = None
    cobertura_nominal: float = _COBERTURA_NOMINAL
    mae_p50: float | None = None
    sesgo_p50: float | None = None
    n_evaluadas: int = 0
    granularidad: Granularidad = GRANULARIDAD_SERVIDA
    por_lote: CalibracionPorLoteDTO | None = None


def calibracion_baja_dto(incluir_lote: bool = False) -> CalibracionBajaDTO:
    """Adapta ``comprobar_calibracion_baja()`` al contrato público de 3 estados.

    Args:
        incluir_lote: si además se mide y se adjunta el desglose por lote. Por
            defecto no, porque duplica el coste de la agregación y el bloque es
            diagnóstico: el usuario de calidad-datos decide sobre lo que se
            sirve, y lo que se sirve es el agregado.
    """
    raw = comprobar_calibracion_baja()

    por_lote: CalibracionPorLoteDTO | None = None
    if incluir_lote:
        crudo_lote = comprobar_calibracion_baja("lote")
        por_lote = CalibracionPorLoteDTO(
            estado=_estado_publico(crudo_lote.get("status")),
            cobertura=crudo_lote.get("cobertura"),
            mae_p50=crudo_lote.get("mae_p50"),
            sesgo_p50=crudo_lote.get("sesgo_p50"),
            n_evaluadas=int(crudo_lote.get("n", 0)),
            n_prediccion_por_lote=int(crudo_lote.get("n_prediccion_por_lote", 0)),
        )

    return CalibracionBajaDTO(
        estado=_estado_publico(raw.get("status")),
        cobertura=raw.get("cobertura"),
        mae_p50=raw.get("mae_p50"),
        sesgo_p50=raw.get("sesgo_p50"),
        n_evaluadas=int(raw.get("n", 0)),
        por_lote=por_lote,
    )
