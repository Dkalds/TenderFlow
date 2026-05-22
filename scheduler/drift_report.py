"""Drift detection semanal — compara distribución de inputs recientes vs training set.

Ejecuta un informe Evidently (si está instalado) o un KS test manual.
Guarda el informe HTML en data/reports/drift_YYYYMMDD.html.
Genera alerta si p-value < 0.05 en columna 'importe' o 'cpv'.

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

log = get_logger(__name__)

_REPORTS_DIR = Path(os.environ.get("DATA_DIR", "data")) / "reports"
_WINDOW_DAYS = 7
_TRAIN_WINDOW_DAYS = 90
_KS_ALPHA = 0.05


def _load_window(days: int, offset_days: int = 0) -> pd.DataFrame:
    """Carga licitaciones de los últimos N días (con offset)."""
    from services.licitaciones import load_drift_window

    rows = load_drift_window(days, offset_days)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _ks_test(ref: pd.Series, cur: pd.Series) -> dict[str, Any]:
    """KS test between two samples; returns statistic, p-value and drift flag."""
    from scipy import stats as sp_stats  # type: ignore[import]

    ref_clean = ref.dropna()
    cur_clean = cur.dropna()
    if len(ref_clean) < 10 or len(cur_clean) < 5:
        return {"statistic": None, "p_value": None, "drift": False, "reason": "insufficient_data"}
    stat, pval = sp_stats.ks_2samp(ref_clean.values, cur_clean.values)
    return {"statistic": float(stat), "p_value": float(pval), "drift": pval < _KS_ALPHA}


def run_drift_report() -> dict[str, Any]:
    """Genera informe de drift. Devuelve resumen con flags de alerta."""
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)

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
            from scipy.stats import chi2_contingency  # type: ignore[import]

            table = [ref_v, cur_v]
            _, pval, _, _ = chi2_contingency(table)
            results["columns"][col] = {"p_value": float(pval), "drift": pval < _KS_ALPHA}
        except Exception:
            pass

    results["drift_detected"] = any(v.get("drift", False) for v in results["columns"].values())

    # ── Evidently HTML report (optional) ─────────────────────────────────
    report_path: Path | None = None
    try:
        from evidently.metric_preset import DataDriftPreset  # type: ignore[import]
        from evidently.report import Report  # type: ignore[import]

        report = Report(metrics=[DataDriftPreset()])
        report.run(reference_data=df_ref, current_data=df_cur)
        date_str = datetime.now(UTC).strftime("%Y%m%d")
        report_path = _REPORTS_DIR / f"drift_{date_str}.html"
        report.save_html(str(report_path))
        results["report_path"] = str(report_path)
        log.info("drift_evidently_report_saved", path=str(report_path))
    except ImportError:
        log.info("evidently_not_installed", hint="pip install evidently")
    except Exception as exc:
        log.warning("drift_evidently_error", error=str(exc))

    # ── Save JSON summary ─────────────────────────────────────────────────
    date_str = datetime.now(UTC).strftime("%Y%m%d")
    json_path = _REPORTS_DIR / f"drift_{date_str}.json"
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    results["json_path"] = str(json_path)

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

        from sklearn.metrics import f1_score  # type: ignore[import]

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

    # F1 registrado en el entrenamiento
    trained_f1 = float(active.get("metrics", {}).get("f1") or 0.0)
    if trained_f1 <= 0.0:
        return 0.0

    # Cargar feedback reciente como ground-truth
    since = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()
    try:
        with db_connect() as c:
            rows = c.execute(
                "SELECT f.expediente, f.relevante, l.titulo, l.descripcion, "
                "l.cpv, l.importe "
                "FROM ml_feedback f "
                "JOIN licitaciones l ON l.id_externo = f.expediente "
                "WHERE f.created_at >= ?",
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
            int(clf.predict(t, cpv, imp)[0])
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
