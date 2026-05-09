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
            "SELECT titulo, descripcion FROM licitaciones WHERE fecha_publicacion >= ?",
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
            "Concept Drift — Términos emergentes detectados",
            body,
            level=AlertLevel.WARN,
        )

    return candidates
