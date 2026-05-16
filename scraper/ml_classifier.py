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

if TYPE_CHECKING:
    import pandas as pd

log = get_logger(__name__)

# Ruta del modelo serializado (formato joblib, extensión .pkl por compatibilidad)
_MODEL_PATH = Path(__file__).parents[1] / "data" / "models" / "sap_classifier.pkl"

# Número mínimo de ejemplos para entrenar
MIN_TRAIN_SAMPLES = 50


def _make_pipeline():
    """Construye el pipeline sklearn con FeatureUnion + Calibración."""
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, Pipeline
    from sklearn.preprocessing import MaxAbsScaler

    feature_union = FeatureUnion(
        [
            (
                "word",
                TfidfVectorizer(
                    analyzer="word",
                    ngram_range=(1, 2),
                    max_features=20_000,
                    sublinear_tf=True,
                    min_df=2,
                    strip_accents="unicode",
                ),
            ),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(2, 4),
                    max_features=15_000,
                    sublinear_tf=True,
                    min_df=2,
                ),
            ),
        ]
    )
    base_lr = LogisticRegression(
        C=1.0,
        max_iter=500,
        class_weight="balanced",
        solver="lbfgs",
        random_state=42,
    )
    return Pipeline(
        [
            ("features", feature_union),
            ("scaler", MaxAbsScaler()),
            ("clf", CalibratedClassifierCV(base_lr, cv=5, method="sigmoid")),
        ]
    )


class SAPClassifier:
    """Pipeline FeatureUnion(TF-IDF) + CalibratedLR para detección de licitaciones SAP."""

    def __init__(self) -> None:
        self.pipeline = _make_pipeline()
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
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
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
        from sklearn.pipeline import FeatureUnion, Pipeline
        from sklearn.preprocessing import MaxAbsScaler

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
        pipeline_cv = Pipeline(
            [
                (
                    "features",
                    FeatureUnion(
                        [
                            (
                                "word",
                                TfidfVectorizer(
                                    analyzer="word",
                                    ngram_range=(1, 2),
                                    max_features=20_000,
                                    sublinear_tf=True,
                                    min_df=2,
                                    strip_accents="unicode",
                                ),
                            ),
                            (
                                "char",
                                TfidfVectorizer(
                                    analyzer="char_wb",
                                    ngram_range=(2, 4),
                                    max_features=15_000,
                                    sublinear_tf=True,
                                    min_df=2,
                                ),
                            ),
                        ]
                    ),
                ),
                ("scaler", MaxAbsScaler()),
                (
                    "clf",
                    LogisticRegression(
                        C=1.0,
                        max_iter=500,
                        class_weight="balanced",
                        solver="lbfgs",
                        random_state=42,
                    ),
                ),
            ]
        )
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
        augmented = _augment_text(text, cpv=cpv, importe=importe)
        proba = self.pipeline.predict_proba([augmented])[0]
        confidence = float(proba[1])
        return confidence >= self._threshold, confidence

    def predict_batch(self, texts: list[str]) -> list[tuple[bool, float]]:
        """Predicción en batch (más eficiente que llamadas individuales)."""
        if not self._trained:
            raise RuntimeError("Clasificador no entrenado.")
        probas = self.pipeline.predict_proba(texts)
        threshold = self._threshold
        return [(float(p[1]) >= threshold, float(p[1])) for p in probas]

    def predict_proba(self, texts: list[str]):
        """Devuelve la matriz de probabilidades sklearn (shape: [n, 2]).

        Columna 0 = P(no-SAP), columna 1 = P(SAP). Idéntico a
        sklearn.pipeline.Pipeline.predict_proba — expuesto en SAPClassifier
        para que los endpoints de active learning puedan usarlo directamente.
        """
        if not self._trained:
            raise RuntimeError("Clasificador no entrenado.")
        return self.pipeline.predict_proba(texts)

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
            log.warning(
                "ml_classifier.no_checksum_file",
                path=str(checksum_path),
                hint="El modelo se cargará sin verificación de integridad. "
                "Re-entrena con save() para generar el fichero .sha256.",
            )

        obj = joblib.load(target)
        if not isinstance(obj, cls):
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


# ── Funciones auxiliares ──────────────────────────────────────────────────────


# Ruta del registro de entrenamientos (histórico de runs).
_REGISTRY_PATH = Path(__file__).parents[1] / "data" / "models" / "registry.json"


def _expected_calibration_error(y_true, y_proba, n_bins: int = 10) -> float:
    """Expected Calibration Error con bins equi-anchos.

    Mide la diferencia ponderada entre confianza media y accuracy real
    en cada bin. ECE=0 → calibración perfecta; ECE alto → mal calibrado.
    """
    import numpy as np

    y_true_arr = np.asarray(y_true)
    y_proba_arr = np.asarray(y_proba)
    if len(y_true_arr) == 0:
        return 0.0
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.digitize(y_proba_arr, bins[1:-1])
    ece = 0.0
    n = len(y_true_arr)
    for b in range(n_bins):
        mask = bin_idx == b
        if not mask.any():
            continue
        conf = float(y_proba_arr[mask].mean())
        acc = float(y_true_arr[mask].mean())
        ece += (mask.sum() / n) * abs(conf - acc)
    return float(ece)


def _append_to_registry(entry: dict[str, Any], path: Path | None = None) -> Path:
    """Añade una entrada al registro de entrenamientos JSON (lista append-only).

    El registro permite:
      - Visualizar la evolución de métricas en el tiempo.
      - Detectar regresiones automáticamente (comparar último vs penúltimo).
      - Auditar qué modelo está en producción.
    """
    import json

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
    import json

    target = path or _REGISTRY_PATH
    if not target.exists():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _augment_text(text: str, *, cpv: str | None = None, importe: float | None = None) -> str:
    """Añade tokens estructurales al texto para mejorar la discriminación.

    CPV: Los códigos 48xxx/72xxx son señal TI fuerte → token "CPV_TI".
         Cualquier otro CPV → token "CPV_NO_TI".
    Importe: Se codifica en rangos logarítmicos (k€) como tokens especiales.

    Estos tokens son reconocidos por el TF-IDF word vectorizer como features
    adicionales sin cambiar la API de predict().
    """
    parts = [text]
    if cpv:
        cpv_clean = cpv.strip()[:8]
        if cpv_clean.startswith(("48", "72")):
            parts.append("CPV_TI CPV_TI")  # duplicado para mayor peso
        else:
            parts.append("CPV_NO_TI")
    if importe and importe > 0:
        import math

        log_imp = math.log10(max(importe, 1))
        if log_imp < 4:  # < 10k€
            parts.append("IMPORTE_XS")
        elif log_imp < 5:  # 10k-100k€
            parts.append("IMPORTE_S")
        elif log_imp < 6:  # 100k-1M€
            parts.append("IMPORTE_M")
        elif log_imp < 7:  # 1M-10M€
            parts.append("IMPORTE_L")
        else:  # > 10M€
            parts.append("IMPORTE_XL")
    return " ".join(parts)


def _build_dataset(df: pd.DataFrame) -> tuple[list[str], list[int]]:
    """Construye el dataset de entrenamiento desde el DataFrame.

    Fuentes de etiqueta (prioridad descendente):
      1. ``es_relevante`` columna (feedback humano explícito).
      2. ``raw_keywords`` IS NOT NULL → positivo.
      Negativos: ``raw_keywords`` IS NULL + CPV fuera del rango TI (no 48/72).
    Aumenta los textos con tokens CPV e importe si las columnas están presentes.

    Preserva el orden del df para que el split temporal en train() sea correcto.
    """
    import numpy as np

    has_cpv = "cpv" in df.columns
    has_importe = "importe" in df.columns
    has_keywords = "raw_keywords" in df.columns
    has_relevante = "es_relevante" in df.columns

    def _text_for_row(row) -> str:
        titulo = str(row.get("titulo", "") or "")
        desc = str(row.get("descripcion", "") or "")
        text = (titulo + " " + desc).strip()
        cpv = str(row.get("cpv", "") or "") if has_cpv else None
        importe = row.get("importe") if has_importe else None
        return _augment_text(text, cpv=cpv or None, importe=float(importe) if importe else None)

    # Máscara de positivos
    if has_relevante and not has_keywords:
        # Solo feedback — usar es_relevante como label
        mask_pos = df["es_relevante"].astype(bool)
    elif has_relevante and has_keywords:
        # Combinar: relevante=1 O raw_keywords notna
        mask_pos = df["es_relevante"].astype(bool) | (
            df["raw_keywords"].notna() & (df["raw_keywords"] != "")
        )
    elif has_keywords:
        mask_pos = df["raw_keywords"].notna() & (df["raw_keywords"] != "")
    else:
        # No hay señal → vacío
        return [], []

    # Máscara de negativos: sin señal positiva + CPV no-TI
    if has_cpv:
        mask_neg_cpv = df["cpv"].notna() & ~(
            df["cpv"].str.startswith("48") | df["cpv"].str.startswith("72")
        )
    else:
        mask_neg_cpv = ~mask_pos  # sin CPV, usamos todo lo que no es positivo

    mask_neg = ~mask_pos & mask_neg_cpv

    pos_rows = df[mask_pos]
    neg_rows = df[mask_neg]

    pos_texts = [_text_for_row(r) for r in pos_rows.to_dict("records")]
    neg_texts_all = [_text_for_row(r) for r in neg_rows.to_dict("records")]

    # Balancear: máx. 2x positivos en negativos
    max_neg = min(len(neg_texts_all), len(pos_texts) * 2)
    if max_neg < len(neg_texts_all):
        rng = np.random.default_rng(42)
        # Seleccionar subset y ORDENAR los índices para preservar orden temporal del df
        idx = rng.choice(len(neg_texts_all), max_neg, replace=False)
        idx_sorted = sorted(idx)
        neg_texts = [neg_texts_all[i] for i in idx_sorted]
    else:
        neg_texts = neg_texts_all

    texts = pos_texts + neg_texts
    labels = [1] * len(pos_texts) + [0] * len(neg_texts)
    return texts, labels


def seed_negatives(
    year: int | None = None,
    month: int | None = None,
    max_negatives: int = 2000,
) -> dict[str, int]:
    """Descarga el bulk de un mes y persiste licitaciones con CPV no-TI como negativos.

    Estas licitaciones se guardan con raw_keywords=NULL para que el entrenamiento ML
    las use como ejemplos negativos.

    Args:
        year: Año del bulk a descargar (defecto: mes anterior).
        month: Mes del bulk a descargar (defecto: mes anterior).
        max_negatives: Máximo de negativos a insertar (para no inflar la BD).

    Returns:
        {"downloaded": N, "inserted": M, "skipped_ti": K, "already_exists": J}
    """
    from datetime import UTC, datetime

    from dateutil.relativedelta import relativedelta

    from db.database import init_db
    from scraper.bulk_downloader import download_month, iter_xml_files
    from scraper.codice_parser import (
        _text,
        parse_entry_unfiltered,
    )

    if year is None or month is None:
        prev = datetime.now(UTC).date() - relativedelta(months=1)
        year = year or prev.year
        month = month or prev.month

    log.info("seed_negatives.start", year=year, month=month, max_negatives=max_negatives)
    init_db()

    zip_path = download_month(year, month, force=False)
    if zip_path is None:
        log.warning("seed_negatives.no_zip", year=year, month=month)
        return {"downloaded": 0, "inserted": 0, "skipped_ti": 0, "already_exists": 0}

    # CPV prefijos que consideramos TI/software (positivos en potencia → excluir)
    _TI_PREFIXES = ("48", "72")

    downloaded = 0
    skipped_ti = 0
    rows_to_insert: list[tuple[Any, ...]] = []

    for _filename, content in iter_xml_files(zip_path):
        if len(rows_to_insert) >= max_negatives:
            break
        try:
            from lxml import etree

            parser = etree.XMLParser(
                huge_tree=False, recover=True, resolve_entities=False, no_network=True
            )
            root = etree.fromstring(content, parser=parser)
            for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
                if len(rows_to_insert) >= max_negatives:
                    break
                try:
                    # Filtrar por CPV antes de parsear completamente
                    cfs = "./cacext:ContractFolderStatus"
                    project_xp = f"{cfs}/cac:ProcurementProject"
                    cpv_raw = _text(
                        entry,
                        f"{project_xp}/cac:RequiredCommodityClassification"
                        f"/cbc:ItemClassificationCode",
                    )
                    if cpv_raw and any(cpv_raw.startswith(p) for p in _TI_PREFIXES):
                        skipped_ti += 1
                        continue

                    lic = parse_entry_unfiltered(entry)
                    if lic is None:
                        continue
                    downloaded += 1
                    rows_to_insert.append(
                        (
                            lic.id_externo,
                            lic.titulo,
                            lic.descripcion,
                            lic.organo_contratacion,
                            lic.importe,
                            lic.moneda,
                            lic.cpv,
                            lic.tipo_contrato,
                            lic.estado,
                            lic.fecha_publicacion,
                            lic.fecha_actualizacion_fuente,
                            lic.url,
                            lic.provincia,
                            lic.nuts_code,
                            lic.ccaa,
                            lic.duracion_valor,
                            lic.duracion_unidad,
                            lic.fecha_inicio,
                            lic.fecha_fin,
                            lic.prorroga_descripcion,
                        )
                    )
                except Exception:
                    log.debug("seed_negatives.entry_error")
        except Exception:
            log.debug("seed_negatives.file_error")

    # Bulk insert en una sola transacción usando sqlite3 nativo (evita overhead libsql)
    inserted = 0
    already_exists = 0
    if rows_to_insert:
        import sqlite3

        from config import settings as _settings

        db_file = str(_settings.DB_PATH)
        with sqlite3.connect(db_file) as sqlite_conn:
            sqlite_conn.execute("PRAGMA journal_mode=WAL")
            sqlite_conn.execute("PRAGMA busy_timeout=5000")
            # Detect available columns to handle schema version differences
            existing_cols = {
                r[1] for r in sqlite_conn.execute("PRAGMA table_info(licitaciones)").fetchall()
            }
            has_fecha_act = "fecha_actualizacion_fuente" in existing_cols
            has_tecnologia = "tecnologia" in existing_cols

            for row in rows_to_insert:
                extra_cols = ""
                extra_vals = ""
                extra_params: list[Any] = []
                if has_fecha_act:
                    extra_cols += ", fecha_actualizacion_fuente"
                    extra_vals += ", ?"
                    extra_params.append(row[10])
                if has_tecnologia:
                    extra_cols += ", tecnologia"
                    extra_vals += ", NULL"
                cur = sqlite_conn.execute(
                    f"""INSERT OR IGNORE INTO licitaciones
                       (id_externo, titulo, descripcion, organo_contratacion,
                        importe, moneda, cpv, tipo_contrato, estado,
                        fecha_publicacion, fecha_extraccion, url, raw_keywords,
                        provincia, nuts_code, ccaa,
                        duracion_valor, duracion_unidad, fecha_inicio,
                        fecha_fin, prorroga_descripcion{extra_cols})
                       VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'),?,NULL,?,?,?,?,?,?,?,?{extra_vals})""",
                    (
                        row[0],  # id_externo
                        row[1],  # titulo
                        row[2],  # descripcion
                        row[3],  # organo_contratacion
                        row[4],  # importe
                        row[5],  # moneda
                        row[6],  # cpv
                        row[7],  # tipo_contrato
                        row[8],  # estado
                        row[9],  # fecha_publicacion
                        row[11],  # url
                        row[12],  # provincia
                        row[13],  # nuts_code
                        row[14],  # ccaa
                        row[15],  # duracion_valor
                        row[16],  # duracion_unidad
                        row[17],  # fecha_inicio
                        row[18],  # fecha_fin
                        row[19],  # prorroga_descripcion
                        *extra_params,
                    ),
                )
                if cur.rowcount:
                    inserted += 1
                else:
                    already_exists += 1

    log.info(
        "seed_negatives.done",
        year=year,
        month=month,
        downloaded=downloaded,
        inserted=inserted,
        skipped_ti=skipped_ti,
        already_exists=already_exists,
    )
    return {
        "downloaded": downloaded,
        "inserted": inserted,
        "skipped_ti": skipped_ti,
        "already_exists": already_exists,
    }


def train_from_db() -> dict[str, Any]:
    """Entrena el clasificador usando datos de la BD activa y lo guarda."""
    import pandas as pd

    from db.database import connect, init_db

    init_db()
    with connect() as c:
        cursor = c.execute(
            "SELECT titulo, descripcion, raw_keywords, cpv, importe, fecha_publicacion "
            "FROM licitaciones"
        )
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description]

    df = pd.DataFrame(rows, columns=cols)
    clf = SAPClassifier()
    metrics = clf.train(df)
    if "error" not in metrics:
        clf.save()
    return metrics


def precompute_ml_proba(*, batch_size: int = 500, force: bool = False) -> dict[str, int]:
    """Pre-computa ml_proba para todas las licitaciones en la BD.

    Actualiza la columna ``ml_proba`` con P(SAP) del clasificador actual.
    Por defecto solo procesa filas donde ``ml_proba IS NULL``; con ``force=True``
    recalcula todas.

    Args:
        batch_size: Número de filas a procesar por batch (contro memoria).
        force: Si True, sobreescribe valores existentes.

    Returns:
        {"updated": N, "skipped_no_model": bool}
    """
    if not SAPClassifier.is_available():
        log.warning("precompute_ml_proba.no_model")
        return {"updated": 0, "skipped_no_model": True}

    try:
        clf = SAPClassifier.load()
    except Exception as exc:
        log.error("precompute_ml_proba.load_failed", error=str(exc))
        return {"updated": 0, "skipped_no_model": True}

    from db.database import connect

    where = "" if force else "WHERE ml_proba IS NULL"
    with connect() as c:
        rows = c.execute(
            f"SELECT id_externo, titulo, descripcion, cpv, importe FROM licitaciones {where}"
        ).fetchall()

    if not rows:
        log.info("precompute_ml_proba.nothing_to_update")
        return {"updated": 0, "skipped_no_model": False}

    updated = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        texts = [
            _augment_text(
                (str(r[1] or "") + " " + str(r[2] or "")).strip(),
                cpv=str(r[3]) if r[3] else None,
                importe=float(r[4]) if r[4] else None,
            )
            for r in batch
        ]
        try:
            probas = clf.pipeline.predict_proba(texts)[:, 1]
        except Exception as exc:
            log.error("precompute_ml_proba.predict_failed", batch_start=i, error=str(exc))
            continue

        with connect() as c:
            for row, proba in zip(batch, probas, strict=False):
                c.execute(
                    "UPDATE licitaciones SET ml_proba = ? WHERE id_externo = ?",
                    (float(proba), row[0]),
                )
            c.commit()
        updated += len(batch)

    log.info("precompute_ml_proba.done", updated=updated)
    return {"updated": updated, "skipped_no_model": False}


# ── CLI entry point ───────────────────────────────────────────────────────────

# ── Multi-label classifier (H4) ───────────────────────────────────────────────

#: Labels soportados. El label "SAP" se mapea al clasificador binario existente.
MULTI_LABELS = ["SAP", "Cloud", "Integracion", "Mantenimiento", "RRHH"]

#: Keywords para heurística de labels adicionales (se combina con modelo lineal)
_LABEL_KEYWORDS: dict[str, list[str]] = {
    "Cloud": ["cloud", "saas", "azure", "aws", "nube", "on-demand", "s/4hana cloud"],
    "Integracion": [
        "integración",
        "integrar",
        "middleware",
        "api",
        "interfaz",
        "sistema externo",
        "conexion",
        "interoperabilidad",
    ],
    "Mantenimiento": [
        "mantenimiento",
        "soporte",
        "correctivo",
        "preventivo",
        "helpdesk",
        "servicio técnico",
        "licencias soporte",
    ],
    "RRHH": ["rrhh", "recursos humanos", "hr", "sap hr", "payroll", "nomina", "nómina"],
}

_MULTILABEL_MODEL_PATH = Path(__file__).parents[1] / "data" / "models" / "sap_multilabel.pkl"


class SAPMultiLabelClassifier:
    """Clasificador multi-label para SAP/Cloud/Integración/Mantenimiento/RRHH.

    Estrategia:
      - SAP: delega en SAPClassifier (modelo binario existente).
      - Otros labels: heurística de keywords + LogisticRegression por label.

    La API es compatible con SAPClassifier para fácil sustitución.
    """

    def __init__(self) -> None:
        self._sap_clf: SAPClassifier | None = None
        self._label_clfs: dict[str, Any] = {}
        self._trained = False

    def _keyword_score(self, text: str, label: str) -> float:
        """Devuelve fracción de keywords del label que aparecen en el texto."""
        t = text.lower()
        kws = _LABEL_KEYWORDS.get(label, [])
        if not kws:
            return 0.0
        return sum(1 for kw in kws if kw in t) / len(kws)

    def train(self, df: pd.DataFrame) -> dict[str, Any]:
        """Entrena usando el SAP binario + heurística para labels extras."""
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline

        # Train SAP binary
        sap = SAPClassifier()
        metrics = sap.train(df)
        if "error" in metrics:
            return metrics
        self._sap_clf = sap

        texts = (df["titulo"].fillna("") + " " + df["descripcion"].fillna("")).str.strip().tolist()

        # Train one LogReg per extra label using keyword heuristic as silver labels
        for label, kws in _LABEL_KEYWORDS.items():
            silver = [int(any(kw in t.lower() for kw in kws)) for t in texts]
            if sum(silver) < 10:
                continue  # skip if too few positive examples
            pipe = Pipeline(
                [
                    (
                        "tfidf",
                        TfidfVectorizer(ngram_range=(1, 2), max_features=20000, sublinear_tf=True),
                    ),
                    (
                        "clf",
                        LogisticRegression(
                            C=1.0, max_iter=300, class_weight="balanced", random_state=42
                        ),
                    ),
                ]
            )
            try:
                pipe.fit(texts, silver)
                self._label_clfs[label] = pipe
            except Exception as exc:
                log.warning("multilabel_train_skip", label=label, error=str(exc))

        self._trained = True
        metrics["multilabel_trained"] = list(self._label_clfs.keys())
        return metrics

    def predict_labels(self, text: str) -> dict[str, float]:
        """Devuelve {label: confidence} para todos los labels."""
        if not self._trained or self._sap_clf is None:
            raise RuntimeError("Clasificador no entrenado.")
        out: dict[str, float] = {}
        _, sap_conf = self._sap_clf.predict(text)
        out["SAP"] = sap_conf
        for label, pipe in self._label_clfs.items():
            try:
                proba = pipe.predict_proba([text])[0][1]
                out[label] = float(proba)
            except Exception:
                out[label] = self._keyword_score(text, label)
        return out

    def predict(self, text: str) -> tuple[bool, float]:
        """Compatible with SAPClassifier.predict() — returns (is_sap, confidence)."""
        labels = self.predict_labels(text)
        conf = labels.get("SAP", 0.0)
        return conf >= settings.ML_CONFIDENCE_THRESHOLD, conf

    def predict_proba(self, texts: list[str]) -> Any:
        """Returns array-like probabilities for compatibility with H3 uncertainty sampling."""
        import numpy as np

        if not self._trained or self._sap_clf is None:
            raise RuntimeError("Clasificador no entrenado.")
        probas = []
        for text in texts:
            _, conf = self._sap_clf.predict(text)
            probas.append([1 - conf, conf])
        return np.array(probas)

    def save(self, path: Path | None = None) -> Path:
        import joblib

        target = path or _MULTILABEL_MODEL_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, target, compress=3)
        log.info("multilabel_classifier.saved", path=str(target))
        return target

    @classmethod
    def load(cls, path: Path | None = None) -> SAPMultiLabelClassifier:
        import joblib

        target = path or _MULTILABEL_MODEL_PATH
        if not target.exists():
            raise FileNotFoundError(f"Multi-label classifier not found: {target}")
        obj = joblib.load(target)
        if not isinstance(obj, cls):
            raise TypeError(f"Expected SAPMultiLabelClassifier, got {type(obj)}")
        return obj

    @classmethod
    def is_available(cls, path: Path | None = None) -> bool:
        return (path or _MULTILABEL_MODEL_PATH).exists()


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
    elif cmd == "info":
        if SAPClassifier.is_available():
            print(f"Modelo disponible: {_MODEL_PATH}")
        else:
            print("No hay modelo entrenado. Ejecuta: python -m scraper.ml_classifier train")
    else:
        print(f"Comando desconocido: {cmd}. Usa 'train', 'seed-negatives' o 'info'.")
        sys.exit(1)
