"""Construcción del pipeline sklearn y utilidades de features para el clasificador SAP.

Contiene:
  - ``_make_pipeline()`` — FeatureUnion(TF-IDF word + char_wb) + MaxAbsScaler + CalibratedLR
  - ``_augment_text()`` — añade tokens estructurales (CPV, importe) al texto
  - ``_build_dataset()`` — construye (texts, labels) desde un DataFrame
  - ``_expected_calibration_error()`` — ECE con bins equi-anchos
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd


def _make_pipeline() -> Any:
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

    def _text_for_row(row: dict[str, Any]) -> str:
        titulo = str(row.get("titulo", "") or "")
        desc = str(row.get("descripcion", "") or "")
        text = (titulo + " " + desc).strip()
        cpv = str(row.get("cpv", "") or "") if has_cpv else None
        importe = row.get("importe") if has_importe else None
        return _augment_text(text, cpv=cpv or None, importe=float(importe) if importe else None)

    # Máscara de positivos
    if has_relevante and not has_keywords:
        mask_pos = df["es_relevante"].astype(bool)
    elif has_relevante and has_keywords:
        mask_pos = df["es_relevante"].astype(bool) | (
            df["raw_keywords"].notna() & (df["raw_keywords"] != "")
        )
    elif has_keywords:
        mask_pos = df["raw_keywords"].notna() & (df["raw_keywords"] != "")
    else:
        return [], []

    # Máscara de negativos: sin señal positiva + CPV no-TI
    if has_cpv:
        mask_neg_cpv = df["cpv"].notna() & ~(
            df["cpv"].str.startswith("48") | df["cpv"].str.startswith("72")
        )
    else:
        mask_neg_cpv = ~mask_pos

    mask_neg = ~mask_pos & mask_neg_cpv

    pos_rows = df[mask_pos]
    neg_rows = df[mask_neg]

    pos_texts = [_text_for_row(r) for r in pos_rows.to_dict("records")]
    neg_texts_all = [_text_for_row(r) for r in neg_rows.to_dict("records")]

    # Balancear: máx. 2x positivos en negativos
    max_neg = min(len(neg_texts_all), len(pos_texts) * 2)
    if max_neg < len(neg_texts_all):
        rng = np.random.default_rng(42)
        idx = rng.choice(len(neg_texts_all), max_neg, replace=False)
        idx_sorted = sorted(idx)
        neg_texts = [neg_texts_all[i] for i in idx_sorted]
    else:
        neg_texts = neg_texts_all

    texts = pos_texts + neg_texts
    labels = [1] * len(pos_texts) + [0] * len(neg_texts)
    return texts, labels


def _expected_calibration_error(y_true: Any, y_proba: Any, n_bins: int = 10) -> float:
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
