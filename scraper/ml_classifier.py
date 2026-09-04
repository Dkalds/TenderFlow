"""Clasificador ML para detección de licitaciones SAP.

Complementa el filtro por keywords con un modelo FeatureUnion(TF-IDF word +
TF-IDF char_wb) + MaxAbsScaler + CalibratedClassifierCV(LogisticRegression)
entrenado sobre los propios datos de la base de datos.

Estrategia de etiquetado:
  - Positivos: licitaciones que ya pasaron el filtro de keywords (raw_keywords IS NOT NULL)
    o con es_relevante=1 por feedback humano.
  - Negativos: licitaciones con CPV fuera del rango TI/software (no 48xxx ni 72xxx)
    y sin keywords SAP — muestra balanceada automáticamente.

Features del pipeline:
  1. FeatureUnion: TF-IDF word (1,2) + TF-IDF char_wb (2,4) — captura sub-palabras
     como "S/4HANA", "netweaver" que word-tokenizer fragmenta incorrectamente.
  2. CPV e importe se codifican como tokens especiales (``_augment_text``) en
     entrenamiento **y** en los tres caminos de predicción, sin cambiar la API.
  3. ``precompute_ml_proba()`` actualiza la columna ``ml_proba`` en BD.

Cómo se evalúa (y por qué así)
------------------------------
El dataset se parte en tres, no en dos: **fit** (ajuste), **validación**
(elección del umbral y de la calibración) y **test** (las métricas que se
publican). Elegir el umbral donde se reportan las métricas las infla — medido
sobre el golden set: +0,08 de F-beta de media, +0,25 en el p90.

El corte es **por fecha, no por posición**, y respeta la integridad de grupo:
ningún expediente (sus lotes, sus prórrogas, sus republicaciones) puede
aparecer a los dos lados. Si hay fechas y ningún corte deja las dos clases a
ambos lados, ``train()`` devuelve ``error: temporal_split_impossible`` en vez de
caer a un split aleatorio: un aleatorio sobre datos temporales mide
interpolación, no predicción de licitaciones futuras, y publicarlo bajo los
mismos nombres de métrica es lo que hacía que las cifras del registry no
significaran lo que decían.

Las métricas se calculan sobre el pipeline **final** —después de la calibración
externa— para que ``brier``/``ece`` describan el modelo que de verdad se
serializa. ``f1_ti``/``pr_auc_ti`` las restringen a CPV 48/72, que es la única
población sobre la que el modelo decide en producción. ``metrics_reliable``
marca si el test da para sostener esas cifras; el gate de promoción
(``services.ml.promotion``) se niega a promocionar si no.

Las métricas internas miden cuánto **imita** el modelo al filtro de keywords,
porque de ahí salen las etiquetas. Lo que mide su valor real es
``recall_no_keyword`` sobre el golden set humano (``services.ml_eval``).

Uso:
    # Entrenar (una vez, o periódicamente):
    python -m scraper.ml_classifier train

    # En el pipeline (predicción):
    from scraper.ml_classifier import SAPClassifier
    clf = SAPClassifier.load()
    is_sap, confidence = clf.predict("Mantenimiento del sistema ERP corporativo")
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from config import settings
from observability.logging import get_logger
from scraper.ml_pipeline import (
    _augment_text,
    _expected_calibration_error,
    _make_pipeline,
    _make_pipeline_with_embeddings,
    _tune_pipeline,
)
from shared.model_integrity import verify_model_integrity, write_checksum
from shared.outbound_http import pinned_https_request

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt
    import pandas as pd

log = get_logger(__name__)

# Ruta del modelo serializado (formato joblib, extensión .pkl por compatibilidad)
_MODEL_PATH = Path(__file__).parents[1] / "data" / "models" / "sap_classifier.pkl"
_GITHUB_REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")

# Motivo de degradación cuando el artefacto de la versión activa del registry
# no está en esta máquina y se sirve el local, que puede ser anterior. Viaja en
# `SAPClassifier.serving_degradado` y sale por el `warning` de `explain()`: un
# `log.warning` en el contenedor no lo ve quien consume la API, y esta es
# justo la situación en la que las explicaciones que devuelve no son las del
# modelo que el registry dice estar sirviendo.
DEGRADACION_VERSION_MISMATCH = "serving_version_mismatch"
_AVISO_VERSION_MISMATCH = (
    "Degradado: el artefacto de la versión activa no está en esta máquina; "
    "esta explicación sale del modelo local, que puede ser anterior."
)

# Número mínimo de ejemplos para entrenar
MIN_TRAIN_SAMPLES = 50
# Umbral a partir del cual las métricas del test se consideran fiables. Por
# debajo se calculan igual (son informativas) pero se marcan
# ``metrics_reliable=False`` y el gate de promoción se niega a promocionar:
# un f1 a cuatro decimales sobre 10 filas de test no es una medición.
MIN_RELIABLE_TEST_ROWS = 100
MIN_RELIABLE_POS = 20


class SAPClassifier:
    """Pipeline FeatureUnion(TF-IDF) + CalibratedLR para detección de licitaciones SAP."""

    def __init__(self) -> None:
        use_embeddings = getattr(settings, "ML_USE_EMBEDDINGS", False)
        # Si la calibración la aplica una capa externa (calibrate_and_tune en
        # train() cuando ML_USE_CALIBRATION=True), el pipeline base NO debe
        # calibrar internamente: así se evita la doble calibración que degrada
        # las probabilidades (oversmoothing).
        calibrate_internally = not bool(getattr(settings, "ML_USE_CALIBRATION", False))
        if use_embeddings:
            self.pipeline = _make_pipeline_with_embeddings(calibrate=calibrate_internally)
            log.info(
                "ml_classifier.init",
                pipeline_variant="embeddings",
                calibrate_internally=calibrate_internally,
            )
        else:
            self.pipeline = _make_pipeline(calibrate=calibrate_internally)
            log.info(
                "ml_classifier.init",
                pipeline_variant="tfidf_only",
                calibrate_internally=calibrate_internally,
            )
        self._trained = False
        # Umbral óptimo aprendido en train(); fallback al de settings si no entrenado.
        self._threshold: float = settings.ML_CONFIDENCE_THRESHOLD
        # Metadata del entrenamiento (versión, métricas, timestamp).
        self.metadata: dict[str, Any] = {}
        # Por qué esta instancia NO es el artefacto de la versión activa del
        # registry, si ese es el caso. Lo rellena `load()`; `explain()` lo
        # propaga a la respuesta de la API. Ver DEGRADACION_VERSION_MISMATCH.
        self.serving_degradado: str | None = None

    # ── Entrenamiento ─────────────────────────────────────────────────────

    def train(self, df: pd.DataFrame) -> dict[str, Any]:
        """Entrena el clasificador con datos de la BD.

        Args:
            df: DataFrame con columnas titulo, descripcion, raw_keywords, cpv.
                Opcionalmente: fecha_publicacion (para split temporal),
                importe (para tokens de importe), es_relevante (label de feedback).

        Returns:
            Métricas de evaluación: accuracy, f1, pr_auc, cv_f1, optimal_threshold,
            precision, recall, n_train, n_test, n_positive, n_negative.
        """
        import numpy as np
        from sklearn.metrics import (
            accuracy_score,
            average_precision_score,
            brier_score_loss,
            f1_score,
            fbeta_score,
            precision_recall_curve,
        )
        from sklearn.model_selection import GroupKFold, cross_val_score

        from scraper.ml_pipeline import (
            TemporalSplitImposible,
            build_dataset_rows,
            split_dataset_rows,
        )

        # Ordenar por fecha si está disponible: no lo necesita el split (que
        # corta por fecha, no por posición) pero deja los logs y el dataset
        # legibles en orden cronológico.
        _has_date = bool(
            "fecha_publicacion" in df.columns and df["fecha_publicacion"].notna().any()
        )
        if _has_date:
            df = df.sort_values("fecha_publicacion", na_position="first").reset_index(drop=True)

        pu_learning = bool(getattr(settings, "ML_PU_LEARNING", False))
        filas = build_dataset_rows(df)
        texts = [f.text for f in filas]
        labels = [f.label for f in filas]
        weights_all: list[float] | None = [f.weight for f in filas] if pu_learning else None
        if len(texts) < MIN_TRAIN_SAMPLES:
            log.warning(
                "ml_classifier.insufficient_data",
                n=len(texts),
                min_required=MIN_TRAIN_SAMPLES,
            )
            return {"error": "insufficient_data", "n_samples": len(texts)}

        n_pos_total = int(sum(1 for label in labels if label == 1))
        n_neg_total = len(labels) - n_pos_total
        if len(set(labels)) < 2:
            log.warning(
                "ml_classifier.single_class",
                n_positive=n_pos_total,
                n_negative=n_neg_total,
                hint="Se necesitan ejemplos negativos (CPV fuera de 48xxx/72xxx sin keywords SAP).",
            )
            return {"error": "single_class", "n_positive": n_pos_total, "n_negative": n_neg_total}

        # ── Split ──────────────────────────────────────────────────────────
        # Corte por FECHA (no por posición) y con integridad de grupo: ningún
        # expediente puede aparecer a los dos lados. Si hay fechas pero ningún
        # corte es válido, se aborta en vez de degradar a un split aleatorio:
        # esa degradación silenciosa era lo que hacía que ``f1``/``pr_auc``
        # midieran interpolación y se publicaran como si midieran predicción.
        try:
            split = split_dataset_rows(filas)
        except TemporalSplitImposible as exc:
            log.warning("ml_classifier.temporal_split_impossible", error=str(exc))
            return {
                "error": "temporal_split_impossible",
                "detail": str(exc),
                "n_samples": len(texts),
                "n_positive": n_pos_total,
                "n_negative": n_neg_total,
            }

        X_train = [texts[i] for i in split.train]
        y_train = [labels[i] for i in split.train]
        X_test = [texts[i] for i in split.test]
        y_test = [labels[i] for i in split.test]
        g_train = [filas[i].grupo for i in split.train]
        # ``w_train`` lleva los pesos PU alineados con X_train (None si no aplica).
        w_train: list[float] | None = (
            [weights_all[i] for i in split.train] if weights_all is not None else None
        )
        _has_date = split.strategy == "temporal"

        if len(set(y_train)) < 2:
            log.warning("ml_classifier.single_class_train", n_train=len(y_train))
            return {
                "error": "single_class_train",
                "n_train": len(y_train),
                "n_test": len(y_test),
            }

        # ── CV F1 estimate (pipeline no calibrado, más rápido) ─────────────
        from scraper.ml_pipeline import _make_pipeline as _make_ml_pipeline

        pipeline_cv = _make_ml_pipeline(calibrate=False)
        # ``min(3, len(set(y_train)))`` daba SIEMPRE 2 folds: en este punto
        # y_train tiene exactamente dos clases por construcción, así que el
        # `min` no protegía de datos pequeños, solo capaba la CV a la mitad.
        # El límite real son los grupos y la clase minoritaria.
        n_grupos = len(set(g_train))
        n_minoritaria = min(y_train.count(0), y_train.count(1))
        n_cv_splits = max(2, min(3, n_grupos, n_minoritaria))
        cv_f1: float = 0.0
        cv_pr_auc: float = 0.0
        if len(X_train) >= 10 and n_grupos >= 2 and n_minoritaria >= 2:
            try:
                # GroupKFold: los lotes y republicaciones de un mismo
                # expediente no pueden repartirse entre folds, o la CV mide
                # memorización. Sustituye a StratifiedKFold(shuffle=True) y a
                # TimeSeriesSplit, que nunca llegaba a ejecutarse porque
                # dependía de un `_has_date` ya mutado a False.
                cv_splitter: Any = GroupKFold(n_splits=n_cv_splits)
                cv_scores = cross_val_score(
                    pipeline_cv,
                    X_train,
                    y_train,
                    groups=g_train,
                    cv=cv_splitter,
                    scoring="f1",
                )
                cv_f1 = float(np.mean(cv_scores))
                cv_ap = cross_val_score(
                    pipeline_cv,
                    X_train,
                    y_train,
                    groups=g_train,
                    cv=cv_splitter,
                    scoring="average_precision",
                )
                cv_pr_auc = float(np.mean(cv_ap))
            except Exception as _cv_exc:
                log.warning("ml_classifier.cv_failed", error=str(_cv_exc))
                cv_f1 = 0.0
                cv_pr_auc = 0.0

        # ── Split interno fit/val ─────────────────────────────────────────
        # El umbral y la calibración NO se pueden elegir sobre el mismo
        # conjunto donde se reportan las métricas: hacerlo sobreestima
        # precision/recall (medido: +0.08 de F-beta de media sobre un golden
        # de 27 ejemplos, +0.25 en el p90). Se corta una validación *dentro*
        # del train, con las mismas reglas de fecha y grupo.
        filas_train = [filas[i] for i in split.train]
        try:
            inner = split_dataset_rows(filas_train, seed=7)
        except TemporalSplitImposible as _inner_exc:
            log.warning("ml_classifier.no_validation_split", error=str(_inner_exc))
            inner = None

        if inner is not None:
            X_fit = [filas_train[i].text for i in inner.train]
            y_fit = [filas_train[i].label for i in inner.train]
            w_fit = [filas_train[i].weight for i in inner.train] if w_train is not None else None
            X_val = [filas_train[i].text for i in inner.test]
            y_val = [filas_train[i].label for i in inner.test]
        else:
            X_fit, y_fit, w_fit = X_train, y_train, w_train
            X_val, y_val = [], []

        # ── Entrenamiento final (pipeline calibrado) ───────────────────────
        tune_on_train = bool(getattr(settings, "ML_TUNE_ON_TRAIN", False))
        best_params: dict[str, Any] | None = None
        if tune_on_train:
            log.info("ml_classifier.tuning_start")
            try:
                tuned_pipeline, best_params = _tune_pipeline(X_fit, y_fit)
                self.pipeline = tuned_pipeline
                self._trained = True
                log.info("ml_classifier.tuning_done", best_params=best_params)
            except Exception as _tune_exc:
                log.warning("ml_classifier.tuning_failed", error=str(_tune_exc))
                self.pipeline.fit(X_fit, y_fit)
                self._trained = True
        else:
            if w_fit is not None:
                # PU learning: los negativos ambiguos pesan menos en el ajuste.
                self.pipeline.fit(X_fit, y_fit, clf__sample_weight=w_fit)
            else:
                self.pipeline.fit(X_fit, y_fit)
            self._trained = True

        beta = float(getattr(settings, "ML_FBETA", 1.0))

        # ── Calibración externa (opcional), ANTES de medir ────────────────
        # Si ML_USE_CALIBRATION=True, el pipeline base se construyó SIN
        # CalibratedClassifierCV interno (ver __init__), de modo que
        # calibrate_and_tune aplica una ÚNICA capa de calibración. Va aquí, y
        # no después de las métricas, porque antes brier/ece/pr_auc se
        # calculaban sobre el pipeline SIN calibrar y se guardaban como si
        # describieran el modelo que luego se serializa y se sirve.
        calibration_method: str | None = None
        if getattr(settings, "ML_USE_CALIBRATION", False) and X_val:
            try:
                from services.threshold_tuning import calibrate_and_tune

                tune_result = calibrate_and_tune(
                    base_estimator=self.pipeline,
                    X_train=X_fit,
                    y_train=list(y_fit),
                    X_val=X_val,
                    y_val=list(y_val),
                    cost_fp=float(getattr(settings, "ML_COST_FP", 1.0)),
                    cost_fn=float(getattr(settings, "ML_COST_FN", 1.0)),
                )
                self.pipeline = tune_result.calibrated
                calibration_method = tune_result.method
                log.info("ml_classifier.calibrated", method=tune_result.method)
            except Exception as _cal_exc:
                log.warning("ml_classifier.calibration_failed", error=str(_cal_exc))

        # ── Umbral: se elige en VALIDACIÓN, nunca en test ─────────────────
        threshold_source = "settings_default"
        optimal_threshold = settings.ML_CONFIDENCE_THRESHOLD
        if X_val and len(set(y_val)) >= 2:
            proba_val = self.pipeline.predict_proba(X_val)[:, 1]
            precisions, recalls, thresholds = precision_recall_curve(y_val, proba_val)
            beta_sq = beta * beta
            denom = beta_sq * precisions[:-1] + recalls[:-1] + 1e-9
            fbeta_scores = (1 + beta_sq) * precisions[:-1] * recalls[:-1] / denom
            if len(fbeta_scores) > 0:
                best_idx = int(np.argmax(fbeta_scores))
                optimal_threshold = max(0.30, min(0.95, float(thresholds[best_idx])))
                threshold_source = "validation"
        self._threshold = optimal_threshold

        # ── Umbral final sobre el golden set (labels humanas, split "tune") ──
        # Las etiquetas del split derivan del filtro de keywords; el golden set
        # tiene etiquetas humanas independientes. El tuning usa SOLO la mitad
        # "tune"; la mitad "holdout" queda para reportar sin contaminar.
        golden_metrics: dict[str, Any] = {}
        if getattr(settings, "ML_TUNE_THRESHOLD_ON_GOLDEN", True):
            try:
                from services.ml_eval import tune_threshold_on_golden

                golden = tune_threshold_on_golden(
                    self,
                    cost_fp=float(getattr(settings, "ML_COST_FP", 1.0)),
                    cost_fn=float(getattr(settings, "ML_COST_FN", 1.0)),
                )
                if golden is not None:
                    self._threshold = float(golden["threshold"])
                    threshold_source = "golden_tune"
                    golden_metrics = {f"golden_{k}": v for k, v in golden.items()}
            except Exception as _golden_exc:
                log.warning("ml_classifier.golden_tuning_failed", error=str(_golden_exc))

        optimal_threshold = self._threshold

        # ── Evaluación en test set, con el pipeline y el umbral FINALES ────
        proba_test = self.pipeline.predict_proba(X_test)[:, 1]
        y_pred_opt = (proba_test >= optimal_threshold).astype(int)
        y_test_arr = np.asarray(y_test, dtype=int)

        acc = float(accuracy_score(y_test_arr, y_pred_opt))
        f1 = float(f1_score(y_test_arr, y_pred_opt, zero_division=0))
        fbeta_opt = float(fbeta_score(y_test_arr, y_pred_opt, beta=beta, zero_division=0))
        pr_auc = (
            float(average_precision_score(y_test_arr, proba_test)) if len(set(y_test)) >= 2 else 0.0
        )
        brier = float(brier_score_loss(y_test_arr, proba_test))
        ece = _expected_calibration_error(y_test_arr, proba_test, n_bins=10)

        tp = int(((y_pred_opt == 1) & (y_test_arr == 1)).sum())
        fp = int(((y_pred_opt == 1) & (y_test_arr == 0)).sum())
        fn = int(((y_pred_opt == 0) & (y_test_arr == 1)).sum())
        precision_opt = tp / (tp + fp) if (tp + fp) else 0.0
        recall_opt = tp / (tp + fn) if (tp + fn) else 0.0

        # ── Métricas operativas ───────────────────────────────────────────
        cost_fn_v = float(getattr(settings, "ML_COST_FN", 1.0))
        cost_fp_v = float(getattr(settings, "ML_COST_FP", 1.0))
        from services.ml_eval import metricas_operativas

        operativas = metricas_operativas(
            y_test_arr.tolist(), proba_test.tolist(), cost_fp=cost_fp_v, cost_fn=cost_fn_v
        )

        # ── Métricas restringidas a la población de serving (CPV 48/72) ───
        # El modelo se entrena con negativos de todos los CPV pero en
        # producción solo puntúa TI, donde el token CPV_TI es constante. La
        # métrica global mide un separador de CPV que ya está implementado
        # aguas arriba; esta mide lo que el modelo aporta donde decide.
        ti_pos = [j for j, i in enumerate(split.test) if filas[i].cpv_ti]
        if ti_pos:
            y_ti = y_test_arr[ti_pos]
            proba_ti = proba_test[ti_pos]
            pred_ti = (proba_ti >= optimal_threshold).astype(int)
            metricas_ti: dict[str, Any] = {
                "n_test_ti": len(ti_pos),
                "f1_ti": round(float(f1_score(y_ti, pred_ti, zero_division=0)), 4),
            }
            if len(set(y_ti.tolist())) >= 2:
                metricas_ti["pr_auc_ti"] = round(float(average_precision_score(y_ti, proba_ti)), 4)
        else:
            metricas_ti = {"n_test_ti": 0}
            log.warning(
                "ml_classifier.sin_test_ti",
                hint=(
                    "Ninguna fila de test tiene CPV 48/72: el test no cubre la "
                    "población sobre la que el modelo decide en producción. "
                    "Sembrá hard negatives TI (seed_negatives(include_ti=True))."
                ),
            )

        # ── ¿Son fiables estas métricas? ──────────────────────────────────
        # MIN_TRAIN_SAMPLES=50 permite entrenar, pero un test de 10 filas no
        # sostiene un f1 a cuatro decimales. Este flag es el que consulta el
        # gate de promoción para negarse a promocionar a ciegas.
        n_pos_test = int(y_test_arr.sum())
        metrics_reliable = len(y_test) >= MIN_RELIABLE_TEST_ROWS and n_pos_test >= MIN_RELIABLE_POS
        if not metrics_reliable:
            log.warning(
                "ml_classifier.metrics_not_reliable",
                n_test=len(y_test),
                n_pos_test=n_pos_test,
                min_test=MIN_RELIABLE_TEST_ROWS,
                min_pos=MIN_RELIABLE_POS,
            )

        metrics: dict[str, Any] = {
            "accuracy": round(acc, 4),
            "f1": round(f1, 4),
            "fbeta": round(fbeta_opt, 4),
            "beta": beta,
            "cv_f1": round(cv_f1, 4),
            "cv_pr_auc": round(cv_pr_auc, 4),
            "pr_auc": round(pr_auc, 4),
            "brier": round(brier, 4),
            "ece": round(ece, 4),
            "optimal_threshold": round(optimal_threshold, 4),
            "threshold_source": threshold_source,
            "precision": round(precision_opt, 4),
            "recall": round(recall_opt, 4),
            "n_train": len(X_fit),
            "n_val": len(X_val),
            "n_test": len(X_test),
            "n_positive": n_pos_total,
            "n_negative": n_neg_total,
            "n_positive_test": n_pos_test,
            "temporal_split": _has_date,
            "split_strategy": split.strategy,
            "split_fecha_corte": split.fecha_corte,
            "split_descartadas_por_grupo": split.descartadas_por_grupo,
            "metrics_reliable": metrics_reliable,
            **metricas_ti,
            **operativas,
            **golden_metrics,
        }
        if calibration_method is not None:
            metrics["calibration_method"] = calibration_method
        self.metadata = {
            **metrics,
            "trained_at": datetime.now(UTC).isoformat(),
        }
        if best_params is not None:
            self.metadata["best_params"] = best_params

        log.info("ml_classifier.trained", **metrics)
        # Append run a registry JSON para histórico de entrenamientos.
        try:
            _append_to_registry(self.metadata)
        except Exception as exc:  # pragma: no cover — never block training
            log.warning("ml_classifier.registry_append_failed", error=str(exc))
        return metrics

    def predict(
        self,
        text: str,
        *,
        cpv: str | None = None,
        importe: float | None = None,
        organo: str | None = None,
    ) -> tuple[bool, float]:
        """Predice si un texto corresponde a una licitación SAP.

        Args:
            text: Texto combinado (título + descripción).
            cpv: Código CPV opcional — mejora la predicción con token estructural.
            importe: Importe en EUR opcional — añade token de rango de importe.
            organo: Órgano de contratación opcional — token estable de órgano
                (solo aprovechado si el modelo se entrenó con ML_USE_ORGANO_FEATURE).

        Returns:
            (es_sap, confianza) — confianza en [0, 1].
        """
        if not self._trained:
            raise RuntimeError("Clasificador no entrenado. Llama a train() o load() primero.")
        import time

        from observability.runtime_metrics import ml_inference_duration_seconds

        t0 = time.perf_counter()
        augmented = _augment_text(text, cpv=cpv, importe=importe, organo=organo)
        proba = self.pipeline.predict_proba([augmented])[0]
        ml_inference_duration_seconds.labels(method="predict").observe(time.perf_counter() - t0)
        confidence = float(proba[1])
        return confidence >= self._threshold, confidence

    def predict_batch(
        self,
        texts: list[str],
        *,
        cpvs: list[str | None] | None = None,
        importes: list[float | None] | None = None,
        organos: list[str | None] | None = None,
    ) -> list[tuple[bool, float]]:
        """Predicción en batch (más eficiente que llamadas individuales).

        Args:
            texts: Textos combinados (título + descripción).
            cpvs: Lista paralela de códigos CPV (opcional). Mejora la
                predicción con tokens estructurales vía ``_augment_text``.
            importes: Lista paralela de importes EUR (opcional). Codifica
                rangos logarítmicos como tokens.

        Si ``cpvs`` o ``importes`` no se proporcionan, se usa el texto tal
        cual (backward compatible).
        """
        if not self._trained:
            raise RuntimeError("Clasificador no entrenado.")
        import time

        from observability.runtime_metrics import ml_inference_duration_seconds

        t0 = time.perf_counter()
        augmented = [
            _augment_text(
                t,
                cpv=cpvs[i] if cpvs and i < len(cpvs) else None,
                importe=importes[i] if importes and i < len(importes) else None,
                organo=organos[i] if organos and i < len(organos) else None,
            )
            for i, t in enumerate(texts)
        ]
        probas = self.pipeline.predict_proba(augmented)
        ml_inference_duration_seconds.labels(method="predict_batch").observe(
            time.perf_counter() - t0
        )
        threshold = self._threshold
        return [(float(p[1]) >= threshold, float(p[1])) for p in probas]

    def predict_proba(
        self,
        texts: list[str],
        *,
        entity_ids: list[str] | None = None,
        cpvs: list[str | None] | None = None,
        importes: list[float | None] | None = None,
        organos: list[str | None] | None = None,
    ) -> npt.NDArray[np.floating[Any]]:
        """Devuelve la matriz de probabilidades sklearn (shape: [n, 2]).

        Columna 0 = P(no-SAP), columna 1 = P(SAP).

        .. important:: Pasá ``cpvs``/``importes``

            El modelo se entrena sobre texto **aumentado** con los tokens
            estructurales de :func:`_augment_text` (``CPV_TI``, ``CPV2_72``,
            ``IMPORTE_M``…). Este método los aplica igual que ``predict`` y
            ``predict_batch``; hasta ahora no lo hacía, y era el único de los
            tres que no. Como es el que puntúa la cola de active learning,
            el conjunto de licitaciones que un humano llegaba a etiquetar
            —y por tanto todo el feedback que realimenta el modelo— se
            ordenaba con una probabilidad calculada sin las señales más
            discriminantes, y además contradecía el ``ml_proba`` guardado en
            BD para la misma licitación.

        Si se pasa ``entity_ids`` (misma longitud que ``texts``), los
        resultados se cachean en el feature store por entity_id y versión de
        modelo, y se devuelven sin recomputar cuando la versión coincide.
        """
        if not self._trained:
            raise RuntimeError("Clasificador no entrenado.")

        model_version = self.metadata.get("trained_at", "unknown")

        # ── Feature store cache: lookup ────────────────────────────────
        cached_indices: dict[int, list[float]] = {}
        if entity_ids is not None and len(entity_ids) == len(texts):
            try:
                from db import feature_store

                cached = feature_store.get_features_bulk(
                    "licitacion",
                    entity_ids,
                    "ml_proba",
                    version=model_version,
                )
                for i, eid in enumerate(entity_ids):
                    if eid in cached:
                        cached_indices[i] = cached[eid]
            except Exception as _fs_exc:
                log.warning("ml_classifier.feature_store_lookup_failed", error=str(_fs_exc))

        # ── Compute only uncached texts ────────────────────────────────
        import numpy as np

        uncached_indices = [i for i in range(len(texts)) if i not in cached_indices]

        if uncached_indices:
            uncached_texts = [
                _augment_text(
                    texts[i],
                    cpv=cpvs[i] if cpvs and i < len(cpvs) else None,
                    importe=importes[i] if importes and i < len(importes) else None,
                    organo=organos[i] if organos and i < len(organos) else None,
                )
                for i in uncached_indices
            ]
            computed = self.pipeline.predict_proba(uncached_texts)
        else:
            computed = np.empty((0, 2))

        # ── Assemble full result matrix ────────────────────────────────
        result = np.zeros((len(texts), 2))
        for j, idx in enumerate(uncached_indices):
            result[idx] = computed[j]
        for idx, val in cached_indices.items():
            result[idx] = val

        # ── Feature store cache: store new results ─────────────────────
        if entity_ids is not None and len(entity_ids) == len(texts) and uncached_indices:
            try:
                from db import feature_store

                for idx in uncached_indices:
                    feature_store.set_feature(
                        "licitacion",
                        entity_ids[idx],
                        "ml_proba",
                        result[idx].tolist(),
                        version=model_version,
                    )
            except Exception as _fs_exc:
                log.warning("ml_classifier.feature_store_write_failed", error=str(_fs_exc))

        return result

    # ── Explicabilidad ────────────────────────────────────────────────────

    def explain(self, text: str, top_k: int = 5) -> dict[str, Any]:
        """Devuelve los términos que más contribuyen a la predicción.

        Con CalibratedClassifierCV, extrae el coeficiente medio de los
        clasificadores base de cada fold y lo multiplica por la contribución
        TF-IDF del texto. Equivalente al SHAP value para modelos lineales.

        Returns:
            Dict con ``prediction``, ``confidence``, ``top_features`` (lista
            de ``{term, weight, contribution}``) y, cuando el serving está
            degradado, ``warning`` (ver :func:`_con_degradacion`).
        """
        if not self._trained:
            raise RuntimeError("Clasificador no entrenado.")

        import numpy as np

        proba = self.pipeline.predict_proba([text])[0]
        confidence = float(proba[1])

        # Extraer el FeatureUnion (paso "features") y el clasificador calibrado
        feature_step = self.pipeline.named_steps.get("features")
        clf_step = self.pipeline.named_steps.get("clf")

        if feature_step is None or clf_step is None:
            return self._con_degradacion(
                {
                    "prediction": confidence >= self._threshold,
                    "confidence": confidence,
                    "top_features": [],
                    "warning": "No se pudieron extraer pasos del pipeline.",
                }
            )

        # Transformar el texto a través del FeatureUnion
        tfidf_matrix = feature_step.transform([text])
        feature_names = feature_step.get_feature_names_out()

        # CalibratedClassifierCV: extraer coef promedio de los estimadores base
        try:
            calibrated_classifiers = clf_step.calibrated_classifiers_
            coefs = [cc.estimator.coef_[0] for cc in calibrated_classifiers]
            coef = np.mean(coefs, axis=0)
        except AttributeError:
            # Fallback: clasificador sin calibración o estructura distinta
            if hasattr(clf_step, "coef_"):
                coef = clf_step.coef_[0]
            else:
                return self._con_degradacion(
                    {
                        "prediction": confidence >= self._threshold,
                        "confidence": confidence,
                        "top_features": [],
                        "warning": (
                            f"Clasificador {type(clf_step).__name__} no soporta explicación lineal."
                        ),
                    }
                )

        contributions = tfidf_matrix.multiply(coef).toarray().ravel()

        # Top-k por valor absoluto
        idx_sorted = sorted(
            range(len(contributions)),
            key=lambda i: abs(contributions[i]),
            reverse=True,
        )[: top_k * 2]
        top = [
            {
                "term": str(feature_names[i]),
                "weight": float(coef[i]),
                "contribution": float(contributions[i]),
            }
            for i in idx_sorted
            if abs(contributions[i]) > 1e-9
        ][:top_k]

        return self._con_degradacion(
            {
                "prediction": confidence >= self._threshold,
                "confidence": confidence,
                "top_features": top,
            }
        )

    def _con_degradacion(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Adjunta el aviso de degradación al payload de ``explain``.

        Cuando el artefacto de la versión activa no está en esta máquina, la
        API sirve el modelo local sin decirlo: hasta ahora eso era solo un
        `log.warning` dentro del contenedor, invisible para quien consume
        `/explain`. El campo `warning` ya existe en el DTO de la respuesta
        (`ExplainPayload`), así que la degradación viaja por ahí en vez de
        exigir un campo nuevo — y se **antepone** a un aviso previo en lugar de
        pisarlo: los dos son ciertos y el de degradación es el que cambia cómo
        hay que leer la explicación entera.
        """
        if not self.serving_degradado:
            return payload
        previo = str(payload.get("warning") or "")
        payload["warning"] = f"{_AVISO_VERSION_MISMATCH} {previo}".strip()
        payload["degradado"] = self.serving_degradado
        return payload

    # ── Persistencia ──────────────────────────────────────────────────────

    def save(self, path: Path | None = None) -> Path:
        """Serializa el modelo a disco usando joblib (más seguro que pickle).

        Guarda el objeto SAPClassifier completo (incluye pipeline entrenado,
        _threshold óptimo y metadata) junto con un checksum SHA256.
        """
        import joblib

        target = path or _MODEL_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, target, compress=3)

        # Generar checksum SHA256 junto al modelo
        sha256_hash = write_checksum(target)

        log.info(
            "ml_classifier.saved",
            path=str(target),
            sha256=sha256_hash[:16],
            threshold=self._threshold,
            trained_at=self.metadata.get("trained_at", "unknown"),
        )
        return target

    @classmethod
    def ensure_downloaded(
        cls,
        path: Path | None = None,
        repo: str = "Dkalds/TenderFlow",
        asset_name: str = "sap_classifier.pkl",
        pinned_sha256: str | None = None,
        pin_setting_name: str = "ML_MODEL_SHA256",
    ) -> bool:
        """Descarga el modelo desde el último GitHub Release si no existe localmente.

        Usa GITHUB_TOKEN del entorno si está disponible (necesario para repos privados
        y siempre disponible en GitHub Actions via secrets.GITHUB_TOKEN).

        Args:
            path: Destino. Por defecto el artefacto local del clasificador SAP.
            repo: ``owner/name`` del repositorio con la Release.
            asset_name: Nombre exacto del asset a descargar.
            pinned_sha256: Pin out-of-band contra el que verificar lo
                descargado. ``None`` usa ``settings.ML_MODEL_SHA256``. Es
                parámetro y no lectura fija porque
                ``TechnologyClassifier.ensure_downloaded`` reutiliza esta
                descarga para **otro** artefacto: aplicarle el pin del SAP lo
                borraría en cuanto ese pin estuviera configurado.
            pin_setting_name: Nombre del setting, solo para el log.

        Returns:
            True si el modelo está disponible (ya existía o se descargó correctamente).
            False si no se pudo descargar (sin acceso a red, sin releases, etc.).
        """
        import json
        import os

        target = path or _MODEL_PATH
        if target.exists():
            log.info("ml_classifier.model_already_local", path=str(target))
            return True

        if not _GITHUB_REPO_RE.fullmatch(repo):
            log.warning("ml_classifier.invalid_release_repository", repository=repo)
            return False

        github_token = os.environ.get("GITHUB_TOKEN", "")
        auth_header = {"Authorization": f"Bearer {github_token}"} if github_token else {}

        # Obtener la URL del asset desde la GitHub API
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        try:
            with pinned_https_request(
                "GET",
                api_url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "tenderflow",
                    **auth_header,
                },
                timeout_seconds=15,
                allowed_hosts=frozenset({"api.github.com"}),
            ) as response:
                response.raise_for_status()
                release = json.loads(b"".join(response.iter_content()))
        except Exception as e:
            log.warning("ml_classifier.release_fetch_failed", error=str(e))
            return False

        if not isinstance(release, dict):
            log.warning("ml_classifier.invalid_release_response")
            return False
        assets = release.get("assets", [])
        if not isinstance(assets, list):
            log.warning("ml_classifier.invalid_release_assets")
            return False

        asset_id: int | None = None
        for asset in assets:
            if isinstance(asset, dict) and asset.get("name") == asset_name:
                candidate = asset.get("id")
                if isinstance(candidate, int) and candidate > 0:
                    asset_id = candidate
                break

        if not asset_id:
            log.warning(
                "ml_classifier.asset_not_found", asset=asset_name, release=release.get("tag_name")
            )
            return False

        # Para repos privados, descargar via API con Accept: application/octet-stream
        download_url = f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            log.info("ml_classifier.downloading_model", asset_id=asset_id, dest=str(target))
            with pinned_https_request(
                "GET",
                download_url,
                headers={
                    "Accept": "application/octet-stream",
                    "User-Agent": "tenderflow",
                    **auth_header,
                },
                timeout_seconds=60,
                allowed_hosts=frozenset({"api.github.com"}),
            ) as response:
                response.raise_for_status()
                target.write_bytes(b"".join(response.iter_content()))
            # Verificar el pin out-of-band si está configurado: no confiar en un
            # modelo descargado cuyo hash no coincide con el pin del artefacto.
            crudo = (
                pinned_sha256
                if pinned_sha256 is not None
                else getattr(settings, "ML_MODEL_SHA256", "")
            )
            pinned = str(crudo or "").strip().lower()
            if pinned:
                import hashlib

                actual = hashlib.sha256(target.read_bytes()).hexdigest().lower()
                if actual != pinned:
                    log.error(
                        "ml_classifier.download_hash_mismatch",
                        pin=pin_setting_name,
                        expected=pinned[:16],
                        got=actual[:16],
                    )
                    target.unlink(missing_ok=True)
                    return False
            log.info("ml_classifier.model_downloaded", path=str(target))
            return True
        except Exception as e:
            log.warning("ml_classifier.download_failed", error=str(e))
            if target.exists():
                target.unlink()
            return False

    @classmethod
    def load(cls, path: Path | None = None) -> SAPClassifier:
        """Carga un modelo serializado con joblib. Lanza FileNotFoundError si no existe.

        Verifica la integridad del fichero contra el checksum SHA256 almacenado.
        Si el checksum no coincide, lanza RuntimeError para evitar cargar un
        modelo potencialmente manipulado.
        """
        import joblib

        # Si no se pasa path explícito, consultar el model registry.
        #
        # El `path` del registry es una ruta del sistema de ficheros de la
        # máquina que ENTRENÓ el modelo (un runner de GitHub Actions), y el
        # serving corre en otro contenedor: esa ruta normalmente no existe aquí.
        # Antes se usaba tal cual, así que `load()` fallaba con FileNotFoundError
        # sobre una ruta ajena en vez de caer al artefacto local, y el registry
        # quedaba de metadato decorativo. Ahora la ruta se usa **solo si existe**
        # en esta máquina, y el `sha256` del registry se aprovecha para verificar
        # la integridad del artefacto local — que es el dato que sí viaja entre
        # máquinas (ver ADR-025 sobre identificar artefactos por contenido).
        registry_sha256 = ""
        sirviendo_artefacto_del_registry = False
        version_activa: object | None = None
        degradado: str | None = None
        if path is None:
            try:
                from db.model_registry import get_active

                active = get_active("sap_classifier")
                if active:
                    version_activa = active.get("version")
                    registry_path = Path(str(active["path"])) if active.get("path") else None
                    if registry_path is not None and registry_path.exists():
                        path = registry_path
                        registry_sha256 = str(active.get("sha256") or "")
                        sirviendo_artefacto_del_registry = True
                        log.info(
                            "ml_classifier.load_from_registry",
                            version=version_activa,
                            path=str(path),
                        )
                    elif registry_path is not None:
                        # El artefacto versionado se quedó en el runner efímero
                        # que lo entrenó. Se sirve el local — pero SIN heredar
                        # el sha del registry: describe otro fichero, y
                        # aplicarlo como pin hacía que todo `load()` muriera
                        # con "integridad comprometida" en cuanto el
                        # reentrenamiento semanal promocionaba una versión.
                        degradado = DEGRADACION_VERSION_MISMATCH
                        log.warning(
                            "ml_classifier.serving_version_mismatch",
                            version_activa=version_activa,
                            registry_path=str(registry_path),
                            fallback=str(_MODEL_PATH),
                            hint=(
                                "El artefacto de la versión activa no está en esta máquina; "
                                "se sirve el modelo local, que puede ser anterior."
                            ),
                        )
            except Exception as _reg_exc:
                log.warning("ml_classifier.registry_lookup_failed", error=str(_reg_exc))

        target = path or _MODEL_PATH
        # El pin explícito de settings manda siempre. El sha del registry solo
        # se aplica cuando se está sirviendo **ese mismo** artefacto: es un
        # hash de contenido de un fichero concreto, no una propiedad del
        # modelo activo en abstracto.
        pinned = str(getattr(settings, "ML_MODEL_SHA256", "") or "")
        if not pinned and sirviendo_artefacto_del_registry:
            pinned = registry_sha256
        verify_model_integrity(
            target,
            pinned_sha256=pinned,
            pin_setting_name="ML_MODEL_SHA256",
            model_label="sap_classifier",
            env=str(getattr(settings, "ENV", "dev")),
        )

        obj = joblib.load(target)
        # Compatibilidad con modelos guardados ejecutando el script como __main__:
        # en ese caso el tipo es '__main__.SAPClassifier' en lugar de
        # 'scraper.ml_classifier.SAPClassifier'. Se acepta si el nombre de clase coincide.
        if not isinstance(obj, cls) and type(obj).__name__ != cls.__name__:
            raise TypeError(f"El archivo no contiene un SAPClassifier: {type(obj)}")
        # Retrocompatibilidad: modelos anteriores no tienen _threshold ni metadata
        if not hasattr(obj, "_threshold"):
            obj._threshold = settings.ML_CONFIDENCE_THRESHOLD
        if not hasattr(obj, "metadata"):
            obj.metadata = {}
        # El artefacto deserializado puede ser anterior a que este atributo
        # existiera; se fija siempre, tanto para marcar la degradación como
        # para limpiarla en una carga sana.
        obj.serving_degradado = degradado
        log.info(
            "ml_classifier.loaded",
            degradado=degradado,
            path=str(target),
            threshold=obj._threshold,
            trained_at=obj.metadata.get("trained_at", "legacy"),
        )
        return cast(SAPClassifier, obj)

    @classmethod
    def is_available(cls, path: Path | None = None) -> bool:
        """True si existe un modelo entrenado en disco."""
        return (path or _MODEL_PATH).exists()


# ── Re-exportaciones de utilidades ───────────────────────────────────────────
# Mantenidas para retrocompatibilidad con importadores externos.
from scraper.ml_training import (
    _append_to_registry,
    read_registry,  # noqa: F401  # re-export for external importers
    seed_negatives,
    train_from_db,
)

# ── CLI entry point ───────────────────────────────────────────────────────────

# ── Multi-label classifier (H4) ───────────────────────────────────────────────

#: Labels soportados. El label "SAP" se mapea al clasificador binario existente.

if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "train"
    if cmd == "train":
        print("Entrenando clasificador SAP desde la BD...")
        result = train_from_db()
        if "error" in result:
            err = result["error"]
            if err == "single_class":
                print(
                    "\n[AVISO] Entrenamiento no posible: todos los ejemplos son SAP (clase única).\n"
                    f"  n_positive={result.get('n_positive', 0)}, n_negative={result.get('n_negative', 0)}\n"
                    "  El clasificador ML necesita licitaciones sin keywords SAP con CPV fuera de 48xxx/72xxx.\n"
                    "  Solución: ejecuta primero: python -m scraper.ml_classifier seed-negatives"
                )
            elif err == "insufficient_data":
                print(
                    f"\n[AVISO] Datos insuficientes: {result.get('n_samples', 0)} muestras "
                    f"(mínimo {MIN_TRAIN_SAMPLES})."
                )
            else:
                print(f"\n[ERROR] {result}")
        else:
            for k, v in result.items():
                print(f"  {k}: {v}")
            print(f"\nModelo guardado en: {_MODEL_PATH}")
    elif cmd == "seed-negatives":
        import argparse

        parser_cli = argparse.ArgumentParser(prog="ml_classifier seed-negatives")
        parser_cli.add_argument("--year", type=int, default=None)
        parser_cli.add_argument("--month", type=int, default=None)
        parser_cli.add_argument("--max", type=int, default=2000, dest="max_negatives")
        args = parser_cli.parse_args(sys.argv[2:])
        print(
            f"Descargando negativos del bulk "
            f"{args.year or 'mes anterior'}/{args.month or ''}  (máx {args.max_negatives})..."
        )
        seed_result = seed_negatives(
            year=args.year, month=args.month, max_negatives=args.max_negatives
        )
        print(
            f"  Descargadas : {seed_result['downloaded']}\n"
            f"  Insertadas  : {seed_result['inserted']}\n"
            f"  Omitidas TI : {seed_result['skipped_ti']}\n"
            f"  Ya existían : {seed_result['already_exists']}\n"
            "\nAhora puedes entrenar: python -m scraper.ml_classifier train"
        )
    elif cmd == "precompute":
        import argparse

        parser_pre = argparse.ArgumentParser(prog="ml_classifier precompute")
        parser_pre.add_argument(
            "--force", action="store_true", help="Recalcular incluso filas ya clasificadas"
        )
        args_pre = parser_pre.parse_args(sys.argv[2:])
        from scraper.ml_training import precompute_ml_proba

        print("Precomputando ml_proba para licitaciones pendientes...")
        result = precompute_ml_proba(force=args_pre.force)
        print(f"  Actualizadas : {result.get('updated', 0)}")
        if result.get("skipped_no_model"):
            print("  [AVISO] No hay modelo disponible.")
    elif cmd == "info":
        if SAPClassifier.is_available():
            print(f"Modelo disponible: {_MODEL_PATH}")
        else:
            print("No hay modelo entrenado. Ejecuta: python -m scraper.ml_classifier train")
    elif cmd == "train-tech":
        from scraper.tech_classifier import _MODEL_PATH as _TECH_MODEL_PATH
        from scraper.tech_classifier import train_from_db as _train_tech_from_db

        print("Entrenando TechnologyClassifier multi-label desde la BD...")
        tech_metrics = _train_tech_from_db()
        if "error" in tech_metrics:
            print(f"\n[ERROR] {tech_metrics}")
        else:
            # `macro_f1_ml_ready_only` promedia SOLO las etiquetas con
            # suficientes positivos: es un promedio de los aprobados. Las dos
            # de al lado son las que cubren las 13 tecnologías.
            print(f"  micro_f1 (todas)  : {tech_metrics.get('micro_f1_all_labels')}")
            print(f"  macro_f1 (todas)  : {tech_metrics.get('macro_f1_all_labels')}")
            print(f"  macro_f1 ml_ready : {tech_metrics.get('macro_f1_ml_ready_only')}")
            # Si las etiquetas salen del regex de keywords, las métricas de
            # arriba miden imitación, no detección. Este es el dato que decide
            # si significan algo.
            print(f"  labels circulares : {tech_metrics.get('labels_circulares')}")
            print(f"  n_models          : {tech_metrics.get('n_models')}")
            print(f"  n_rules_fallback  : {tech_metrics.get('n_rules_fallback')}")
            print(
                f"  n_train/val/test  : {tech_metrics.get('n_train')} / "
                f"{tech_metrics.get('n_val')} / {tech_metrics.get('n_test')}"
            )
            print("\nDesglose por tecnología:")
            per_tech = tech_metrics.get("per_tech", {})
            for label, info in per_tech.items():
                tier = info.get("tier")
                n_pos = info.get("n_positive")
                f1 = info.get("f1")
                prec = info.get("precision")
                rec = info.get("recall")
                thr = info.get("threshold")
                f1_s = f"{f1:.3f}" if isinstance(f1, float) else "—"
                prec_s = f"{prec:.3f}" if isinstance(prec, float) else "—"
                rec_s = f"{rec:.3f}" if isinstance(rec, float) else "—"
                print(
                    f"  - {label:<12} tier={tier:<9} n+={n_pos:<5} "
                    f"thr={thr:<5} F1={f1_s} P={prec_s} R={rec_s}"
                )
            print(f"\nModelo guardado en: {_TECH_MODEL_PATH}")
    elif cmd == "precompute-tech":
        import argparse

        parser_pt = argparse.ArgumentParser(prog="ml_classifier precompute-tech")
        parser_pt.add_argument(
            "--force",
            action="store_true",
            help="Recalcular incluso filas ya clasificadas",
        )
        args_pt = parser_pt.parse_args(sys.argv[2:])
        from scraper.ml_training import precompute_ml_tecnologias

        print("Precomputando ml_tecnologias/ml_proba_max para licitaciones pendientes...")
        tech_result = precompute_ml_tecnologias(force=args_pt.force)
        print(f"  Actualizadas      : {tech_result.get('updated', 0)}")
        print(f"  Scores insertados : {tech_result.get('scores_inserted', 0)}")
        if tech_result.get("skipped_no_model"):
            print(
                "  [AVISO] No hay TechnologyClassifier entrenado. "
                "Ejecuta primero: python -m scraper.ml_classifier train-tech"
            )
    else:
        print(
            f"Comando desconocido: {cmd}. "
            "Usa 'train', 'precompute', 'seed-negatives', 'info', "
            "'train-tech' o 'precompute-tech'."
        )
        sys.exit(1)
