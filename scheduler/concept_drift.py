"""Concept drift detector — detecta términos emergentes no cubiertos por SAP_KEYWORDS.

Analiza licitaciones recientes usando TF-IDF para encontrar términos frecuentes
que no están en el vocabulario conocido (SAP_KEYWORDS). Estos términos candidatos
pueden indicar nuevas tecnologías, módulos o servicios SAP que deberían añadirse
a la configuración.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from config import SAP_KEYWORDS
from db.database import connect
from observability import AlertLevel, get_logger, notify

log = get_logger(__name__)

# Palabras funcionales (stop words) que ignoramos siempre
_STOP_WORDS = frozenset(
    [
        "de",
        "del",
        "la",
        "las",
        "el",
        "los",
        "un",
        "una",
        "en",
        "por",
        "para",
        "con",
        "al",
        "que",
        "se",
        "su",
        "sus",
        "no",
        "es",
        "y",
        "o",
        "a",
        "ante",
        "bajo",
        "con",
        "contra",
        "desde",
        "entre",
        "hacia",
        "hasta",
        "según",
        "sin",
        "sobre",
        "tras",
        "durante",
        "mediante",
        "como",
        "más",
        "pero",
        "si",
        "ser",
        "haber",
        "estar",
        "tener",
        "hacer",
        "poder",
        "decir",
        "ir",
        "ver",
        "dar",
        "saber",
        "este",
        "esta",
        "estos",
        "estas",
        "ese",
        "esa",
        "esos",
        "esas",
        "aquel",
        "aquella",
        "todo",
        "toda",
        "todos",
        "todas",
        "otro",
        "otra",
        "otros",
        "otras",
        "mismo",
        "misma",
        "servicio",
        "servicios",
        "contrato",
        "contratos",
        "licitación",
        "licitaciones",
        "sistema",
        "sistemas",
        "información",
        "pública",
        "público",
        "públicas",
        "públicos",
        "gestión",
        "administración",
        "plataforma",
        "electrónica",
        "general",
        "mantenimiento",
        "soporte",
        "técnico",
        "asistencia",
        "dirección",
        "nacional",
        "ministerio",
        "comunidad",
        "ayuntamiento",
        "diputación",
        "universidad",
        "acuerdo",
        "marco",
        "lote",
        "lotes",
        "expediente",
        "tipo",
        "procedimiento",
        "abierto",
        "negociado",
        "restringido",
        "anualidad",
        "anualidades",
        "importe",
        "objeto",
        "descripción",
        "título",
        "adjudicación",
    ]
)

# Normalizar SAP_KEYWORDS a minúsculas para comparación
_KNOWN_TERMS = frozenset(k.lower().strip() for k in SAP_KEYWORDS)


def _tokenize(text: str) -> list[str]:
    """Extrae tokens alfanuméricos de 3+ caracteres, minúsculas."""
    return [
        w
        for w in re.findall(r"[a-záéíóúñü0-9/\-]{3,}", text.lower())
        if w not in _STOP_WORDS and len(w) >= 3
    ]


def _fetch_recent_texts(days: int = 30) -> list[str]:
    """Obtiene títulos y descripciones de licitaciones de los últimos N días."""
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with connect() as c:
        cur = c.execute(
            "SELECT titulo, descripcion FROM licitaciones WHERE fecha_publicacion >= %s",
            (since,),
        )
        texts = []
        for row in cur.fetchall():
            parts = [str(row[0] or ""), str(row[1] or "")]
            texts.append(" ".join(parts))
        return texts


def detect_drift(
    *,
    days: int = 30,
    min_doc_freq: int = 3,
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """Detecta términos emergentes no presentes en SAP_KEYWORDS.

    Args:
        days: Ventana de análisis en días.
        min_doc_freq: Frecuencia mínima de documentos para considerar un término.
        top_n: Número máximo de candidatos a devolver.

    Returns:
        Lista de dicts con {term, doc_freq, example_titles} ordenados por frecuencia desc.
    """
    texts = _fetch_recent_texts(days)
    if not texts:
        log.info("concept_drift.no_texts", days=days)
        return []

    # Contar frecuencia de documento (en cuántos docs aparece cada término)
    doc_freq: Counter[str] = Counter()
    # Para extraer ejemplos
    term_examples: dict[str, list[str]] = {}

    for text in texts:
        tokens = set(_tokenize(text))
        for tok in tokens:
            doc_freq[tok] += 1
            if tok not in term_examples:
                term_examples[tok] = []
            if len(term_examples[tok]) < 3:
                title = text[:120]
                term_examples[tok].append(title)

    # Filtrar: solo términos NO conocidos, con freq >= min_doc_freq
    candidates = []
    for term, freq in doc_freq.most_common():
        if freq < min_doc_freq:
            break
        # Ignorar si es un término conocido o parte de uno
        if term in _KNOWN_TERMS:
            continue
        if any(term in known for known in _KNOWN_TERMS):
            continue

        candidates.append(
            {
                "term": term,
                "doc_freq": freq,
                "example_titles": term_examples.get(term, []),
            }
        )
        if len(candidates) >= top_n:
            break

    log.info("concept_drift.detected", n_candidates=len(candidates), days=days)
    return candidates


def run_drift_report(*, days: int = 30, send_alert: bool = True) -> list[dict[str, Any]]:
    """Ejecuta el análisis de drift y opcionalmente envía alerta por email.

    Diseñado para ejecutarse como tarea del scheduler (mensual).
    """
    candidates = detect_drift(days=days)
    if not candidates:
        log.info("concept_drift.no_drift", days=days)
        return []

    if send_alert:
        lines = [
            f"Se han detectado {len(candidates)} términos emergentes en las "
            f"licitaciones de los últimos {days} días que NO están en SAP_KEYWORDS:\n"
        ]
        for c in candidates:
            lines.append(f"  • **{c['term']}** ({c['doc_freq']} docs)")
            if c["example_titles"]:
                lines.append(f"    Ejemplo: {c['example_titles'][0][:100]}")
        lines.append("\nRevisa si alguno debería añadirse a SAP_KEYWORDS en config.py.")
        body = "\n".join(lines)
        notify(
            AlertLevel.WARN,
            "Concept Drift — Términos emergentes detectados",
            body,
        )

    return candidates


# ────────────────────────── C1: Active learning loop ───────────────────────


_RETRAIN_FEEDBACK_THRESHOLD = 50


def maybe_retrain_classifier(
    *, threshold: int = _RETRAIN_FEEDBACK_THRESHOLD, dry_run: bool = False
) -> dict[str, Any]:
    """Re-entrena el clasificador si hay suficientes feedbacks nuevos (C1).

    Cuenta cuántas filas en ``ml_feedback`` son posteriores al ``trained_at``
    de la versión activa registrada. Si supera ``threshold``, dispara
    re-entrenamiento, registra la nueva versión en el model registry y la
    activa automáticamente.

    Args:
        threshold: Mínimo de feedbacks nuevos para disparar el retrain.
        dry_run: Si True, solo reporta sin entrenar.

    Returns:
        Dict con ``triggered``, ``feedbacks_new``, ``new_version`` (si aplica).
    """
    from db.model_registry import (
        feedbacks_since_last_train,
        get_active,
        register_version,
    )

    name = "sap_classifier"
    n_new = feedbacks_since_last_train(name)
    active = get_active(name)
    result: dict[str, Any] = {
        "triggered": False,
        "feedbacks_new": n_new,
        "threshold": threshold,
        "current_version": active["version"] if active else None,
    }

    if n_new < threshold:
        log.info("active_learning.below_threshold", n_new=n_new, threshold=threshold)
        return result

    if dry_run:
        log.info("active_learning.dry_run", n_new=n_new)
        result["triggered"] = True
        result["dry_run"] = True
        return result

    # Re-entrenar
    try:
        from pathlib import Path

        from scraper.ml_classifier import SAPClassifier
        from scraper.ml_training import precompute_ml_proba

        df = _fetch_training_dataframe()
        if df is None or df.empty:
            log.warning("active_learning.no_data")
            return result

        clf = SAPClassifier()
        metrics = clf.train(df)  # train() acepta df directamente

        if "error" in metrics:
            log.warning("active_learning.train_failed", metrics=metrics)
            result["error"] = metrics.get("error")
            return result

        next_version = (active["version"] if active else 0) + 1
        version_path = Path("data/models") / f"{name}_v{next_version}.pkl"
        saved = clf.save(version_path)

        import hashlib

        sha = hashlib.sha256(saved.read_bytes()).hexdigest()

        n_samples = metrics.get("n_train", 0) + metrics.get("n_test", 0)

        # Promotion gate: multi-metric check (F1, PR-AUC, Brier score)
        new_f1 = float(metrics.get("f1") or 0.0)
        old_metrics = (active or {}).get("metrics", {}) if active else {}
        old_f1 = float(old_metrics.get("f1") or 0.0)

        new_pr_auc = float(metrics.get("pr_auc") or 0.0)
        old_pr_auc = old_metrics.get("pr_auc")

        new_brier = float(metrics.get("brier") or 1.0)
        old_brier = old_metrics.get("brier")

        # Log all metrics comparison
        log.info(
            "active_learning.promotion_gate_comparison",
            old_f1=round(old_f1, 4),
            new_f1=round(new_f1, 4),
            old_pr_auc=round(float(old_pr_auc), 4) if old_pr_auc is not None else None,
            new_pr_auc=round(new_pr_auc, 4),
            old_brier=round(float(old_brier), 4) if old_brier is not None else None,
            new_brier=round(new_brier, 4),
        )

        failed_metrics: list[str] = []

        # F1 gate
        if old_f1 > 0.0 and new_f1 < old_f1 - 0.02:
            failed_metrics.append(f"f1 ({new_f1:.4f} < {old_f1:.4f} - 0.02)")

        # PR-AUC gate
        if old_pr_auc is not None:
            old_pr_auc_f = float(old_pr_auc)
            if new_pr_auc < old_pr_auc_f - 0.03:
                failed_metrics.append(f"pr_auc ({new_pr_auc:.4f} < {old_pr_auc_f:.4f} - 0.03)")
        else:
            log.warning(
                "active_learning.promotion_gate_skip_pr_auc",
                reason="metric not available in previous model",
            )

        # Brier score gate (lower is better)
        if old_brier is not None:
            old_brier_f = float(old_brier)
            if new_brier > old_brier_f + 0.05:
                failed_metrics.append(f"brier ({new_brier:.4f} > {old_brier_f:.4f} + 0.05)")
        else:
            log.warning(
                "active_learning.promotion_gate_skip_brier",
                reason="metric not available in previous model",
            )

        should_activate = (old_f1 == 0.0 and old_pr_auc is None and old_brier is None) or len(
            failed_metrics
        ) == 0
        if not should_activate:
            log.warning(
                "active_learning.promotion_gate_rejected",
                failed_metrics=failed_metrics,
                new_f1=round(new_f1, 4),
                old_f1=round(old_f1, 4),
            )
            result["promotion_rejected"] = True
            result["new_f1"] = new_f1
            result["old_f1"] = old_f1
            result["failed_metrics"] = failed_metrics
            return result

        new_version = register_version(
            name=name,
            path=str(saved),
            sha256=sha,
            metrics=metrics,
            n_samples=n_samples,
            n_feedbacks=n_new,
            notes="active_learning_auto_retrain",
            activate=True,
        )
        result["triggered"] = True
        result["new_version"] = new_version
        result["metrics"] = metrics
        log.info("active_learning.retrain_ok", new_version=new_version, n_new=n_new)

        notify(
            AlertLevel.INFO,
            f"Active learning: clasificador re-entrenado (v{new_version})",
            f"Re-entrenamiento disparado por {n_new} feedbacks nuevos.\n"
            f"Métricas: pr_auc={metrics.get('pr_auc')}, f1={metrics.get('f1')}, "
            f"threshold={metrics.get('optimal_threshold')}",
        )

        # Pre-computar ml_proba para todas las licitaciones con el nuevo modelo
        try:
            precompute_ml_proba(force=False)
        except Exception as precomp_exc:
            log.warning("active_learning.precompute_failed", error=str(precomp_exc))

    except Exception as exc:
        log.error("active_learning.retrain_failed", error=str(exc), exc_info=True)
        result["error"] = str(exc)

    return result


def _fetch_training_dataframe() -> Any:
    """Construye un DataFrame con licitaciones + feedbacks para entrenamiento.

    Incluye raw_keywords, cpv, importe y fecha_publicacion para que
    _build_dataset() en ml_classifier.py pueda usar todos los features
    disponibles (CPV tokens, importe bins, split temporal).
    Enriquece las etiquetas con feedback humano de ml_feedback.
    """
    try:
        import pandas as pd
    except ImportError:
        return None

    with connect() as c:
        lic = pd.read_sql_query(
            "SELECT id_externo, titulo, descripcion, raw_keywords, cpv, "
            "importe, fecha_publicacion, tecnologia "
            "FROM licitaciones",
            c,
        )
        fb = pd.read_sql_query("SELECT expediente, relevante FROM ml_feedback", c)
    if lic.empty:
        return None

    # Etiqueta base: raw_keywords notna OR tecnología detectada
    lic["es_relevante"] = (
        (lic["raw_keywords"].notna() & (lic["raw_keywords"] != ""))
        | ((lic["tecnologia"].notna()) & (lic["tecnologia"] != ""))
    ).astype(int)

    # Sobreescribir con feedback humano explícito (mayor prioridad)
    if not fb.empty:
        fb_map = dict(zip(fb["expediente"], fb["relevante"], strict=False))
        lic["es_relevante"] = lic.apply(
            lambda r: (
                int(fb_map[r["id_externo"]]) if r["id_externo"] in fb_map else r["es_relevante"]
            ),
            axis=1,
        )
    return lic


# ────────────────── PSI — Population Stability Index ───────────────────────


def compute_psi(
    *,
    feature: str = "importe",
    ref_days: int = 90,
    cur_days: int = 7,
    n_bins: int = 10,
    eps: float = 1e-6,
) -> float:
    """Calcula el Population Stability Index (PSI) para una feature numérica.

    Compara la distribución de ``feature`` en la ventana de referencia
    (``ref_days`` días antes de la ventana actual) contra la ventana actual
    (``cur_days`` días).  Un PSI < 0.10 es estable; 0.10-0.25 requiere
    seguimiento; > 0.25 indica drift significativo.

    Args:
        feature:  Columna numérica de la tabla ``licitaciones``.
        ref_days: Tamaño de la ventana de referencia (días).
        cur_days: Tamaño de la ventana actual (días).
        n_bins:   Número de bins para discretizar.
        eps:      Pequeño valor para evitar log(0).

    Returns:
        PSI como float. Devuelve 0.0 si no hay datos suficientes.
    """

    try:
        import numpy as np
    except ImportError:
        log.warning("compute_psi_numpy_unavailable")
        return 0.0

    try:
        from services.licitaciones import load_drift_window

        ref_rows = load_drift_window(ref_days, offset_days=cur_days)
        cur_rows = load_drift_window(cur_days)
    except Exception as exc:
        log.warning("compute_psi_load_failed", error=str(exc))
        return 0.0

    if not ref_rows or not cur_rows:
        return 0.0

    ref_vals = np.array(
        [r.get(feature) for r in ref_rows if r.get(feature) is not None], dtype=float
    )
    cur_vals = np.array(
        [r.get(feature) for r in cur_rows if r.get(feature) is not None], dtype=float
    )

    if len(ref_vals) < 10 or len(cur_vals) < 5:
        return 0.0

    # Calcular bins sobre la distribución de referencia
    bin_edges = np.percentile(ref_vals, np.linspace(0, 100, n_bins + 1))
    # Evitar bins duplicados en percentiles
    bin_edges = np.unique(bin_edges)
    if len(bin_edges) < 2:
        return 0.0

    ref_counts, _ = np.histogram(ref_vals, bins=bin_edges)
    cur_counts, _ = np.histogram(cur_vals, bins=bin_edges)

    ref_pct = ref_counts / ref_counts.sum()
    cur_pct = cur_counts / cur_counts.sum()

    # Aplicar eps para evitar log(0)
    ref_pct = np.where(ref_pct == 0, eps, ref_pct)
    cur_pct = np.where(cur_pct == 0, eps, cur_pct)

    psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
    log.debug(
        "compute_psi_result",
        feature=feature,
        psi=round(psi, 4),
        ref_n=len(ref_vals),
        cur_n=len(cur_vals),
    )
    return max(0.0, psi)
