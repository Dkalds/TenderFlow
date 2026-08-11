"""Scoring batch de predicciones (Fase 6, RFC 20260611-2).

Serving = batch nocturno + lectura de tabla (patrón ``ml_proba``): nada de
inferencia online por request. Idempotente: PK natural + upsert
(``ON CONFLICT ... DO UPDATE``) — doble
ejecución produce las mismas filas.

Si no hay versión activa del modelo en ``model_versions`` (no entrenado aún,
o el entrenamiento no batió al baseline — criterio de honestidad), se sirve
el **baseline** de medias históricas del segmento con ``model_version NULL``:
el frontend puede distinguirlo y etiquetarlo como estimación histórica.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from observability.logging import get_logger
from services.dedupe import exclude_duplicados_sql
from services.ml.baja_model import (
    MODEL_NAME,
    BajaModel,
    FeatureSchemaMismatch,
    Prediccion,
    predecir_baseline,
)
from services.ml.features import features_licitaciones_abiertas

log = get_logger(__name__)


def _media_global_baja() -> float:
    """Baja media histórica, usada como baseline sin modelo entrenado.

    Delega en ``db.repositories.ml_dataset`` para compartir la regla de
    denominador con el target de entrenamiento y con ``calibration.py``: antes
    promediaba bajas **por lote** mientras el modelo predice la baja
    **agregada por expediente**, así que el baseline y el modelo no medían la
    misma magnitud.
    """
    from db.repositories.ml_dataset import MlDatasetRepository

    return MlDatasetRepository().media_global_baja()


def score_predicciones_baja(*, limit: int = 5000) -> dict[str, Any]:
    """Puntúa las licitaciones abiertas y materializa ``predicciones_baja``."""
    filas = features_licitaciones_abiertas(limit=limit)
    if not filas:
        log.info("baja_scoring_skip", reason="sin_licitaciones_abiertas")
        return {"status": "sin_abiertas", "filas": 0}

    from db.model_registry import get_active
    from shared.model_artifacts import resolve_active_artifact

    # resolve_active_artifact verifica el sha256 registrado (y descarga el
    # asset de la Release si el runner efímero no tiene el fichero). Un
    # artefacto irresoluble degrada a baseline; un MISMATCH propaga — servir
    # predicciones de un artefacto equivocado es peor que no servirlas.
    activa = get_active(MODEL_NAME)
    artefacto = resolve_active_artifact(MODEL_NAME) if activa else None
    preds: list[Prediccion] | None = None
    version: int | None = None
    if activa and artefacto is not None:
        modelo = BajaModel.load(artefacto)
        try:
            preds = modelo.predict(filas)
            version = int(activa["version"])
        except FeatureSchemaMismatch as exc:
            # El artefacto activo se entrenó con otro layout de columnas: sus
            # árboles recibirían features distintas en las mismas posiciones y
            # devolverían números sin significado. Degradar al baseline (que la
            # UI ya etiqueta como estimación histórica) es la única opción
            # honesta hasta que corra el reentrenamiento.
            log.warning(
                "baja_model_feature_schema_mismatch",
                version=int(activa["version"]),
                error=str(exc),
            )
    if preds is None:
        if activa and artefacto is None:
            log.warning("baja_model_artifact_unresolvable_fallback_baseline")
        preds = predecir_baseline(filas, _media_global_baja())
        version = None

    computed_at = now_utc_iso()
    with connect() as c:
        c.executemany(
            "INSERT INTO predicciones_baja "
            "(licitacion_id, p10, p50, p90, model_version, computed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT(licitacion_id) DO UPDATE SET "
            "p10=excluded.p10, p50=excluded.p50, p90=excluded.p90, "
            "model_version=excluded.model_version, computed_at=excluded.computed_at",
            [
                (
                    p.licitacion_id,
                    round(p.p10, 5),
                    round(p.p50, 5),
                    round(p.p90, 5),
                    version,
                    computed_at,
                )
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


def _tasa_retencion_baseline() -> dict[tuple[str, str], float]:
    """Tasa historica de re-adjudicacion al mismo adjudicatario por (organo, CPV-4).

    Para cada par (organo, CPV-4) con >= 5 contratos consecutivos, calcula la
    fraccion de los que fueron readjudicados al mismo ganador.
    Fallback: media global si el par no tiene historia suficiente.
    """
    sql = """
        SELECT
            l.organo_contratacion,
            substr(l.cpv, 1, 4) AS cpv4,
            COUNT(*) AS total,
            SUM(CASE WHEN a.empresa_id IS NOT NULL THEN 1 ELSE 0 END) AS con_adjudicatario
        FROM licitaciones l
        JOIN adjudicaciones a ON a.licitacion_id = l.id_externo
        WHERE l.organo_contratacion IS NOT NULL
          AND COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed'
          AND l.cpv IS NOT NULL
          AND length(l.cpv) >= 4
        GROUP BY l.organo_contratacion, cpv4
        HAVING COUNT(*) >= 5
    """
    tasas: dict[tuple[str, str], float] = {}
    try:
        with connect_read() as c:
            rows = c.execute(sql).fetchall()
        for row in rows:
            organo, cpv4, total, con_adj = row
            if total and total > 0:
                tasas[(str(organo), str(cpv4))] = float(con_adj) / float(total)
    except Exception as exc:
        log.warning("retencion_baseline_error", error=str(exc))
    return tasas


def _media_global_retencion(tasas: dict[tuple[str, str], float]) -> float:
    if not tasas:
        return 0.6  # default conservador
    return sum(tasas.values()) / len(tasas)


def score_predicciones_retencion(*, months_ahead: int = 12) -> dict[str, Any]:
    """Puntua el riesgo de cambio de manos en los vencimientos proximos.

    Sin version activa del modelo, usa un baseline heuristico: tasa historica
    de re-adjudicacion por (organo, CPV-4) con fallback a media global.
    Se materializa con model_version='baseline' para que la UI lo distinga.
    """
    from db.model_registry import get_active
    from shared.model_artifacts import resolve_active_artifact

    activa = get_active("retencion_model")
    artefacto = resolve_active_artifact("retencion_model") if activa else None
    if activa and artefacto is None:
        log.warning("retencion_model_artifact_unresolvable_fallback_baseline")
        activa = None

    from services.ml.retencion_labels import features_para_vencimientos

    filas = features_para_vencimientos(months_ahead=months_ahead)
    if not filas:
        return {"status": "sin_vencimientos", "filas": 0}

    if activa:
        from services.ml.retencion_model import RetencionModel

        assert artefacto is not None
        modelo = RetencionModel.load(artefacto)
        probas = modelo.predict_proba_retencion(filas)
        computed_at = now_utc_iso()
        version_int: int | None = int(activa["version"])
        model_version_str: str = str(version_int)
        with connect() as c:
            c.executemany(
                "INSERT INTO predicciones_retencion "
                "(licitacion_id, empresa_id, prob_retencion, riesgo_cambio, "
                " model_version, computed_at) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT(licitacion_id) DO UPDATE SET "
                "empresa_id=excluded.empresa_id, prob_retencion=excluded.prob_retencion, "
                "riesgo_cambio=excluded.riesgo_cambio, "
                "model_version=excluded.model_version, computed_at=excluded.computed_at",
                [
                    (
                        f.licitacion_id,
                        f.empresa_id,
                        round(p, 5),
                        round(1 - p, 5),
                        version_int,
                        computed_at,
                    )
                    for f, p in zip(filas, probas, strict=True)
                ],
            )
        log.info("retencion_scoring_done", filas=len(filas), model_version=version_int)
        return {"status": "ok", "filas": len(filas), "model_version": version_int}
    else:
        # Baseline heuristico: tasa historica de re-adjudicacion por segmento
        log.info("retencion_scoring_baseline", reason="sin_modelo_activo", filas=len(filas))
        tasas = _tasa_retencion_baseline()
        media_global = _media_global_retencion(tasas)
        computed_at = now_utc_iso()
        model_version_str = "baseline"
        rows_to_insert = []
        for f in filas:
            # Intentar obtener CPV-4 y organo de la fila (si tiene estos attrs)
            cpv4 = str(getattr(f, "cpv", "") or "")[:4]
            organo = str(getattr(f, "organo_contratacion", "") or "")
            tasa = tasas.get((organo, cpv4), media_global) if cpv4 and organo else media_global
            prob = min(max(tasa, 0.0), 1.0)
            rows_to_insert.append(
                (
                    f.licitacion_id,
                    f.empresa_id,
                    round(prob, 5),
                    round(1 - prob, 5),
                    None,
                    computed_at,
                )
            )
        with connect() as c:
            c.executemany(
                "INSERT INTO predicciones_retencion "
                "(licitacion_id, empresa_id, prob_retencion, riesgo_cambio, "
                " model_version, computed_at) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT(licitacion_id) DO UPDATE SET "
                "empresa_id=excluded.empresa_id, prob_retencion=excluded.prob_retencion, "
                "riesgo_cambio=excluded.riesgo_cambio, "
                "model_version=excluded.model_version, computed_at=excluded.computed_at",
                rows_to_insert,
            )
        log.info("retencion_baseline_done", filas=len(rows_to_insert))
        return {
            "status": "baseline",
            "filas": len(rows_to_insert),
            "model_version": model_version_str,
            "serving": "baseline",
        }


def _baja_real(c: Any, licitacion_id: str) -> tuple[float, float] | None:
    """Baja real ``(baja_pct, importe_adjudicado)`` si la licitación fue adjudicada.

    Suma ``importe_adjudicado`` de todos los lotes de la licitación (una
    licitación puede tener varias filas en ``adjudicaciones``) y lo compara
    contra el presupuesto (``licitaciones.importe``).
    """
    sql = f"""
        SELECT l.importe, SUM(a.importe_adjudicado) AS total_adjudicado
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        WHERE a.licitacion_id = %s AND {exclude_duplicados_sql()}
          AND l.importe > 0 AND a.importe_adjudicado > 0
        GROUP BY l.importe
    """  # noqa: S608 — exclude_duplicados_sql() es un fragmento constante
    row = c.execute(sql, (licitacion_id,)).fetchone()
    if row is None or row[0] is None or row[1] is None:
        return None
    importe, total_adjudicado = row
    return (importe - total_adjudicado) / importe, total_adjudicado


def prediccion_baja(licitacion_id: str) -> dict[str, Any] | None:
    """Lectura de la predicción materializada y/o la baja real de una licitación.

    - Publicada/abierta: solo estimación del batch (p10/p50/p90).
    - Adjudicada con estimación previa (scoreada antes de adjudicarse): ambas,
      para comparar lo estimado contra lo real.
    - Adjudicada sin estimación previa (adjudicada antes de que corriera el
      batch): solo la baja real.
    - Ninguna de las dos → ``None`` (404).
    """
    with connect_read() as c:
        cur = c.execute(
            "SELECT p10, p50, p90, model_version, computed_at "
            "FROM predicciones_baja WHERE licitacion_id = %s",
            (licitacion_id,),
        )
        pred_row = cur.fetchone()
        real = _baja_real(c, licitacion_id)

    if pred_row is None and real is None:
        return None

    data: dict[str, Any] = {"licitacion_id": licitacion_id}
    if pred_row is not None:
        p10, p50, p90, model_version, computed_at = pred_row
        data.update(
            p10=p10,
            p50=p50,
            p90=p90,
            model_version=model_version,
            computed_at=computed_at,
            serving="modelo" if model_version else "baseline",
        )
    if real is not None:
        baja_real, importe_adjudicado = real
        data["baja_real"] = baja_real
        data["importe_adjudicado"] = importe_adjudicado
    return data
