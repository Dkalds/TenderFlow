"""Scoring batch de predicciones (Fase 6, RFC 20260611-2).

Serving = batch nocturno + lectura de tabla (patrón ``ml_proba``): nada de
inferencia online por request. Idempotente: PK natural + upsert
(``ON CONFLICT ... DO UPDATE``) — doble
ejecución produce las mismas filas.

Si no hay versión activa del modelo en ``model_versions`` (no entrenado aún,
o el entrenamiento no batió al baseline — criterio de honestidad), se sirve
el **baseline** de medias históricas del segmento con ``model_version NULL``:
el frontend puede distinguirlo y etiquetarlo como estimación histórica.

Ese baseline también **conformaliza** su intervalo (``_offset_baseline``). Su
±40% relativo era una forma sin garantía de cobertura, servida bajo el nombre
p10/p90 que promete un 80%: en producción cubría el 24%. Ahora la anchura sale
de los pares predicción↔realidad que el propio baseline ya generó, con la misma
matemática split-conformal que usa el modelo.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from observability.logging import get_logger
from services.dedupe import exclude_duplicados_sql, normalize_organo
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


def _offset_baseline() -> float:
    """Corrección conformal del intervalo del baseline, sobre pares ya resueltos.

    Sin esto el baseline servía un ±40% relativo que no cubría el 80% que su
    nombre (p10/p90) promete: medido en producción sobre 406 pares, cubría el
    24%. El offset lo mide contra la realidad y lo corrige.

    Fail-open como el resto del closed-loop: si la agregación falla se sirve el
    intervalo crudo en vez de no servir nada. Se loguea el fallo, porque un 0
    por error y un 0 por falta de pares se leen igual en la tabla y no son lo
    mismo.
    """
    from db.repositories.ml_dataset import MlDatasetRepository
    from services.ml.baja_model import offset_conformal_baseline

    try:
        return offset_conformal_baseline(MlDatasetRepository().pares_baseline_resueltos())
    except Exception as exc:
        log.warning("baja_baseline_conformal_failed", error=str(exc))
        return 0.0


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
    # Distingue el baseline legítimo (no hay versión activa: el RFC lo sirve a
    # propósito) del baseline **degradado** (hay versión activa pero no se pudo
    # servir). Los dos escriben las mismas filas y hasta 2026-08 los dos salían
    # como `status: ok`, así que el batch pasaba en verde mientras el modelo
    # activo llevaba semanas sin llegar a producción. El CLI usa este campo
    # para poner el job en rojo y alertar.
    degradado: str | None = None
    # Solo tiene valor en el camino baseline; en el del modelo la
    # conformalización ya viene dentro del artefacto (`conformal_offset`).
    offset_baseline: float | None = None
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
            degradado = "feature_schema_mismatch"
    if preds is None:
        if activa and artefacto is None:
            log.warning("baja_model_artifact_unresolvable_fallback_baseline")
            degradado = "artefacto_irresoluble"
        offset_baseline = _offset_baseline()
        preds = predecir_baseline(filas, _media_global_baja(), offset_baseline)
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
        degradado=degradado,
        conformal_offset_baseline=offset_baseline,
    )
    return {
        "status": "ok",
        "filas": len(preds),
        "model_version": version,
        "serving": "modelo" if version else "baseline",
        "degradado": degradado,
        "conformal_offset_baseline": offset_baseline,
        "computed_at": computed_at,
    }


def _tasa_retencion_baseline() -> dict[tuple[str, str], float]:
    """Tasa histórica de **retención** por ``(órgano normalizado, CPV-4)``.

    Hasta 2026-08 esta función medía otra cosa: contaba adjudicaciones con
    ``empresa_id`` no nulo sobre el total del segmento —la tasa de vinculación
    al maestro de empresas, ≈1 en cuanto la resolución de entidades funciona—
    bajo un docstring que prometía "la fracción de los que fueron readjudicados
    al mismo ganador". El resultado era un ``predicciones_retencion`` con un
    riesgo de cambio constante y falsamente bajo, escrito cada noche.

    Ahora delega en ``retencion_labels.tasas_retencion_por_segmento``, que
    agrega ``AVG(label)`` sobre los MISMOS pares vencimiento→sucesora con los
    que se entrena el modelo de retención. Es el mismo criterio que aplica
    :func:`_media_global_baja` con el target de baja: el baseline tiene que
    medir la magnitud que sustituye, o compararlo con el modelo no significa
    nada.

    Efecto lateral buscado: la población pasa a ser la del etiquetado (todas
    las adjudicaciones no duplicadas con fin efectivo) en vez del universo
    ``technology_observed`` de la query anterior. La comparación baseline↔
    modelo se hace sobre las mismas filas.

    Fail-open, como antes: si el etiquetado falla, ``{}`` y el serving cae a la
    media global.
    """
    from services.ml.retencion_labels import tasas_retencion_por_segmento

    try:
        return tasas_retencion_por_segmento()
    except Exception as exc:
        log.warning("retencion_baseline_error", error=str(exc))
        return {}


def _media_global_retencion(tasas: dict[tuple[str, str], float]) -> float:
    if not tasas:
        return 0.6  # default conservador
    return sum(tasas.values()) / len(tasas)


def score_predicciones_retencion(*, months_ahead: int = 12) -> dict[str, Any]:
    """Puntua el riesgo de cambio de manos en los vencimientos proximos.

    Sin version activa del modelo, usa un baseline heuristico: tasa historica
    de retencion observada por (organo normalizado, CPV-4) con fallback a la
    media global (:func:`_tasa_retencion_baseline`).
    Se materializa con model_version='baseline' para que la UI lo distinga.
    """
    from db.model_registry import get_active
    from shared.model_artifacts import resolve_active_artifact

    activa = get_active("retencion_model")
    artefacto = resolve_active_artifact("retencion_model") if activa else None
    # Ver la nota de `degradado` en score_predicciones_baja: el baseline por
    # falta de modelo activo es el contrato del RFC; el baseline con modelo
    # activo irresoluble es una avería que debe verse.
    degradado: str | None = None
    if activa and artefacto is None:
        log.warning("retencion_model_artifact_unresolvable_fallback_baseline")
        degradado = "artefacto_irresoluble"
        activa = None

    from services.ml.retencion_labels import features_para_vencimientos

    filas = features_para_vencimientos(months_ahead=months_ahead)
    if not filas:
        return {"status": "sin_vencimientos", "filas": 0, "degradado": degradado}

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
        return {
            "status": "ok",
            "filas": len(filas),
            "model_version": version_int,
            "degradado": None,
        }
    else:
        # Baseline heuristico: tasa historica de retencion observada por segmento
        log.info("retencion_scoring_baseline", reason="sin_modelo_activo", filas=len(filas))
        tasas = _tasa_retencion_baseline()
        media_global = _media_global_retencion(tasas)
        computed_at = now_utc_iso()
        model_version_str = "baseline"
        rows_to_insert = []
        for f in filas:
            # La clave tiene que ser la MISMA con la que se agregó la tasa:
            # ``(normalize_organo(organo), cpv4)``. Antes se leían ``f.cpv`` y
            # ``f.organo_contratacion`` con ``getattr(..., "")``, dos atributos
            # que ``ParRetencion`` no tiene: los dos salían vacíos, la condición
            # de abajo era siempre falsa y TODAS las filas recibían la media
            # global — el lookup por segmento no se aplicaba nunca.
            organo_n = normalize_organo(f.organo)
            cpv4 = f.cpv4 or ""
            tasa = tasas.get((organo_n, cpv4), media_global) if cpv4 and organo_n else media_global
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
        log.info("retencion_baseline_done", filas=len(rows_to_insert), degradado=degradado)
        return {
            "status": "baseline",
            "filas": len(rows_to_insert),
            "model_version": model_version_str,
            "serving": "baseline",
            "degradado": degradado,
        }


def _baja_real(c: Any, licitacion_id: str) -> tuple[float, float] | None:
    """Baja real ``(baja_pct, importe_adjudicado)`` si la licitación fue adjudicada.

    Suma ``importe_adjudicado`` de todos los lotes de la licitación (una
    licitación puede tener varias filas en ``adjudicaciones``) y lo divide
    entre el **presupuesto efectivo** del expediente.

    Ese denominador es la parte que estaba mal. El modelo aprende y
    ``calibration.py`` mide contra la regla de
    ``db.repositories.ml_dataset._sql_agregado``: si TODAS las adjudicaciones
    del expediente tienen ``lote_id`` resuelto, el presupuesto es la suma de
    los lotes **distintos** adjudicados (un lote ganado por dos empresas no
    cuenta su presupuesto dos veces); si alguna no lo tiene (datos anteriores a
    v65_lotes), ``licitaciones.importe``. Aquí se dividía siempre entre
    ``licitaciones.importe``, así que un expediente de tres lotes con dos
    adjudicados devolvía por el API una "baja real" del 61% al lado de un
    intervalo entrenado contra el 22% de la porción adjudicada: la comparación
    estimado-vs-real que justifica este endpoint enfrentaba dos magnitudes
    distintas.

    Lo que **no** se importa del dataset son sus filtros de validez (universo
    ``technology_observed``, tolerancia de sobrecoste): seleccionan filas de
    entrenamiento, no filas que enseñar. Aplicarlos aquí convertiría en 404
    expedientes reales por no ser aptos para entrenar.

    La regla vive duplicada porque ``MlDatasetRepository`` solo la expone sobre
    el dataset completo y este es un GET por expediente; su sitio natural es un
    método por id en ese repositorio (``db/``).
    """
    sql = f"""
        WITH adj AS (
            SELECT SUM(a.importe_adjudicado) AS total_adjudicado,
                   COUNT(*) AS n_adjudicaciones,
                   COUNT(a.lote_id) AS n_con_lote
            FROM adjudicaciones a
            WHERE a.licitacion_id = %s
              AND a.importe_adjudicado > 0
              AND {exclude_duplicados_sql("a.licitacion_id")}
        ),
        lotes_adjudicados AS (
            SELECT SUM(lo.importe) AS presupuesto_lotes
            FROM (
                SELECT DISTINCT licitacion_id, lote_id
                FROM adjudicaciones
                WHERE licitacion_id = %s
                  AND lote_id IS NOT NULL
                  AND importe_adjudicado > 0
            ) d
            JOIN lotes lo ON lo.id = d.lote_id
            WHERE lo.importe > 0
        )
        SELECT CASE
                   WHEN adj.n_adjudicaciones = adj.n_con_lote
                        AND la.presupuesto_lotes > 0
                   THEN la.presupuesto_lotes
                   ELSE l.importe
               END AS presupuesto_efectivo,
               adj.total_adjudicado
        FROM adj
        JOIN licitaciones l ON l.id_externo = %s
        LEFT JOIN lotes_adjudicados la ON TRUE
        WHERE l.importe > 0 AND adj.total_adjudicado > 0
    """  # noqa: S608 — exclude_duplicados_sql() es un fragmento constante
    row = c.execute(sql, (licitacion_id, licitacion_id, licitacion_id)).fetchone()
    if row is None or row[0] is None or row[1] is None:
        return None
    presupuesto_efectivo, total_adjudicado = float(row[0]), float(row[1])
    if presupuesto_efectivo <= 0:
        return None
    return (presupuesto_efectivo - total_adjudicado) / presupuesto_efectivo, total_adjudicado


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
