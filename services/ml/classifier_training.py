"""Utilidades de entrenamiento y operaciones sobre la BD para el clasificador SAP.

Contiene:
  - ``_append_to_registry()`` / ``read_registry()`` — histórico de entrenamientos
  - ``train_from_db()`` — orquesta entrenamiento completo desde la BD
  - ``precompute_ml_proba()`` — pre-computa ml_proba para todas las licitaciones
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from observability.logging import get_logger

if TYPE_CHECKING:
    import pandas as pd

log = get_logger(__name__)

# Ruta del registro de entrenamientos (histórico de runs).
_MODEL_DIR = Path(__file__).parents[2] / "data" / "models"
_REGISTRY_PATH = _MODEL_DIR / "registry.json"


def _append_to_registry(entry: dict[str, Any], path: Path | None = None) -> Path:
    """Añade una entrada al registro de entrenamientos JSON (lista append-only).

    El registro permite:
      - Visualizar la evolución de métricas en el tiempo.
      - Detectar regresiones automáticamente (comparar último vs penúltimo).
      - Auditar qué modelo está en producción.
    """
    target = path or _REGISTRY_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    history: list[dict[str, Any]] = []
    if target.exists():
        try:
            raw = target.read_text(encoding="utf-8")
            if raw.strip():
                history = json.loads(raw)
            if not isinstance(history, list):
                history = []
        except json.JSONDecodeError:
            history = []
    history.append(dict(entry))
    target.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def read_registry(path: Path | None = None) -> list[dict[str, Any]]:
    """Lee el histórico de entrenamientos como lista de dicts (vacía si no existe)."""
    target = path or _REGISTRY_PATH
    if not target.exists():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def etiquetar_dataset_sap(lic: pd.DataFrame, feedback: list[dict[str, Any]]) -> pd.DataFrame:
    """Añade ``es_relevante`` al DataFrame de entrenamiento del clasificador SAP.

    Usa las MISMAS etiquetas que el reentrenamiento semanal
    (``scheduler.concept_drift._fetch_training_dataframe``): etiqueta base por
    keyword/tecnología, SOBRESCRITA por el feedback humano de ``ml_feedback``.
    La lógica se replica aquí (no se importa desde ``scheduler`` para no
    invertir capas: ``services`` es capa inferior).

    Función aparte de :func:`train_from_db` para poder ejercitarla con un
    DataFrame en un test unitario, sin BD.
    """
    if lic.empty:
        return lic
    # Etiqueta base: raw_keywords no vacío OR tecnología detectada.
    lic = lic.copy()
    lic["es_relevante"] = (
        (lic["raw_keywords"].notna() & (lic["raw_keywords"] != ""))
        | (lic["tecnologia"].notna() & (lic["tecnologia"] != ""))
    ).astype(int)
    # Sobrescribir con feedback humano explícito (mayor prioridad).
    fb_map = {fila["expediente"]: fila["relevante"] for fila in feedback}
    if fb_map:
        lic["es_relevante"] = [
            int(fb_map[ident]) if ident in fb_map else int(etiqueta)
            for ident, etiqueta in zip(lic["id_externo"], lic["es_relevante"], strict=False)
        ]
    return lic


def resumen_poblacion_sap(lic: pd.DataFrame) -> dict[str, Any]:
    """Describe la población de entrenamiento para el registro del modelo.

    Se guarda en ``model_versions.metrics_json`` bajo ``train_population``: sin
    esto, dos versiones entrenadas sobre poblaciones distintas son
    indistinguibles en el registro, que es justo la comparación que hay que
    poder hacer después de acotar (backlog P2).
    """
    from db.repositories.ml_dataset import POBLACION_SAP_UNIVERSOS, TRAIN_POPULATION_SAP

    n_filas = len(lic)
    tiene_etiqueta = n_filas > 0 and "es_relevante" in lic.columns
    n_positivos = int(lic["es_relevante"].sum()) if tiene_etiqueta else 0
    return {
        "nombre": TRAIN_POPULATION_SAP,
        "universos": list(POBLACION_SAP_UNIVERSOS),
        "n_filas": n_filas,
        "n_positivos": n_positivos,
        "pct_positivos": round(100.0 * n_positivos / n_filas, 2) if n_filas else 0.0,
    }


def train_from_db(*, activar: bool = True) -> dict[str, Any]:
    """Entrena el clasificador usando datos de la BD activa y lo guarda.

    ``activar=False`` es para quien todavía tiene que publicar el artefacto
    (``scheduler/jobs/ml_training_run.py``, el entrypoint de
    ``train-model.yml``): el candidato que pasa el gate queda registrado sin
    activar, y ``metrics["promotion"]`` lo dice con ``pendiente_de_activar``.

    **Población acotada (S6.1).** El dataset ya no es ``licitaciones`` entera:
    son las fuentes cuyo conector filtró por señal tecnológica antes de
    persistir (``db.repositories.ml_dataset.filas_entrenamiento_sap``). El
    corpus completo dejaba la clase minoritaria en 1,14 % y
    ``validate_training_data`` abortaba; el motivo y la elección están
    documentados junto al predicado, en ``db/``. La población medida viaja al
    registro como ``train_population``.

    El gate de promoción (``services.ml.promotion``) decide si el candidato
    llega a sobrescribir el artefacto que sirve producción.
    """
    import pandas as pd

    from db.database import init_db
    from db.repositories.ml_dataset import feedback_humano_es_ti, filas_entrenamiento_sap
    from services.ml.classifier_pipeline import validate_training_data
    from services.ml.sap_classifier import SAPClassifier

    init_db()
    filas = filas_entrenamiento_sap()
    if not filas:
        # Sin filas no hay ni DataFrame con columnas que validar: se corta aquí
        # con el mismo código de error que devolvería ``train``.
        log.warning("train_from_db.poblacion_vacia")
        return {"error": "insufficient_data", "n_samples": 0}
    lic = etiquetar_dataset_sap(pd.DataFrame(filas), feedback_humano_es_ti())
    train_population = resumen_poblacion_sap(lic)
    log.info("train_from_db.poblacion", **train_population)

    # El validador es la puerta que rechazó el dataset ahogado; se ejecuta
    # aquí, en el camino que produce el asset de la Release, y no solo en el
    # semanal. Un ValueError suyo es un desenlace legítimo —el dataset no da
    # para entrenar— y se devuelve como ``error`` en vez de tumbar el job.
    try:
        validate_training_data(lic)
    except ValueError as exc:
        log.warning("train_from_db.dataset_invalido", error=str(exc), **train_population)
        return {
            "error": "dataset_invalido",
            "detalle": str(exc),
            "train_population": train_population,
        }

    # Con ``lic`` vacío el clasificador devuelve ``{"error": ...}`` y no se
    # guarda (mismo comportamiento que antes: train decide, no un early-return).
    clf = SAPClassifier()
    metrics = clf.train(lic)
    metrics["train_population"] = train_population
    if "error" in metrics:
        return metrics

    # El artefacto de producción SOLO se sobrescribe si la versión nueva pasa
    # el gate. Antes este camino —el que genera el asset de la Release que
    # descargan la API y todos los runners— guardaba sin ninguna comprobación
    # y sin registrar versión, así que un entrenamiento con datos degradados
    # se promocionaba solo y no había versión previa a la que volver.
    from services.ml.promotion import promote_if_better

    resultado = promote_if_better(
        clf,
        metrics,
        name="sap_classifier",
        notes="train_from_db",
        models_dir=_MODEL_DIR,
        publicar_como=_MODEL_DIR / "sap_classifier.pkl",
        activar=activar,
    )
    promocion = resultado.as_dict()
    metrics["promotion"] = promocion
    if not (promocion.get("activada") or promocion.get("pendiente_de_activar")):
        log.warning(
            "train_from_db.no_promocionado",
            version=resultado.version,
            motivos=resultado.motivos_rechazo,
        )
    return metrics


def precompute_ml_proba(*, batch_size: int = 500, force: bool = False) -> dict[str, int]:
    """Pre-computa ``ml_proba`` para la **población del clasificador**.

    Actualiza la columna ``ml_proba`` con P(SAP) del clasificador actual.
    Por defecto solo procesa filas donde ``ml_proba IS NULL``; con ``force=True``
    recalcula todas.

    **Puntúa lo mismo que entrena (S6.1).** El corpus que llega a la columna es
    el de ``db.repositories.ml_dataset.filas_pendientes_ml_proba``, la misma
    población acotada de ``train_from_db``. Y antes de puntuar se borran los
    scores que quedaron fuera de ella: eran los del modelo de mayo sobre las
    683k filas de PSCP, que daba «SAP» a nueve de cada diez (backlog P2). Un
    score extrapolado a un corpus que el modelo nunca vio no es una predicción.

    Args:
        batch_size: Número de filas a procesar por batch (control de memoria).
        force: Si True, sobreescribe valores existentes.

    Returns:
        ``{"updated": N, "limpiadas_fuera_de_poblacion": M,
        "quedan_scores_por_limpiar": bool, "skipped_no_model": bool}``
    """
    from services.ml.classifier_pipeline import _augment_text
    from services.ml.sap_classifier import SAPClassifier

    # `resolve_artifact` y no `is_available`: el segundo es un `Path.exists()`
    # sobre `data/models/`, que está en .gitignore y viene vacío en el runner,
    # así que este paso salía en `no_model` **por construcción** en cada pasada
    # de la pipeline diaria -- con el artefacto publicado en la Release desde
    # mayo y nadie bajándolo. Ver `shared/model_artifacts.py`.
    artefacto = SAPClassifier.resolve_artifact()
    if artefacto is None:
        log.warning("precompute_ml_proba.no_model")
        return {"updated": 0, "limpiadas_fuera_de_poblacion": 0, "skipped_no_model": True}

    try:
        clf = SAPClassifier.load(artefacto)
    except Exception as exc:
        log.error("precompute_ml_proba.load_failed", error=str(exc))
        return {"updated": 0, "limpiadas_fuera_de_poblacion": 0, "skipped_no_model": True}

    from db.repositories.ml_dataset import (
        _LIMPIEZA_BATCH,
        filas_pendientes_ml_proba,
        guardar_ml_proba,
        limpiar_ml_proba_fuera_de_poblacion,
    )

    # Acotada por diseño (ver `_LIMPIEZA_BATCH`): la primera vez que esto corre
    # en producción hay ~600k scores heredados que borrar y no caben en una
    # transacción razonable. Que devuelva el tope significa «quedan más», y eso
    # se registra: una limpieza que va por su tercera corrida es información,
    # pero una que lleva veinte es que el borrado no converge y alguien tiene
    # que mirarlo.
    limpiadas = limpiar_ml_proba_fuera_de_poblacion()
    quedan_mas = limpiadas >= _LIMPIEZA_BATCH
    if limpiadas:
        log.info(
            "precompute_ml_proba.fuera_de_poblacion_limpiadas",
            n=limpiadas,
            quedan_mas=quedan_mas,
        )

    rows = filas_pendientes_ml_proba(force=force)
    if not rows:
        log.info("precompute_ml_proba.nothing_to_update")
        return {
            "updated": 0,
            "limpiadas_fuera_de_poblacion": limpiadas,
            "quedan_scores_por_limpiar": quedan_mas,
            "skipped_no_model": False,
        }

    from config import settings

    use_organo = bool(getattr(settings, "ML_USE_ORGANO_FEATURE", False))

    updated = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        texts = [
            _augment_text(
                (str(r["titulo"] or "") + " " + str(r["descripcion"] or "")).strip(),
                cpv=str(r["cpv"]) if r["cpv"] else None,
                importe=float(r["importe"]) if r["importe"] else None,
                organo=(
                    str(r["organo_contratacion"])
                    if (use_organo and r.get("organo_contratacion"))
                    else None
                ),
            )
            for r in batch
        ]
        try:
            probas = clf.pipeline.predict_proba(texts)[:, 1]
        except Exception as exc:
            log.error("precompute_ml_proba.predict_failed", batch_start=i, error=str(exc))
            continue

        updated += guardar_ml_proba(
            [
                (float(proba), str(row["id_externo"]))
                for row, proba in zip(batch, probas, strict=False)
            ]
        )

    log.info(
        "precompute_ml_proba.done",
        updated=updated,
        limpiadas=limpiadas,
        quedan_mas=quedan_mas,
    )
    return {
        "updated": updated,
        "limpiadas_fuera_de_poblacion": limpiadas,
        "quedan_scores_por_limpiar": quedan_mas,
        "skipped_no_model": False,
    }


def precompute_ml_tecnologias(*, batch_size: int = 500, force: bool = False) -> dict[str, Any]:
    """Puntúa el clasificador multi-tecnología y lo persiste en su única fuente.

    Escribe **solo** ``licitacion_tecnologia_score`` (un score por tecnología,
    modelo o fallback de reglas). ``ml_tecnologias``, ``ml_proba_max`` y
    ``ml_tech_principal`` no se tocan desde aquí: las deriva el trigger de
    ``v136`` a partir de esa tabla (T3 del plan v2, «Tecnología: una sola
    verdad»). Por defecto solo procesa filas donde ``ml_proba_max IS NULL``;
    con ``force=True`` recalcula todas.

    Args:
        batch_size: Número de filas por batch (control de memoria).
        force: Si True, sustituye las filas de score existentes.

    Returns:
        ``{"updated": N, "scores_inserted": M, "skipped_no_model": bool}``.
    """
    from services.ml.tech_classifier import TechnologyClassifier

    # Mismo motivo que en `precompute_ml_proba`: `is_available` es local.
    artefacto = TechnologyClassifier.resolve_artifact()
    if artefacto is None:
        log.warning("precompute_ml_tecnologias.no_model")
        return {"updated": 0, "scores_inserted": 0, "skipped_no_model": True}

    try:
        clf = TechnologyClassifier.load(artefacto)
    except Exception as exc:
        log.error("precompute_ml_tecnologias.load_failed", error=str(exc))
        return {"updated": 0, "scores_inserted": 0, "skipped_no_model": True}

    from db.repositories.ml_dataset import (
        filas_pendientes_ml_tecnologias,
        guardar_scores_tecnologia,
    )

    rows = filas_pendientes_ml_tecnologias(force=force)

    if not rows:
        log.info("precompute_ml_tecnologias.nothing_to_update")
        return {"updated": 0, "scores_inserted": 0, "skipped_no_model": False}

    updated = 0
    scores_inserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        items = [
            {
                "text": (str(r["titulo"] or "") + " " + str(r["descripcion"] or "")).strip(),
                "cpv": str(r["cpv"]) if r["cpv"] else None,
                "importe": float(r["importe"]) if r["importe"] else None,
            }
            for r in batch
        ]
        try:
            preds = clf.predict_batch(items)
        except Exception as exc:
            log.error(
                "precompute_ml_tecnologias.predict_failed",
                batch_start=i,
                error=str(exc),
            )
            continue

        score_params: list[tuple[str, str, float, float]] = []
        sin_score: list[tuple[float, str]] = []
        for row, pred in zip(batch, preds, strict=False):
            lic_id = str(row["id_externo"])
            filas_de_esta = 0
            for label, score in pred["scores"].items():
                if score <= 0.0:
                    continue
                thr = pred["thresholds"].get(label, 0.5)
                score_params.append((lic_id, label, float(score), float(thr)))
                filas_de_esta += 1
            if not filas_de_esta:
                # Puntuada y sin ninguna etiqueta > 0: sin fila de score el
                # trigger no tiene de dónde derivar ml_proba_max, y sin él la
                # pasada siguiente volvería a seleccionarla.
                sin_score.append((float(pred["max_proba"]), lic_id))
            scores_inserted += filas_de_esta

        guardar_scores_tecnologia(
            scores=score_params,
            sin_score=sin_score,
            reemplazar=[str(r["id_externo"]) for r in batch] if force else None,
        )
        updated += len(batch)
        log.debug(
            "precompute_ml_tecnologias.batch_done",
            batch_start=i,
            batch_size=len(batch),
            scores=len(score_params),
        )

    log.info(
        "precompute_ml_tecnologias.done",
        updated=updated,
        scores_inserted=scores_inserted,
    )
    return {
        "updated": updated,
        "scores_inserted": scores_inserted,
        "skipped_no_model": False,
    }
