"""Concept drift detector — detecta términos emergentes no cubiertos por SAP_KEYWORDS.

Analiza licitaciones recientes usando TF-IDF para encontrar términos frecuentes
que no están en el vocabulario conocido (SAP_KEYWORDS). Estos términos candidatos
pueden indicar nuevas tecnologías, módulos o servicios SAP que deberían añadirse
a la configuración.
"""

from __future__ import annotations

import os
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
        # Fuera del análisis el universo CPV sin señal (``cpv_ti_universe``):
        # el detector busca términos emergentes entre lo que el diccionario ya
        # acepta, y meter todo el CPV 48/72 sólo lo llenaría de vocabulario
        # genérico de TI («mantenimiento», «licencias») que no es deriva.
        cur = c.execute(
            "SELECT titulo, descripcion FROM licitaciones WHERE fecha_publicacion >= %s "
            "AND COALESCE(inclusion_reason, '') <> 'cpv_ti_universe'",
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


def _plano_declarado() -> str:
    """Valor de ``SCHEDULER_PLANE``, o cadena vacía si nadie lo puso.

    Solo se usa para decir en el aviso desde dónde se intentó: ningún plano
    entrena en proceso (ver :func:`maybe_retrain_classifier`).
    """
    return os.environ.get("SCHEDULER_PLANE", "").strip()


#: Workflow que entrena, publica el artefacto en la Release y activa la versión.
_WORKFLOW_ENTRENAMIENTO = "train-model.yml"


def _lanzar_entrenamiento() -> bool:
    """Encola ``train-model.yml`` por ``workflow_dispatch``. ``True`` si se aceptó.

    Solo puede funcionar dentro de GitHub Actions, que es donde existen las
    tres variables: ``GITHUB_TOKEN`` (el step tiene que exportarlo, y el
    workflow darle ``actions: write``), ``GITHUB_REPOSITORY`` y
    ``GITHUB_REF_NAME``. Se lanza sobre la misma rama que está corriendo, que en
    la pasada programada es la rama por defecto. Fuera de Actions —el worker de
    Render, el scheduler de Compose, un checkout local— falta alguna y devuelve
    ``False``.
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    ref = os.environ.get("GITHUB_REF_NAME", "")
    if not (token and repo and ref):
        return False
    from shared.github_actions import dispatch_workflow

    return dispatch_workflow(repo, _WORKFLOW_ENTRENAMIENTO, ref=ref, token=token)


def maybe_retrain_classifier(
    *, threshold: int = _RETRAIN_FEEDBACK_THRESHOLD, dry_run: bool = False
) -> dict[str, Any]:
    """Lanza el reentrenamiento del clasificador si hay feedback nuevo (C1).

    Cuenta cuántas filas de feedback humano en ``ml_feedback`` son posteriores
    al ``trained_at`` de la **última versión registrada**, esté activa o no.
    Si supera ``threshold``, lanza ``train-model.yml`` —el único camino que
    entrena, publica el artefacto en la Release y solo entonces activa— y, si
    no puede lanzarlo, avisa con el comando exacto.

    Desde la última registrada y no desde la activa: un candidato que el gate
    rechazó ya se entrenó con esas etiquetas, y reentrenar cada semana con las
    mismas solo repite el rechazo.

    **No entrena ni toca el registro, en ningún plano.** Hasta 2026-10, sin
    ``SCHEDULER_PLANE`` declarado, entrenaba aquí con su propio dataset
    (``licitaciones`` entera, sin la población acotada de ``train_from_db``) y
    activaba la versión en el acto; con plano declarado ya solo lanzaba el
    workflow. Eran dos caminos de entrenamiento con datasets distintos, y el
    de aquí era el que el 2026-09-29 dejó activa en ``model_versions`` una v2
    cuyo ``.pkl`` nadie publicó: ``ml_scoring`` cayó por
    ``ModelArtifactMismatch`` en cada pasada. Un checkout local tampoco es
    excepción: lo que escribe en su ``data/models/`` no llega a la API ni a los
    runners que leen la misma BD.

    Args:
        threshold: Mínimo de feedbacks nuevos para disparar el retrain.
        dry_run: Si True, solo reporta sin lanzar nada.

    Returns:
        Dict con ``triggered`` (siempre ``False`` salvo en ``dry_run``: aquí no
        se entrena), ``feedbacks_new``, ``retrain_lanzado`` cuando se encoló
        ``train-model.yml`` y ``retrain_pendiente`` cuando tocaba reentrenar y
        solo se pudo avisar.
    """
    from db.model_registry import feedbacks_since_last_train, get_active

    name = "sap_classifier"
    n_new = feedbacks_since_last_train(name, desde_ultimo_registro=True)
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

    if _lanzar_entrenamiento():
        log.info("active_learning.retrain_lanzado", n_new=n_new, threshold=threshold)
        result["retrain_lanzado"] = True
        notify(
            AlertLevel.INFO,
            "Active learning: reentrenamiento del clasificador SAP lanzado",
            f"Hay {n_new} feedbacks humanos desde el último entrenamiento "
            f"(umbral: {threshold}), así que se lanzó {_WORKFLOW_ENTRENAMIENTO}.\n"
            "Entrena, pasa el gate de promoción y, si lo supera, publica el "
            "artefacto y activa la versión. El desenlace está en ese workflow.",
        )
        return result

    plano = _plano_declarado() or "sin SCHEDULER_PLANE"
    log.warning(
        "active_learning.retrain_pendiente",
        n_new=n_new,
        threshold=threshold,
        plano=plano,
    )
    result["retrain_pendiente"] = True
    notify(
        AlertLevel.WARN,
        "Active learning: toca reentrenar el clasificador SAP",
        f"Hay {n_new} feedbacks humanos desde el último entrenamiento "
        f"(umbral: {threshold}).\n"
        f"Este proceso ({plano}) no ha podido lanzar {_WORKFLOW_ENTRENAMIENTO} "
        "y no reentrena por su cuenta: una versión activa sin artefacto "
        "publicado deja sin modelo a todos los procesos.\n"
        f"Lanzá el workflow que entrena y publica: gh workflow run {_WORKFLOW_ENTRENAMIENTO}",
    )
    return result


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
