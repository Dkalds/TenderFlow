"""Clasificador ML para detección de licitaciones SAP.

Complementa el filtro por keywords con un modelo FeatureUnion(TF-IDF word +
TF-IDF char_wb) + MaxAbsScaler + CalibratedClassifierCV(LogisticRegression)
entrenado sobre los propios datos de la base de datos.

Estrategia de etiquetado:
  - Positivos: licitaciones que ya pasaron el filtro de keywords (raw_keywords IS NOT NULL)
    o con es_relevante=1 por feedback humano.
  - Negativos: licitaciones con CPV fuera del rango TI/software (no 48xxx ni 72xxx)
    y sin keywords SAP — muestra balanceada automáticamente.

Mejoras respecto a la versión original:
  1. FeatureUnion: TF-IDF word (1,2) + TF-IDF char_wb (2,4) — captura sub-palabras
     como "S/4HANA", "netweaver" que word-tokenizer fragmenta incorrectamente.
  2. CalibratedClassifierCV(sigmoid) — probabilidades calibradas (ECE reducido).
  3. Split temporal si fecha_publicacion disponible; random 80/20 como fallback.
  4. CV F1 estimate via 3-fold sobre el set de entrenamiento (pipeline sin calibración).
  5. PR-AUC y threshold sweep → optimal_threshold almacenado en metadata.
  6. self._threshold actualizado al optimal_threshold; fallback a settings si no entrenado.
  7. Metadata completa guardada en el pickle: trained_at, version, metrics, threshold.
  8. predict_proba() público (necesario para uncertainty sampling en active learning).
  9. precompute_ml_proba() — actualiza columna ml_proba en BD para todas las licitaciones.
 10. CPV e importe se codifican como tokens especiales en el texto de entrenamiento y
     predicción, permitiendo al modelo aprender señales estructurales sin cambiar la API.

Uso:
    # Entrenar (una vez, o periódicamente):
    python -m scraper.ml_classifier train

    # En el pipeline (predicción):
    from scraper.ml_classifier import SAPClassifier
    clf = SAPClassifier.load()
    is_sap, confidence = clf.predict("Mantenimiento del sistema ERP corporativo")
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import settings
from observability.logging import get_logger
from scraper.ml_pipeline import (
    _augment_text,
    _build_dataset,
    _expected_calibration_error,
    _make_pipeline,
    _make_pipeline_with_embeddings,
    _tune_pipeline,
)

if TYPE_CHECKING:
    import pandas as pd

log = get_logger(__name__)

# Ruta del modelo serializado (formato joblib, extensión .pkl por compatibilidad)
_MODEL_PATH = Path(__file__).parents[1] / "data" / "models" / "sap_classifier.pkl"

# Número mínimo de ejemplos para entrenar
MIN_TRAIN_SAMPLES = 50


class SAPClassifier:
    """Pipeline FeatureUnion(TF-IDF) + CalibratedLR para detección de licitaciones SAP."""

    def __init__(self) -> None:
        use_embeddings = getattr(settings, "ML_USE_EMBEDDINGS", False)
        if use_embeddings:
            self.pipeline = _make_pipeline_with_embeddings()
            log.info("ml_classifier.init", pipeline_variant="embeddings")
        else:
            self.pipeline = _make_pipeline()
            log.info("ml_classifier.init", pipeline_variant="tfidf_only")
        self._trained = False
        # Umbral óptimo aprendido en train(); fallback al de settings si no entrenado.
        self._threshold: float = settings.ML_CONFIDENCE_THRESHOLD
        # Metadata del entrenamiento (versión, métricas, timestamp).
        self.metadata: dict[str, Any] = {}

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
        from sklearn.model_selection import (
            StratifiedKFold,
            TimeSeriesSplit,
            cross_val_score,
            train_test_split,
        )

        # Ordenar por fecha si está disponible (split temporal)
        _has_date = "fecha_publicacion" in df.columns and df["fecha_publicacion"].notna().any()
        if _has_date:
            df = df.sort_values("fecha_publicacion", na_position="first").reset_index(drop=True)

        texts, labels = _build_dataset(df)
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
        if _has_date:
            # Split temporal: últimos 20% como test (más realista que random)
            cutoff = max(1, int(len(texts) * 0.80))
            X_train, X_test = texts[:cutoff], texts[cutoff:]
            y_train, y_test = labels[:cutoff], labels[cutoff:]
            # Si el test set tiene una sola clase, caer a random split
            if len(set(y_test)) < 2:
                _has_date = False

        if not _has_date:
            X_train, X_test, y_train, y_test = train_test_split(
                texts, labels, test_size=0.2, random_state=42, stratify=labels
            )

        # ── CV F1 estimate (pipeline no calibrado, más rápido) ─────────────
        from scraper.ml_pipeline import _make_pipeline as _make_ml_pipeline

        pipeline_cv = _make_ml_pipeline(calibrate=False)
        n_cv_splits = min(3, len(set(y_train)))  # protección datos muy pequeños
        cv_f1: float = 0.0
        if len(X_train) >= 10 and n_cv_splits >= 2:
            try:
                # TimeSeriesSplit cuando hay fechas y está habilitado en settings:
                # respeta el orden temporal (sin shuffle) — refleja mejor el
                # rendimiento esperado sobre datos futuros.
                if _has_date and getattr(settings, "ML_USE_TIMESERIES_CV", True):
                    cv_splitter: Any = TimeSeriesSplit(n_splits=n_cv_splits)
                else:
                    cv_splitter = StratifiedKFold(
                        n_splits=n_cv_splits, shuffle=True, random_state=42
                    )
                cv_scores = cross_val_score(
                    pipeline_cv,
                    X_train,
                    y_train,
                    cv=cv_splitter,
                    scoring="f1",
                )
                cv_f1 = float(np.mean(cv_scores))
            except Exception:
                cv_f1 = 0.0

        # ── Entrenamiento final (pipeline calibrado) ───────────────────────
        tune_on_train = bool(getattr(settings, "ML_TUNE_ON_TRAIN", False))
        best_params: dict[str, Any] | None = None
        if tune_on_train:
            log.info("ml_classifier.tuning_start")
            try:
                tuned_pipeline, best_params = _tune_pipeline(X_train, y_train)
                self.pipeline = tuned_pipeline
                self._trained = True
                log.info("ml_classifier.tuning_done", best_params=best_params)
            except Exception as _tune_exc:
                log.warning("ml_classifier.tuning_failed", error=str(_tune_exc))
                self.pipeline.fit(X_train, y_train)
                self._trained = True
        else:
            self.pipeline.fit(X_train, y_train)
            self._trained = True

        # ── Evaluación en test set ─────────────────────────────────────────
        proba_test = self.pipeline.predict_proba(X_test)[:, 1]
        y_pred = self.pipeline.predict(X_test)

        acc = float(accuracy_score(y_test, y_pred))
        f1 = float(f1_score(y_test, y_pred, zero_division=0))

        # PR-AUC (más informativo que ROC-AUC en clases desbalanceadas)
        pr_auc: float = 0.0
        if len(set(y_test)) >= 2:
            pr_auc = float(average_precision_score(y_test, proba_test))

        # ── Calidad de calibración ────────────────────────────────────────
        # Brier score: error cuadrático medio de las probabilidades (0=perfecto).
        # ECE: Expected Calibration Error con 10 bins equi-anchos.
        brier: float = float(brier_score_loss(y_test, proba_test))
        ece: float = _expected_calibration_error(np.asarray(y_test), proba_test, n_bins=10)

        # ── Threshold sweep: maximizar F-beta (β configurable) ────────────
        beta = float(getattr(settings, "ML_FBETA", 1.0))
        optimal_threshold = settings.ML_CONFIDENCE_THRESHOLD
        if len(set(y_test)) >= 2:
            precisions, recalls, thresholds = precision_recall_curve(y_test, proba_test)
            # F_beta = (1+β²) * P*R / (β²*P + R)
            beta_sq = beta * beta
            denom = beta_sq * precisions[:-1] + recalls[:-1] + 1e-9
            fbeta_scores = (1 + beta_sq) * precisions[:-1] * recalls[:-1] / denom
            if len(fbeta_scores) > 0:
                best_idx = int(np.argmax(fbeta_scores))
                optimal_threshold = float(thresholds[best_idx])
                # Clamping: no salir del rango [0.3, 0.95]
                optimal_threshold = max(0.30, min(0.95, optimal_threshold))

        self._threshold = optimal_threshold

        # Métricas con el threshold óptimo
        y_pred_opt = (proba_test >= optimal_threshold).astype(int)
        precision_opt = float(
            np.sum((y_pred_opt == 1) & (np.array(y_test) == 1)) / (np.sum(y_pred_opt == 1) + 1e-9)
        )
        recall_opt = float(
            np.sum((y_pred_opt == 1) & (np.array(y_test) == 1))
            / (np.sum(np.array(y_test) == 1) + 1e-9)
        )
        fbeta_opt = float(fbeta_score(y_test, y_pred_opt, beta=beta, zero_division=0))

        metrics: dict[str, Any] = {
            "accuracy": round(acc, 4),
            "f1": round(f1, 4),
            "fbeta": round(fbeta_opt, 4),
            "beta": beta,
            "cv_f1": round(cv_f1, 4),
            "pr_auc": round(pr_auc, 4),
            "brier": round(brier, 4),
            "ece": round(ece, 4),
            "optimal_threshold": round(optimal_threshold, 4),
            "precision": round(precision_opt, 4),
            "recall": round(recall_opt, 4),
            "n_train": len(X_train),
            "n_test": len(X_test),
            "n_positive": n_pos_total,
            "n_negative": n_neg_total,
            "temporal_split": _has_date,
        }
        self.metadata = {
            **metrics,
            "trained_at": datetime.now(UTC).isoformat(),
        }
        if best_params is not None:
            self.metadata["best_params"] = best_params

        # ── Calibración de probabilidades + threshold tuning externo (opcional) ───
        # Si ML_USE_CALIBRATION=True en settings, usa CalibratedClassifierCV +
        # búsqueda F-beta sobre malla fina para refinar el umbral y mejorar las
        # probabilidades predichas.
        if getattr(settings, "ML_USE_CALIBRATION", False):
            log.warning(
                "double_calibration_risk",
                detail="Pipeline already uses CalibratedClassifierCV. "
                "Enabling ML_USE_CALIBRATION may degrade probability estimates.",
            )
            try:
                from services.threshold_tuning import calibrate_and_tune

                cost_fn = float(getattr(settings, "ML_COST_FN", 1.0))
                cost_fp = float(getattr(settings, "ML_COST_FP", 1.0))
                tune_result = calibrate_and_tune(
                    base_estimator=self.pipeline,
                    X_train=X_train,
                    y_train=list(y_train),
                    X_val=X_test,
                    y_val=list(y_test),
                    cost_fp=cost_fp,
                    cost_fn=cost_fn,
                )
                # Sustituir pipeline por versión calibrada y actualizar threshold
                self.pipeline = tune_result.calibrated  # type: ignore[assignment]
                self._threshold = tune_result.threshold
                metrics["optimal_threshold"] = round(tune_result.threshold, 4)
                metrics["fbeta_calibrated"] = round(tune_result.fbeta, 4)
                metrics["calibration_method"] = tune_result.method
                self.metadata.update(
                    optimal_threshold=metrics["optimal_threshold"],
                    fbeta_calibrated=metrics["fbeta_calibrated"],
                    calibration_method=tune_result.method,
                )
                log.info(
                    "ml_classifier.calibrated",
                    threshold=self._threshold,
                    fbeta=tune_result.fbeta,
                    method=tune_result.method,
                )
            except Exception as _cal_exc:
                log.warning("ml_classifier.calibration_failed", error=str(_cal_exc))
        log.info("ml_classifier.trained", **metrics)
        # Append run a registry JSON para histórico de entrenamientos.
        try:
            _append_to_registry(self.metadata)
        except Exception as exc:  # pragma: no cover — never block training
            log.warning("ml_classifier.registry_append_failed", error=str(exc))
        return metrics

    def predict(
        self, text: str, *, cpv: str | None = None, importe: float | None = None
    ) -> tuple[bool, float]:
        """Predice si un texto corresponde a una licitación SAP.

        Args:
            text: Texto combinado (título + descripción).
            cpv: Código CPV opcional — mejora la predicción con token estructural.
            importe: Importe en EUR opcional — añade token de rango de importe.

        Returns:
            (es_sap, confianza) — confianza en [0, 1].
        """
        if not self._trained:
            raise RuntimeError("Clasificador no entrenado. Llama a train() o load() primero.")
        import time

        from observability.runtime_metrics import ml_inference_duration_seconds

        t0 = time.perf_counter()
        augmented = _augment_text(text, cpv=cpv, importe=importe)
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
            )
            for i, t in enumerate(texts)
        ]
        probas = self.pipeline.predict_proba(augmented)
        ml_inference_duration_seconds.labels(method="predict_batch").observe(
            time.perf_counter() - t0
        )
        threshold = self._threshold
        return [(float(p[1]) >= threshold, float(p[1])) for p in probas]

    def predict_proba(self, texts: list[str], *, entity_ids: list[str] | None = None):
        """Devuelve la matriz de probabilidades sklearn (shape: [n, 2]).

        Columna 0 = P(no-SAP), columna 1 = P(SAP). Idéntico a
        sklearn.pipeline.Pipeline.predict_proba — expuesto en SAPClassifier
        para que los endpoints de active learning puedan usarlo directamente.

        If ``entity_ids`` is provided (same length as ``texts``), results are
        cached in the feature store keyed by entity_id and model version.
        Cached values are returned without recomputation when the version
        matches.
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
            uncached_texts = [texts[i] for i in uncached_indices]
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
            de ``{term, weight, contribution}``).
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
            return {
                "prediction": confidence >= self._threshold,
                "confidence": confidence,
                "top_features": [],
                "warning": "No se pudieron extraer pasos del pipeline.",
            }

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
                return {
                    "prediction": confidence >= self._threshold,
                    "confidence": confidence,
                    "top_features": [],
                    "warning": f"Clasificador {type(clf_step).__name__} no soporta explicación lineal.",
                }

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

        return {
            "prediction": confidence >= self._threshold,
            "confidence": confidence,
            "top_features": top,
        }

    # ── Persistencia ──────────────────────────────────────────────────────

    def save(self, path: Path | None = None) -> Path:
        """Serializa el modelo a disco usando joblib (más seguro que pickle).

        Guarda el objeto SAPClassifier completo (incluye pipeline entrenado,
        _threshold óptimo y metadata) junto con un checksum SHA256.
        """
        import hashlib

        import joblib

        target = path or _MODEL_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, target, compress=3)

        # Generar checksum SHA256 junto al modelo
        sha256_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        checksum_path = target.with_suffix(".sha256")
        checksum_path.write_text(sha256_hash, encoding="utf-8")

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
        repo: str = "Dkalds/Licitaciones_sap_SP",
        asset_name: str = "sap_classifier.pkl",
    ) -> bool:
        """Descarga el modelo desde el último GitHub Release si no existe localmente.

        Usa GITHUB_TOKEN del entorno si está disponible (necesario para repos privados
        y siempre disponible en GitHub Actions via secrets.GITHUB_TOKEN).

        Returns:
            True si el modelo está disponible (ya existía o se descargó correctamente).
            False si no se pudo descargar (sin acceso a red, sin releases, etc.).
        """
        import json
        import os
        import urllib.request

        target = path or _MODEL_PATH
        if target.exists():
            log.info("ml_classifier.model_already_local", path=str(target))
            return True

        github_token = os.environ.get("GITHUB_TOKEN", "")
        auth_header = {"Authorization": f"Bearer {github_token}"} if github_token else {}

        # Obtener la URL del asset desde la GitHub API
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        try:
            req = urllib.request.Request(  # noqa: S310
                api_url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "licitaciones-sap",
                    **auth_header,
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                release = json.loads(resp.read())
        except Exception as e:
            log.warning("ml_classifier.release_fetch_failed", error=str(e))
            return False

        asset_id = None
        for asset in release.get("assets", []):
            if asset["name"] == asset_name:
                asset_id = asset["id"]
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
            dl_req = urllib.request.Request(  # noqa: S310
                download_url,
                headers={
                    "Accept": "application/octet-stream",
                    "User-Agent": "licitaciones-sap",
                    **auth_header,
                },
            )
            with urllib.request.urlopen(dl_req, timeout=60) as resp:  # noqa: S310
                target.write_bytes(resp.read())
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
        import hashlib

        import joblib

        # Si no se pasa path explícito, consultar el model registry
        if path is None:
            try:
                from db.model_registry import get_active

                active = get_active("sap_classifier")
                if active and active.get("path"):
                    path = Path(active["path"])
                    log.info(
                        "ml_classifier.load_from_registry",
                        version=active.get("version"),
                        path=str(path),
                    )
            except Exception as _reg_exc:
                log.warning("ml_classifier.registry_lookup_failed", error=str(_reg_exc))

        target = path or _MODEL_PATH

        # Verificar integridad con SHA256
        checksum_path = target.with_suffix(".sha256")
        if checksum_path.exists():
            expected_hash = checksum_path.read_text(encoding="utf-8").strip()
            actual_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                raise RuntimeError(
                    f"Integridad del modelo comprometida: SHA256 no coincide. "
                    f"Esperado: {expected_hash[:16]}..., obtenido: {actual_hash[:16]}... "
                    f"Fichero: {target}"
                )
            log.info("ml_classifier.checksum_verified", path=str(target))
        else:
            # En producción, el checksum es obligatorio para prevenir la carga
            # de modelos comprometidos (joblib.load ejecuta código arbitrario).
            from config import settings as _s

            if getattr(_s, "ENV", "dev") == "prod":
                raise RuntimeError(
                    f"Fichero de checksum no encontrado: {checksum_path}. "
                    "En producción, el checksum SHA256 es obligatorio para verificar "
                    "la integridad del modelo antes de deserializarlo. "
                    "Re-entrena con save() para generar el fichero .sha256."
                )
            log.warning(
                "ml_classifier.no_checksum_file",
                path=str(checksum_path),
                hint="El modelo se cargará sin verificación de integridad. "
                "Re-entrena con save() para generar el fichero .sha256.",
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
        log.info(
            "ml_classifier.loaded",
            path=str(target),
            threshold=obj._threshold,
            trained_at=obj.metadata.get("trained_at", "legacy"),
        )
        return obj

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
            print(f"  macro_f1_ml_ready : {tech_metrics.get('macro_f1_ml_ready')}")
            print(f"  n_models          : {tech_metrics.get('n_models')}")
            print(f"  n_rules_fallback  : {tech_metrics.get('n_rules_fallback')}")
            print(
                f"  n_train / n_test  : {tech_metrics.get('n_train')} / {tech_metrics.get('n_test')}"
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
