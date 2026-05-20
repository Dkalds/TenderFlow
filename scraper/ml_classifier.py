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


# ── Re-exportaciones de utilidades ───────────────────────────────────────────
# Mantenidas para retrocompatibilidad con importadores externos.
from scraper.ml_training import (
    _append_to_registry,
    precompute_ml_proba,
    read_registry,
    seed_negatives,
    train_from_db,
)

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
