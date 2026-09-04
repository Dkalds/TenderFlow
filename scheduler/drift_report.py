"""Drift detection semanal — compara distribución de inputs recientes vs training set.

Ejecuta un informe Evidently (si está instalado) o un KS test manual.

**Dónde sobrevive el resultado.** El HTML y el JSON se escriben en
``DATA_DIR/reports/``, que en el runner de GitHub Actions es un disco efímero
que se destruye al terminar el job y que ningún paso sube como artifact: son
una comodidad para inspección local, no el registro. Lo que persiste es el
**resumen en JSON dentro de ``ops_events``** (:func:`_persistir_resumen`), la
misma tabla que ya leen ``scheduler.healthcheck`` y los tripwires de ADR-004.
Por eso el fichero se escribe *best-effort*: un disco de solo lectura degrada
el informe local, no tumba el paso ni se lleva por delante el resumen durable.

Los umbrales (``KS_ALPHA``) salen de :mod:`services.ml.thresholds`, la tabla
única de umbrales de drift; el mapa de los seis mecanismos que se solapan está
en el docstring de :mod:`services.ml.drift`.

Scheduler: añadir `scheduler.drift_report.run_drift_report` como tarea semanal.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from observability.logging import get_logger
from services.ml.thresholds import KS_ALPHA

log = get_logger(__name__)

_REPORTS_DIR = Path(os.environ.get("DATA_DIR", "data")) / "reports"
_WINDOW_DAYS = 7
_TRAIN_WINDOW_DAYS = 90
# Tipo de evento con el que el resumen aterriza en `ops_events`. Es la clave
# por la que se recupera el histórico de drift cuando el runner ya no existe.
OPS_EVENT_DRIFT_REPORT = "drift_report"


def _json_default(obj: Any) -> Any:
    """Fallback de ``json.dumps`` para escalares y arrays de NumPy.

    Red de seguridad, no la corrección: los flags de drift se convierten a
    ``bool`` en origen. Pero este JSON se serializa dentro de un paso de la
    pipeline diaria, y ese paso falla **en silencio**:
    ``_run_post_ingestion_steps`` se traga la excepción, el run sale verde y el
    único aviso es un email. Hasta 2026-08 un único ``np.bool_`` colado bastaba
    para que ``drift_checks`` no corriera durante semanas sin que nadie lo
    notara — ni informe de drift, ni monitor de PSI/F1 (``run_once`` se ejecuta
    justo después de esta función). Un tipo numérico inesperado no vale eso.
    """
    import numpy as np

    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)


def _load_window(days: int, offset_days: int = 0) -> pd.DataFrame:
    """Carga licitaciones de los últimos N días (con offset)."""
    from services.licitaciones import load_drift_window

    rows = load_drift_window(days, offset_days)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _ks_test(ref: pd.Series, cur: pd.Series) -> dict[str, Any]:
    """KS test between two samples; returns statistic, p-value and drift flag."""
    from scipy import stats as sp_stats  # type: ignore[import-untyped]

    ref_clean = ref.dropna()
    cur_clean = cur.dropna()
    if len(ref_clean) < 10 or len(cur_clean) < 5:
        return {"statistic": None, "p_value": None, "drift": False, "reason": "insufficient_data"}
    stat, pval = sp_stats.ks_2samp(ref_clean.values, cur_clean.values)
    # bool() explícito: ``pval`` es np.float64, así que la comparación devuelve
    # np.bool_ y json.dumps() lo rechaza. Con NumPy 2 el TypeError resultante
    # dice "Object of type bool is not JSON serializable" — np.bool_.__name__
    # ES "bool" — y el mensaje despista. Ver run_drift_report().
    return {"statistic": float(stat), "p_value": float(pval), "drift": bool(pval < KS_ALPHA)}


def _prediction_drift(
    conn: Any,
    window_days: int = 14,
) -> dict[str, Any]:
    """KS test on ml_proba distribution: last N days vs previous N days."""
    from datetime import timedelta

    from scipy import stats as sp_stats

    now = datetime.now(UTC)
    recent_since = (now - timedelta(days=window_days)).isoformat()
    previous_since = (now - timedelta(days=window_days * 2)).isoformat()

    try:
        recent_rows = conn.execute(
            "SELECT ml_proba FROM licitaciones "
            "WHERE fecha_publicacion >= %s AND ml_proba IS NOT NULL",
            (recent_since,),
        ).fetchall()
        previous_rows = conn.execute(
            "SELECT ml_proba FROM licitaciones "
            "WHERE fecha_publicacion >= %s AND fecha_publicacion < %s AND ml_proba IS NOT NULL",
            (previous_since, recent_since),
        ).fetchall()
    except Exception as exc:
        log.warning("prediction_drift_query_failed", error=str(exc))
        return {
            "drift_detected": False,
            "ks_statistic": 0.0,
            "p_value": 1.0,
            "mean_recent": 0.0,
            "mean_previous": 0.0,
            "n_recent": 0,
            "n_previous": 0,
            "error": str(exc),
        }

    import numpy as np

    recent = np.array([float(r[0]) for r in recent_rows if r[0] is not None])
    previous = np.array([float(r[0]) for r in previous_rows if r[0] is not None])

    if len(recent) < 5 or len(previous) < 5:
        return {
            "drift_detected": False,
            "ks_statistic": 0.0,
            "p_value": 1.0,
            "mean_recent": float(recent.mean()) if len(recent) else 0.0,
            "mean_previous": float(previous.mean()) if len(previous) else 0.0,
            "n_recent": len(recent),
            "n_previous": len(previous),
            "reason": "insufficient_data",
        }

    stat, pval = sp_stats.ks_2samp(recent, previous)
    return {
        # bool() explícito: np.bool_ no es serializable a JSON (ver _ks_test).
        "drift_detected": bool(pval < KS_ALPHA),
        "ks_statistic": float(stat),
        "p_value": float(pval),
        "mean_recent": float(recent.mean()),
        "mean_previous": float(previous.mean()),
        "n_recent": len(recent),
        "n_previous": len(previous),
    }


def _resumen_durable(results: dict[str, Any]) -> dict[str, Any]:
    """Lo que se guarda en ``ops_events``: pequeño, plano y suficiente.

    El informe completo (por columna, con estadísticos) no cabe en el ``detail``
    de ``ops_events`` y tampoco hace falta: lo que se consulta semanas después
    es si hubo drift, sobre cuántas filas y en qué columnas.
    """
    return {
        "drift_detected": bool(results.get("drift_detected")),
        "skipped": bool(results.get("skipped")),
        "ref_n": results.get("ref_n"),
        "cur_n": results.get("cur_n"),
        "columns_drift": [
            col
            for col, v in (results.get("columns") or {}).items()
            if isinstance(v, dict) and v.get("drift")
        ],
        "prediction_drift": bool((results.get("prediction_drift") or {}).get("drift_detected")),
    }


def _persistir_resumen(results: dict[str, Any]) -> bool:
    """Escribe el resumen en ``ops_events``. ``True`` si quedó registrado.

    Es el único rastro que sobrevive al runner efímero, así que se llama
    **siempre**, también cuando el informe se salta por falta de datos: "no
    hubo datos esta semana" es información, y con el ``return`` temprano
    anterior no quedaba constancia de ninguna clase.
    """
    try:
        from observability.ops_events import record_event

        record_event(
            OPS_EVENT_DRIFT_REPORT,
            value=1.0 if results.get("drift_detected") else 0.0,
            detail=json.dumps(_resumen_durable(results), ensure_ascii=False, default=_json_default)[
                :500
            ],
        )
    except Exception:
        log.debug("drift_report_ops_event_failed", exc_info=True)
        return False
    return True


def _escribir_local(nombre: str, contenido: str) -> str | None:
    """Escribe un fichero del informe en ``DATA_DIR/reports``. ``None`` si no pudo.

    Best-effort a propósito: el directorio puede no ser escribible (contenedor
    de solo lectura, disco lleno) y ese fichero es una comodidad local, no el
    registro — el registro es ``ops_events``. Antes, el ``mkdir`` estaba en la
    primera línea de ``run_drift_report`` y un fallo ahí se llevaba por delante
    el informe entero.
    """
    try:
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        destino = _REPORTS_DIR / nombre
        destino.write_text(contenido, encoding="utf-8")
    except OSError as exc:
        log.warning("drift_report_local_write_failed", nombre=nombre, error=str(exc))
        return None
    return str(destino)


def run_drift_report() -> dict[str, Any]:
    """Genera informe de drift. Devuelve resumen con flags de alerta."""
    df_ref = _load_window(_TRAIN_WINDOW_DAYS, offset_days=_WINDOW_DAYS)
    df_cur = _load_window(_WINDOW_DAYS)

    results: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "ref_n": len(df_ref),
        "cur_n": len(df_cur),
        "columns": {},
        "drift_detected": False,
    }

    if df_ref.empty or df_cur.empty:
        results["skipped"] = True
        log.warning("drift_report_skipped", reason="empty_data")
        results["persistido"] = _persistir_resumen(results)
        return results

    # ── Numeric drift ─────────────────────────────────────────────────────
    try:
        from scipy import stats  # noqa: F401  # check available

        for col in ["importe"]:
            if col in df_ref.columns and col in df_cur.columns:
                results["columns"][col] = _ks_test(df_ref[col], df_cur[col])
    except ImportError:
        log.warning("scipy_not_installed_for_drift")

    # ── Categorical drift (chi-squared on value counts) ───────────────────
    for col in ["ccaa", "tecnologia", "estado"]:
        if col not in df_ref.columns:
            continue
        ref_counts = df_ref[col].value_counts()
        cur_counts = df_cur[col].value_counts()
        all_cats = set(ref_counts.index) | set(cur_counts.index)
        ref_v = [ref_counts.get(c, 0) for c in all_cats]
        cur_v = [cur_counts.get(c, 0) for c in all_cats]
        try:
            from scipy.stats import chi2_contingency  # type: ignore[import-untyped]

            table = [ref_v, cur_v]
            _, pval, _, _ = chi2_contingency(table)
            results["columns"][col] = {
                "p_value": float(pval),
                # bool() explícito: np.bool_ no es serializable (ver _ks_test).
                "drift": bool(pval < KS_ALPHA),
            }
        except Exception:
            log.debug("chi2_drift_test_failed", column=col, exc_info=True)

    results["drift_detected"] = any(v.get("drift", False) for v in results["columns"].values())

    # ── Prediction distribution drift (ml_proba) ─────────────────────────
    try:
        from db.connection import connect_read

        with connect_read() as conn:
            pred_drift = _prediction_drift(conn)
        results["prediction_drift"] = pred_drift
        if pred_drift.get("drift_detected"):
            results["drift_detected"] = True
            log.warning("prediction_drift_detected", **pred_drift)
        else:
            log.info(
                "prediction_drift_ok",
                n_recent=pred_drift["n_recent"],
                n_previous=pred_drift["n_previous"],
            )
    except Exception as exc:
        log.warning("prediction_drift_failed", error=str(exc))
        results["prediction_drift"] = {"error": str(exc)}

    # ── Persistir resumen en ops_events ──────────────────────────────────
    # PRIMERO, antes de tocar el disco: el JSON/HTML de abajo muere con el
    # runner efímero de Actions y nada lo sube como artifact, así que el
    # resumen durable no puede quedar detrás de una escritura de fichero que
    # puede fallar (revisión de arquitectura 2026-08/2026-09). ops_events es la
    # tabla compartida que ya leen healthcheck y los tripwires.
    results["persistido"] = _persistir_resumen(results)

    # ── Evidently HTML report (opcional, artefacto local) ─────────────────
    date_str = datetime.now(UTC).strftime("%Y%m%d")
    try:
        from evidently.metric_preset import DataDriftPreset  # type: ignore[import-not-found]
        from evidently.report import Report  # type: ignore[import-not-found]

        report = Report(metrics=[DataDriftPreset()])
        report.run(reference_data=df_ref, current_data=df_cur)
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path = _REPORTS_DIR / f"drift_{date_str}.html"
        report.save_html(str(report_path))
        results["report_path"] = str(report_path)
        log.info("drift_evidently_report_saved", path=str(report_path))
    except ImportError:
        log.info("evidently_not_installed", hint="pip install evidently")
    except Exception as exc:
        log.warning("drift_evidently_error", error=str(exc))

    # ── Copia local del JSON (comodidad de inspección, no el registro) ────
    json_path = _escribir_local(
        f"drift_{date_str}.json",
        json.dumps(results, indent=2, ensure_ascii=False, default=_json_default),
    )
    if json_path is not None:
        results["json_path"] = json_path

    if results["drift_detected"]:
        log.warning(
            "drift_detected", columns=[k for k, v in results["columns"].items() if v.get("drift")]
        )
    else:
        log.info("drift_report_ok", ref_n=results["ref_n"], cur_n=results["cur_n"])

    return results


# ────────────────── F1 Drop — model performance degradation ───────────────


def compute_f1_drop(
    model_name: str = "sap_classifier",
    *,
    window_days: int = 30,
    min_labelled: int = 20,
) -> float:
    """Estima la caída de F1 del modelo activo respecto a sus métricas de entrenamiento.

    Estrategia: usa las filas con feedback humano explícito (``ml_feedback``)
    de los últimos ``window_days`` días como ground-truth, y compara las
    predicciones actuales del modelo contra esa etiqueta.

    Args:
        model_name:   Nombre del modelo en el registry.
        window_days:  Ventana de feedback reciente a evaluar.
        min_labelled: Mínimo de ejemplos etiquetados para proceder.

    Returns:
        Caída relativa de F1 (0.0 si no hay datos suficientes o no hay modelo
        activo registrado). Positivo = degradación; negativo = mejora.
    """
    try:
        from datetime import timedelta

        from sklearn.metrics import f1_score

        from db.database import connect as db_connect
        from db.model_registry import get_active
        from scraper.ml_classifier import SAPClassifier

    except ImportError as exc:
        log.warning("compute_f1_drop_import_error", error=str(exc))
        return 0.0

    active = get_active(model_name)
    if active is None:
        log.info("compute_f1_drop_no_active_model", model=model_name)
        return 0.0

    # Referencia: el F1 del modelo sobre el holdout HUMANO del golden set.
    #
    # Antes se usaba ``metrics["f1"]``, medido sobre el test split cuyas
    # etiquetas derivan de ``raw_keywords``, y se comparaba contra el F1 sobre
    # feedback humano reciente. Son dos poblaciones con semántica de etiqueta
    # distinta y prevalencia distinta: la diferencia entre ambas es
    # estructural, no deriva. Con el aviso al 3% de caída relativa, eso
    # significa alertar (o no) por razones que nada tienen que ver con el
    # modelo. Ahora ambos lados son etiquetas humanas.
    metricas_activas = active.get("metrics", {})
    trained_f1 = float(metricas_activas.get("golden_holdout_f1") or 0.0)
    if trained_f1 <= 0.0:
        log.warning(
            "compute_f1_drop_sin_referencia_humana",
            model=model_name,
            hint=(
                "La versión activa no tiene golden_holdout_f1: se registró antes "
                "del gate de promoción unificado. No se compara contra el f1 del "
                "test split porque mide otra cosa."
            ),
        )
        return 0.0

    # Cargar feedback reciente como ground-truth
    since = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()
    try:
        with db_connect() as c:
            rows = c.execute(
                # ``source = 'human'`` por el mismo motivo que en
                # ``_fetch_training_dataframe``: el feedback automático del
                # etiquetado por LLM son predicciones, no ground truth.
                # Usarlas aquí medía el acuerdo entre dos modelos y lo
                # reportaba como degradación frente a la realidad.
                "SELECT f.expediente, f.relevante, l.titulo, l.descripcion, "
                "l.cpv, l.importe "
                "FROM ml_feedback f "
                "JOIN licitaciones l ON l.id_externo = f.expediente "
                "WHERE f.created_at >= %s AND f.source = 'human'",
                (since,),
            ).fetchall()
    except Exception as exc:
        log.warning("compute_f1_drop_query_failed", error=str(exc))
        return 0.0

    if len(rows) < min_labelled:
        log.info("compute_f1_drop_insufficient_data", n=len(rows), min=min_labelled)
        return 0.0

    # Cargar modelo activo desde registry path
    model_path = active.get("path")
    try:
        from pathlib import Path

        clf = SAPClassifier.load(Path(model_path)) if model_path else SAPClassifier.load()
    except Exception as exc:
        log.warning("compute_f1_drop_load_failed", error=str(exc))
        return 0.0

    # Predecir
    texts = [f"{r[2] or ''} {r[3] or ''}" for r in rows]
    cpvs = [r[4] for r in rows]
    importes = [r[5] for r in rows]
    y_true = [int(r[1]) for r in rows]

    try:
        preds = [
            int(clf.predict(t, cpv=cpv, importe=imp)[0])
            for t, cpv, imp in zip(texts, cpvs, importes, strict=False)
        ]
        current_f1 = float(f1_score(y_true, preds, zero_division=0))
    except Exception as exc:
        log.warning("compute_f1_drop_predict_failed", error=str(exc))
        return 0.0

    drop = max(0.0, trained_f1 - current_f1)
    relative_drop = drop / trained_f1 if trained_f1 > 0 else 0.0
    log.info(
        "compute_f1_drop_result",
        model=model_name,
        trained_f1=round(trained_f1, 4),
        current_f1=round(current_f1, 4),
        relative_drop=round(relative_drop, 4),
        n_labelled=len(rows),
    )
    return relative_drop
