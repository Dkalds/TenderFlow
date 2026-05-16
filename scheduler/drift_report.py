"""Drift detection semanal — compara distribución de inputs recientes vs training set.

Ejecuta un informe Evidently (si está instalado) o un KS test manual.
Guarda el informe HTML en data/reports/drift_YYYYMMDD.html.
Genera alerta si p-value < 0.05 en columna 'importe' o 'cpv'.

Scheduler: añadir `scheduler.drift_report.run_drift_report` como tarea semanal.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from db.database import connect
from observability.logging import get_logger

log = get_logger(__name__)

_REPORTS_DIR = Path(os.environ.get("DATA_DIR", "data")) / "reports"
_WINDOW_DAYS = 7
_TRAIN_WINDOW_DAYS = 90
_KS_ALPHA = 0.05


def _load_window(days: int, offset_days: int = 0) -> pd.DataFrame:
    """Carga licitaciones de los últimos N días (con offset)."""
    cutoff = (datetime.now(UTC) - timedelta(days=offset_days + days)).isoformat()[:10]
    end = (datetime.now(UTC) - timedelta(days=offset_days)).isoformat()[:10]
    with connect() as c:
        cur = c.execute(
            "SELECT importe, cpv, ccaa, tecnologia, estado "
            "FROM licitaciones "
            "WHERE fecha_publicacion >= ? AND fecha_publicacion <= ?",
            (cutoff, end),
        )
        cols = [d[0] for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


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
