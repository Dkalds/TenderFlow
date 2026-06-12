"""Scoring batch de predicciones (Fase 6, RFC 20260611-2).

Serving = batch nocturno + lectura de tabla (patrón ``ml_proba``): nada de
inferencia online por request. Idempotente: PK natural + INSERT OR REPLACE —
doble ejecución produce las mismas filas.

Si no hay versión activa del modelo en ``model_versions`` (no entrenado aún,
o el entrenamiento no batió al baseline — criterio de honestidad), se sirve
el **baseline** de medias históricas del segmento con ``model_version NULL``:
el frontend puede distinguirlo y etiquetarlo como estimación histórica.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db.database import connect, connect_read, now_utc_iso
from observability.logging import get_logger
from services.competitive.bajas import _VALID_PAIR
from services.ml.baja_model import MODEL_NAME, BajaModel, Prediccion, predecir_baseline
from services.ml.features import features_licitaciones_abiertas

log = get_logger(__name__)


def _media_global_baja() -> float:
    sql = f"""
        SELECT AVG((l.importe - a.importe_adjudicado) / l.importe)
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        WHERE {_VALID_PAIR}
    """  # noqa: S608 — _VALID_PAIR es un fragmento constante
    with connect_read() as c:
        row = c.execute(sql).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.12


def score_predicciones_baja(*, limit: int = 5000) -> dict[str, Any]:
    """Puntúa las licitaciones abiertas y materializa ``predicciones_baja``."""
    filas = features_licitaciones_abiertas(limit=limit)
    if not filas:
        log.info("baja_scoring_skip", reason="sin_licitaciones_abiertas")
        return {"status": "sin_abiertas", "filas": 0}

    from db.model_registry import get_active

    activa = get_active(MODEL_NAME)
    preds: list[Prediccion]
    if activa:
        modelo = BajaModel.load(Path(str(activa["path"])))
        preds = modelo.predict(filas)
        version: int | None = int(activa["version"])
    else:
        preds = predecir_baseline(filas, _media_global_baja())
        version = None

    computed_at = now_utc_iso()
    with connect() as c:
        c.executemany(
            "INSERT OR REPLACE INTO predicciones_baja "
            "(licitacion_id, p10, p50, p90, model_version, computed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (p.licitacion_id, round(p.p10, 5), round(p.p50, 5), round(p.p90, 5),
                 version, computed_at)
                for p in preds
            ],
        )
    log.info(
        "baja_scoring_done",
        filas=len(preds),
        model_version=version,
        serving="modelo" if version else "baseline",
    )
    return {
        "status": "ok",
        "filas": len(preds),
        "model_version": version,
        "serving": "modelo" if version else "baseline",
        "computed_at": computed_at,
    }


def score_predicciones_retencion(*, months_ahead: int = 12) -> dict[str, Any]:
    """Puntúa el riesgo de cambio de manos en los vencimientos próximos.

    A diferencia de la baja, aquí no hay baseline honesto que servir (una
    probabilidad sin modelo calibrado no tiene semántica): sin versión activa
    el batch se salta y la columna queda vacía en el frontend.
    """
    from db.model_registry import get_active

    activa = get_active("retencion_model")
    if not activa:
        log.info("retencion_scoring_skip", reason="sin_modelo_activo")
        return {"status": "sin_modelo", "filas": 0}

    from services.ml.retencion_labels import features_para_vencimientos
    from services.ml.retencion_model import RetencionModel

    filas = features_para_vencimientos(months_ahead=months_ahead)
    if not filas:
        return {"status": "sin_vencimientos", "filas": 0}

    modelo = RetencionModel.load(Path(str(activa["path"])))
    probas = modelo.predict_proba_retencion(filas)
    computed_at = now_utc_iso()
    version = int(activa["version"])
    with connect() as c:
        c.executemany(
            "INSERT OR REPLACE INTO predicciones_retencion "
            "(licitacion_id, empresa_id, prob_retencion, riesgo_cambio, "
            " model_version, computed_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (f.licitacion_id, f.empresa_id, round(p, 5), round(1 - p, 5),
                 version, computed_at)
                for f, p in zip(filas, probas, strict=True)
            ],
        )
    log.info("retencion_scoring_done", filas=len(filas), model_version=version)
    return {"status": "ok", "filas": len(filas), "model_version": version}


def prediccion_baja(licitacion_id: str) -> dict[str, Any] | None:
    """Lectura de la predicción materializada para una licitación."""
    with connect_read() as c:
        cur = c.execute(
            "SELECT licitacion_id, p10, p50, p90, model_version, computed_at "
            "FROM predicciones_baja WHERE licitacion_id = ?",
            (licitacion_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
    data = dict(zip(cols, row, strict=False))
    data["serving"] = "modelo" if data.get("model_version") else "baseline"
    return data
