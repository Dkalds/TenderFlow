"""Entrenamiento del clasificador multi-tecnología — entrypoint del workflow.

Invocado por ``.github/workflows/train-tech.yml``. Cierra el hueco más ancho
del subsistema ML: ``data/models/tech_classifier.pkl`` no lo producía ningún
workflow —solo el subcomando local ``python -m scraper.ml_classifier
train-tech``— y ``TechnologyClassifier`` ni siquiera tenía ``ensure_downloaded``,
así que ``precompute_ml_tecnologias`` salía ``no_model`` en **todas** las
pasadas de ``scrape-daily.yml`` desde que el paso existe.

Gate de publicación: etiquetas no circulares
--------------------------------------------
``TechnologyClassifier.train`` resuelve la etiqueta **por licitación** con la
prioridad ``tecnologia_humana`` > ``tecnologia_llm`` > ``licitaciones.tecnologia``.
Esa última la escriben los conectores con ``matches_technology()`` sobre el
mismo texto que después ve el modelo, así que entrenar contra ella es enseñarle
a reproducir un regex que ya tenemos (ver el docstring de
``scraper/tech_classifier.py``).

El flag ``labels_circulares`` que emite ``train`` **no basta como gate**: se
apaga en cuanto UNA fila trae etiqueta independiente. Con las 33 de producción
(2026-09-03) y ~1.400 filas resueltas por keywords, saldría ``False`` sobre un
modelo que es el regex con un redondeo humano encima. El gate real es un suelo
absoluto: ``ML_TECH_MIN_POS_READY`` etiquetas independientes, que es el número
de positivos que ``train`` exige para promover una tecnología al tier
``ml_ready``. Por debajo de ese total NINGUNA puede alcanzarlo con datos no
circulares, así que todo tier ``ml_ready`` que salga estaría certificado por
filas de keywords. Es una cota **necesaria, no suficiente**: la proporción real
va en ``pct_keywords``, para que la juzgue quien mire el run.

Publicar un modelo circular sería peor que no publicar.
``precompute_ml_tecnologias`` sobreescribe
``ml_tecnologias``/``ml_proba_max``/``ml_tech_principal`` en toda fila con
``ml_proba_max IS NULL``: serviría el regex pisando la señal de pliego que
``tech_signal_merge`` acaba de fundir sobre esas mismas columnas.

Por eso el job **ni siquiera entrena** cuando el suelo no se alcanza: el corpus
son ~700k licitaciones y entrenar para tirar el resultado cuesta media hora de
runner y arriesga el OOM, sin aportar ni diagnóstico (las métricas de un modelo
circular no significan nada).

No se registra en ``model_versions`` a propósito: ``TechnologyClassifier.load``
no consulta el registry (sirve el artefacto local, verificado contra su
``.sha256`` co-ubicado), así que una fila ``is_active`` ahí sería un metadato
decorativo. El repo ya arrastra una de esas —``baja_model`` v1, con un ``path``
de un runner efímero que murió— y es exactamente el error que documenta
``scheduler/pipeline_runs.py`` al sacar ``ml_retrain`` de la pipeline.
"""

from __future__ import annotations

import os
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

MOTIVO_SIN_ETIQUETAS = "sin_etiquetas_independientes"


def umbral_etiquetas_independientes() -> int:
    """Suelo de etiquetas no circulares para que entrenar signifique algo.

    Ver el gate del docstring del módulo: es ``ML_TECH_MIN_POS_READY``, no un
    número nuevo.
    """
    from config import settings

    return int(getattr(settings, "ML_TECH_MIN_POS_READY", 50))


def contar_etiquetas_independientes() -> int:
    """Licitaciones sobre las que se pronunció una fuente **no** circular.

    Cuenta igual que ``_resolver_label_column``: una cadena vacía es un
    pronunciamiento ("ninguna tecnología") y un negativo válido; solo ``None``
    significa que la fuente no se pronunció.
    """
    from db.repositories.licitaciones import LicitacionRepository

    externas = LicitacionRepository().etiquetas_tecnologia_no_circulares()
    return sum(
        1
        for fuentes in externas.values()
        if fuentes.get("tecnologia_humana") is not None or fuentes.get("tecnologia_llm") is not None
    )


def run() -> dict[str, Any]:
    """Entrena el ``TechnologyClassifier`` desde la BD y devuelve sus métricas.

    Si no hay etiquetas independientes suficientes devuelve un dict con
    ``skipped`` y **no entrena**: el resultado se descartaría igual y el corpus
    es demasiado grande para gastarlo en un diagnóstico que no significa nada.

    Raises:
        RuntimeError: si el entrenamiento devuelve un dict con ``error``.
    """
    from scraper.tech_classifier import train_from_db

    umbral = umbral_etiquetas_independientes()
    n_independientes = contar_etiquetas_independientes()
    if n_independientes < umbral:
        log.warning(
            "tech_training_sin_etiquetas_independientes",
            n_etiquetas_independientes=n_independientes,
            umbral=umbral,
        )
        return {
            "skipped": MOTIVO_SIN_ETIQUETAS,
            "n_etiquetas_independientes": n_independientes,
            "umbral_etiquetas_independientes": umbral,
        }

    metrics = train_from_db()
    metrics["n_etiquetas_independientes"] = n_independientes
    metrics["umbral_etiquetas_independientes"] = umbral
    log.info(
        "tech_training_metrics",
        **{k: v for k, v in metrics.items() if k != "per_tech"},
    )
    if "error" in metrics:
        raise RuntimeError(f"Training failed: {metrics['error']}")
    return metrics


def etiquetas_independientes_usadas(metrics: dict[str, Any]) -> int:
    """Filas que el entrenamiento resolvió con una fuente no circular."""
    counts = metrics.get("label_source_counts") or {}
    return int(counts.get("human", 0)) + int(counts.get("llm", 0))


def pct_keywords(metrics: dict[str, Any]) -> float | None:
    """% de las filas etiquetadas que salió del regex. El dato que hay que mirar."""
    counts = metrics.get("label_source_counts") or {}
    keywords = int(counts.get("keywords", 0))
    total = keywords + etiquetas_independientes_usadas(metrics)
    if total == 0:
        return None
    return round(keywords / total * 100, 2)


def publicable(metrics: dict[str, Any]) -> bool:
    """¿El artefacto entrenado merece llegar a la Release?

    Un rechazo no es un fallo: es el gate haciendo su trabajo.
    """
    if metrics.get("skipped") or metrics.get("error"):
        return False
    if bool(metrics.get("labels_circulares")):
        return False
    if int(metrics.get("n_models") or 0) <= 0:
        return False
    return etiquetas_independientes_usadas(metrics) >= umbral_etiquetas_independientes()


def motivo_rechazo(metrics: dict[str, Any]) -> str:
    """Frase corta para el step summary. Vacía si el modelo es publicable."""
    if publicable(metrics):
        return ""
    if metrics.get("skipped") == MOTIVO_SIN_ETIQUETAS:
        return (
            f"solo {metrics.get('n_etiquetas_independientes')} etiquetas independientes, "
            f"hacen falta {metrics.get('umbral_etiquetas_independientes')}; no se entrenó"
        )
    if bool(metrics.get("labels_circulares")):
        return "todas las etiquetas salen del regex de matches_technology()"
    if int(metrics.get("n_models") or 0) <= 0:
        return "ninguna tecnología llegó al tier ml_ready; solo quedan reglas"
    return (
        f"solo {etiquetas_independientes_usadas(metrics)} filas se resolvieron con una fuente "
        f"independiente, hacen falta {umbral_etiquetas_independientes()}"
    )


def artefactos(metrics: dict[str, Any]) -> list[str]:
    """Rutas a publicar, o lista vacía si el gate rechazó.

    El ``.sha256`` va con el ``.pkl`` y no es opcional: con ``ENV=prod``,
    ``verify_model_integrity`` rechaza deserializar un artefacto que llegue sin
    checksum co-ubicado ni pin ``ML_TECH_MODEL_SHA256``.
    """
    if not publicable(metrics):
        return []
    from scraper.tech_classifier import _MODEL_PATH

    return [str(_MODEL_PATH), str(_MODEL_PATH.with_suffix(".sha256"))]


def _emitir_salida_github(metrics: dict[str, Any]) -> None:
    """Escribe el desenlace en ``$GITHUB_OUTPUT`` para que el workflow decida.

    Mismo contrato que ``scheduler/jobs/ml_training_run.py``: sin esto el YAML
    no puede distinguir «el gate rechazó» de «el entrenamiento reventó», que en
    disco se parecen (en los dos casos no hay artefacto nuevo que subir).
    """
    destino = os.environ.get("GITHUB_OUTPUT")
    if not destino:
        return
    lineas = [
        f"publicable={'true' if publicable(metrics) else 'false'}",
        f"artefactos={' '.join(artefactos(metrics))}",
        f"motivo={motivo_rechazo(metrics)}",
        f"n_etiquetas_independientes={metrics.get('n_etiquetas_independientes', '')}",
        f"umbral={metrics.get('umbral_etiquetas_independientes', '')}",
        f"pct_keywords={pct_keywords(metrics) if pct_keywords(metrics) is not None else ''}",
        f"n_models={metrics.get('n_models', '')}",
        f"n_samples={metrics.get('n_samples', '')}",
        f"macro_f1_all_labels={metrics.get('macro_f1_all_labels', '')}",
    ]
    with open(destino, "a", encoding="utf-8") as fh:
        fh.write("\n".join(str(linea).replace("\n", " ") for linea in lineas) + "\n")


if __name__ == "__main__":
    import sys

    try:
        _metrics = run()
    except RuntimeError as exc:
        log.error("tech_training_failed", error=str(exc))
        sys.exit(1)

    _emitir_salida_github(_metrics)
    if not publicable(_metrics):
        # Salida 0 a propósito, igual que en el gate del clasificador SAP: el
        # job terminó bien y el gate decidió. Marcarlo en rojo enseñaría a
        # ignorar los rojos; el workflow deja el motivo en el step summary.
        log.warning("tech_training_no_publicable", motivo=motivo_rechazo(_metrics))
