"""Clasificador ML para detección de licitaciones SAP.

Complementa el filtro por keywords con un modelo TF-IDF + LogisticRegression
entrenado sobre los propios datos de la base de datos.

Estrategia de etiquetado:
  - Positivos: licitaciones que ya pasaron el filtro de keywords (raw_keywords IS NOT NULL)
  - Negativos: licitaciones con CPV fuera del rango TI/software (no 48xxx ni 72xxx)
    y sin keywords SAP — muestra balanceada automáticamente.

Uso:
    # Entrenar (una vez, o periódicamente):
    python -m scraper.ml_classifier train

    # En el pipeline (predicción):
    from scraper.ml_classifier import SAPClassifier
    clf = SAPClassifier.load()
    is_sap, confidence = clf.predict("Mantenimiento del sistema ERP corporativo")
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import TYPE_CHECKING

from observability.logging import get_logger

if TYPE_CHECKING:
    import pandas as pd

log = get_logger(__name__)

# Ruta del modelo serializado
_MODEL_PATH = Path(__file__).parents[1] / "data" / "models" / "sap_classifier.pkl"

# Umbral de confianza para clasificar como SAP sin keywords
CONFIDENCE_THRESHOLD = 0.70

# Número mínimo de ejemplos para entrenar
MIN_TRAIN_SAMPLES = 50


class SAPClassifier:
    """Pipeline TF-IDF + LogisticRegression para detección de licitaciones SAP."""

    def __init__(self) -> None:
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import MaxAbsScaler
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.pipeline = Pipeline(
            [
                (
                    "tfidf",
                    TfidfVectorizer(
                        ngram_range=(1, 2),
                        max_features=30_000,
                        sublinear_tf=True,
                        min_df=2,
                        analyzer="word",
                        strip_accents="unicode",
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
        self._trained = False

    # ── Entrenamiento ─────────────────────────────────────────────────────

    def train(self, df: "pd.DataFrame") -> dict[str, float]:
        """Entrena el clasificador con datos de la BD.

        Args:
            df: DataFrame con columnas titulo, descripcion, raw_keywords, cpv.

        Returns:
            Métricas de evaluación (accuracy, f1, n_train, n_test).
        """
        import numpy as np
        from sklearn.metrics import accuracy_score, f1_score
        from sklearn.model_selection import train_test_split

        texts, labels = _build_dataset(df)
        if len(texts) < MIN_TRAIN_SAMPLES:
            log.warning(
                "ml_classifier.insufficient_data",
                n=len(texts),
                min_required=MIN_TRAIN_SAMPLES,
            )
            return {"error": "insufficient_data", "n_samples": len(texts)}

        n_pos = int(sum(1 for l in labels if l == 1))
        n_neg = len(labels) - n_pos
        if len(set(labels)) < 2:
            log.warning(
                "ml_classifier.single_class",
                n_positive=n_pos,
                n_negative=n_neg,
                hint="Se necesitan ejemplos negativos (CPV fuera de 48xxx/72xxx sin keywords SAP).",
            )
            return {"error": "single_class", "n_positive": n_pos, "n_negative": n_neg}

        X_train, X_test, y_train, y_test = train_test_split(
            texts, labels, test_size=0.2, random_state=42, stratify=labels
        )
        self.pipeline.fit(X_train, y_train)
        self._trained = True

        y_pred = self.pipeline.predict(X_test)
        acc = float(accuracy_score(y_test, y_pred))
        f1 = float(f1_score(y_test, y_pred, zero_division=0))
        n_pos = int(np.sum(labels))
        n_neg = len(labels) - n_pos

        metrics = {
            "accuracy": round(acc, 4),
            "f1": round(f1, 4),
            "n_train": len(X_train),
            "n_test": len(X_test),
            "n_positive": n_pos,
            "n_negative": n_neg,
        }
        log.info("ml_classifier.trained", **metrics)
        return metrics

    def predict(self, text: str) -> tuple[bool, float]:
        """Predice si un texto corresponde a una licitación SAP.

        Args:
            text: Texto combinado (título + descripción).

        Returns:
            (es_sap, confianza) — confianza en [0, 1].
        """
        if not self._trained:
            raise RuntimeError("Clasificador no entrenado. Llama a train() o load() primero.")
        proba = self.pipeline.predict_proba([text])[0]
        # proba[1] = P(SAP)
        confidence = float(proba[1])
        return confidence >= CONFIDENCE_THRESHOLD, confidence

    def predict_batch(self, texts: list[str]) -> list[tuple[bool, float]]:
        """Predicción en batch (más eficiente que llamadas individuales)."""
        if not self._trained:
            raise RuntimeError("Clasificador no entrenado.")
        probas = self.pipeline.predict_proba(texts)
        return [(float(p[1]) >= CONFIDENCE_THRESHOLD, float(p[1])) for p in probas]

    # ── Persistencia ──────────────────────────────────────────────────────

    def save(self, path: Path | None = None) -> Path:
        """Serializa el modelo a disco."""
        target = path or _MODEL_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as f:
            pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)
        log.info("ml_classifier.saved", path=str(target))
        return target

    @classmethod
    def load(cls, path: Path | None = None) -> "SAPClassifier":
        """Carga un modelo serializado. Lanza FileNotFoundError si no existe."""
        target = path or _MODEL_PATH
        with open(target, "rb") as f:
            obj = pickle.load(f)  # noqa: S301
        if not isinstance(obj, cls):
            raise TypeError(f"El archivo no contiene un SAPClassifier: {type(obj)}")
        log.info("ml_classifier.loaded", path=str(target))
        return obj

    @classmethod
    def is_available(cls, path: Path | None = None) -> bool:
        """True si existe un modelo entrenado en disco."""
        return (path or _MODEL_PATH).exists()


# ── Funciones auxiliares ──────────────────────────────────────────────────────


def _build_dataset(df: "pd.DataFrame") -> tuple[list[str], list[int]]:
    """Construye el dataset de entrenamiento desde el DataFrame.

    Positivos: raw_keywords IS NOT NULL (coincidió con keywords SAP).
    Negativos: raw_keywords IS NULL + CPV fuera del rango TI, balanceados.
    """
    import numpy as np

    text_col = (df["titulo"].fillna("") + " " + df["descripcion"].fillna("")).str.strip()

    mask_pos = df["raw_keywords"].notna() & (df["raw_keywords"] != "")
    mask_neg_cpv = df["cpv"].notna() & ~(
        df["cpv"].str.startswith("48") | df["cpv"].str.startswith("72")
    )
    mask_neg = ~mask_pos & mask_neg_cpv

    pos_texts = text_col[mask_pos].tolist()
    neg_texts = text_col[mask_neg].tolist()

    # Balancear: máx. 2x positivos en negativos
    max_neg = min(len(neg_texts), len(pos_texts) * 2)
    if max_neg < len(neg_texts):
        rng = np.random.default_rng(42)
        idx = rng.choice(len(neg_texts), max_neg, replace=False)
        neg_texts = [neg_texts[i] for i in idx]

    texts = pos_texts + neg_texts
    labels = [1] * len(pos_texts) + [0] * len(neg_texts)
    return texts, labels


def train_from_db() -> dict[str, float]:
    """Entrena el clasificador usando datos de la BD activa y lo guarda."""
    import pandas as pd

    from db.database import connect, init_db

    init_db()
    with connect() as c:
        cursor = c.execute(
            "SELECT titulo, descripcion, raw_keywords, cpv FROM licitaciones"
        )
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description]

    df = pd.DataFrame(rows, columns=cols)
    clf = SAPClassifier()
    metrics = clf.train(df)
    if "error" not in metrics:
        clf.save()
    return metrics


# ── CLI entry point ───────────────────────────────────────────────────────────

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
                    "  Solución: ejecuta el scraper sin filtro para acumular datos mixtos."
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
    elif cmd == "info":
        if SAPClassifier.is_available():
            print(f"Modelo disponible: {_MODEL_PATH}")
        else:
            print("No hay modelo entrenado. Ejecuta: python -m scraper.ml_classifier train")
    else:
        print(f"Comando desconocido: {cmd}. Usa 'train' o 'info'.")
        sys.exit(1)
