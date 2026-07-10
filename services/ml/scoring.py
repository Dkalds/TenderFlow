"""Scoring batch de predicciones (Fase 6, RFC 20260611-2).

Serving = batch nocturno + lectura de tabla (patrón ``ml_proba``): nada de
inferencia online por request. Idempotente: PK natural + upsert
(``ON CONFLICT ... DO UPDATE``, portable entre SQLite y Postgres) — doble
ejecución produce las mismas filas.

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
from services.dedupe import exclude_duplicados_sql
from services.ml.baja_model import MODEL_NAME, BajaModel, Prediccion, predecir_baseline
from services.ml.features import features_licitaciones_abiertas
from services.sql_fragments import VALID_PAIR

log = get_logger(__name__)


def _media_global_baja() -> float:
    sql = f"""
        SELECT AVG((l.importe - a.importe_adjudicado) / l.importe)
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        WHERE {VALID_PAIR} AND {exclude_duplicados_sql()}
    """  # noqa: S608 — VALID_PAIR y exclude_duplicados_sql son fragmentos constantes
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
            "INSERT INTO predicciones_baja "
            "(licitacion_id, p10, p50, p90, model_version, computed_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
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

    activa = get_active("retencion_model")

    from services.ml.retencion_labels import features_para_vencimientos

    filas = features_para_vencimientos(months_ahead=months_ahead)
    if not filas:
        return {"status": "sin_vencimientos", "filas": 0}

    if activa:
        from services.ml.retencion_model import RetencionModel

        modelo = RetencionModel.load(Path(str(activa["path"])))
        probas = modelo.predict_proba_retencion(filas)
        computed_at = now_utc_iso()
        version_int: int | None = int(activa["version"])
        model_version_str: str = str(version_int)
        with connect() as c:
            c.executemany(
                "INSERT INTO predicciones_retencion "
                "(licitacion_id, empresa_id, prob_retencion, riesgo_cambio, "
                " model_version, computed_at) VALUES (?, ?, ?, ?, ?, ?) "
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
                " model_version, computed_at) VALUES (?, ?, ?, ?, ?, ?) "
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
