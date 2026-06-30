"""Construcción del pipeline sklearn y utilidades de features para el clasificador SAP.

Contiene:
  - ``_make_pipeline()`` — FeatureUnion(TF-IDF word + char_wb) + MaxAbsScaler + CalibratedLR
  - ``_augment_text()`` — añade tokens estructurales (CPV, importe) al texto
  - ``_build_dataset()`` — construye (texts, labels) desde un DataFrame
  - ``_expected_calibration_error()`` — ECE con bins equi-anchos
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, overload

from sklearn.base import BaseEstimator, TransformerMixin

from config.keywords import TECH_LABELS
from observability.logging import get_logger

if TYPE_CHECKING:
    import pandas as pd

log = get_logger(__name__)

_VALID_LABELS: frozenset[str] = frozenset(TECH_LABELS)


class SentenceEmbeddingTransformer(BaseEstimator, TransformerMixin):  # type: ignore[misc]
    """Wraps sentence-transformers to produce dense embeddings for sklearn pipelines.

    Requires: pip install sentence-transformers (optional dependency).
    """

    def __init__(
        self, model_name: str = "paraphrase-multilingual-MiniLM-L6-v2", batch_size: int = 64
    ):
        self.model_name = model_name
        self.batch_size = batch_size
        self._model = None

    def fit(self, X: Any, y: Any = None) -> SentenceEmbeddingTransformer:
        return self

    def transform(self, X: Any) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        texts = list(X) if not isinstance(X, list) else X
        assert self._model is not None
        return self._model.encode(texts, batch_size=self.batch_size, show_progress_bar=False)


def _make_pipeline(*, calibrate: bool = True) -> Any:
    """Construye el pipeline sklearn con FeatureUnion + LogReg.

    Args:
        calibrate: Si True (default), envuelve el clasificador en
            ``CalibratedClassifierCV`` para obtener probabilidades calibradas.
            Si False, usa LogisticRegression directamente (más rápido, útil para
            CV y scoring donde la calibración no es necesaria).
    """
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
    clf_step: Any
    if calibrate:
        from sklearn.calibration import CalibratedClassifierCV

        clf_step = CalibratedClassifierCV(base_lr, cv=5, method="sigmoid")
    else:
        clf_step = base_lr

    return Pipeline(
        [
            ("features", feature_union),
            ("scaler", MaxAbsScaler()),
            ("clf", clf_step),
        ]
    )


def _make_pipeline_with_embeddings() -> Any:
    """Construye el pipeline sklearn con FeatureUnion(TF-IDF word + char + embeddings)."""
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
            (
                "embeddings",
                SentenceEmbeddingTransformer(),
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


def _tune_pipeline(
    X: list[str],
    y: list[int],
    cv: int = 3,
    n_iter: int = 20,
) -> tuple[Any, dict[str, Any]]:
    """Run RandomizedSearchCV to find best hyperparameters.

    Returns (best_pipeline, best_params).
    """
    from sklearn.model_selection import RandomizedSearchCV

    pipe = _make_pipeline()
    param_distributions = {
        "clf__estimator__C": [0.01, 0.1, 0.5, 1.0, 5.0, 10.0],
        "features__word__max_features": [10000, 15000, 20000, 30000],
        "features__char__max_features": [10000, 15000, 20000],
        "features__word__ngram_range": [(1, 1), (1, 2), (1, 3)],
        "features__word__min_df": [1, 2, 3],
    }
    search = RandomizedSearchCV(
        pipe,
        param_distributions=param_distributions,
        scoring="f1",
        n_iter=n_iter,
        cv=cv,
        random_state=42,
        n_jobs=-1,
    )
    search.fit(X, y)
    return search.best_estimator_, search.best_params_


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
        # Enriched CPV taxonomy: division (2 digits) and group (4 digits)
        if len(cpv_clean) >= 2:
            parts.append(f"CPV2_{cpv_clean[:2]}")
        if len(cpv_clean) >= 4:
            parts.append(f"CPV4_{cpv_clean[:4]}")
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


def validate_training_data(
    df: pd.DataFrame,
    min_text_len: int = 10,
    min_minority_pct: float = 0.05,
    *,
    label_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Valida calidad del DataFrame antes del entrenamiento.

    Args:
        df: DataFrame con columnas titulo, descripcion y etiquetas.
        min_text_len: Longitud mínima del texto concatenado (titulo + descripcion).
        min_minority_pct: Fracción mínima de la clase minoritaria (binario) o
            tasa mínima de positivos por columna (multi-label).
        label_columns: Si se pasa, valida en modo multi-label comprobando que
            cada columna tiene >= min_minority_pct de positivos.

    Returns:
        El mismo DataFrame sin modificaciones.

    Raises:
        ValueError: Si la distribución de labels viola min_minority_pct.
    """
    n_rows = len(df)
    log.info("validate_training_data.start", n_rows=n_rows)

    # ── Text length check ──────────────────────────────────────────────
    titulo = df["titulo"].fillna("") if "titulo" in df.columns else pd.Series("", index=df.index)
    desc = (
        df["descripcion"].fillna("")
        if "descripcion" in df.columns
        else pd.Series("", index=df.index)
    )
    combined = (titulo + " " + desc).str.strip() if n_rows > 0 else pd.Series(dtype=str)
    if n_rows > 0:
        lengths = combined.str.len()
        short_mask = lengths <= min_text_len
        n_short = int(short_mask.sum())
        if n_short > 0:
            log.warning(
                "validate_training_data.short_texts",
                n_short=n_short,
                pct=round(n_short / n_rows * 100, 1),
                min_text_len=min_text_len,
            )
        mean_len = float(lengths.mean())
    else:
        mean_len = 0.0

    # ── Duplicate ID check ─────────────────────────────────────────────
    for id_col in ("id", "id_externo"):
        if id_col in df.columns:
            n_dup = int(df[id_col].dropna().duplicated().sum())
            if n_dup > 0:
                log.warning(
                    "validate_training_data.duplicate_ids",
                    column=id_col,
                    n_duplicates=n_dup,
                )

    # ── Null percentage ────────────────────────────────────────────────
    pct_nulls = (
        float(df[["titulo", "descripcion"]].isnull().mean().mean() * 100) if n_rows > 0 else 0.0
    )

    # ── Label distribution ─────────────────────────────────────────────
    if label_columns:
        # Multi-label mode
        for col in label_columns:
            if col not in df.columns:
                continue
            pos_rate = float(df[col].sum()) / n_rows if n_rows > 0 else 0.0
            log.info(
                "validate_training_data.label_dist",
                label=col,
                positive_rate=round(pos_rate, 4),
                n_positive=int(df[col].sum()),
            )
            if pos_rate < min_minority_pct:
                raise ValueError(
                    f"Label '{col}' has only {pos_rate:.1%} positives "
                    f"(minimum {min_minority_pct:.1%}). Not enough signal to train."
                )
    else:
        # Binary mode — check via es_relevante / raw_keywords proxies
        # Log overall distribution info
        if "es_relevante" in df.columns:
            vals = df["es_relevante"].value_counts(normalize=True)
            minority_pct = float(vals.min()) if len(vals) >= 2 else 0.0
            log.info(
                "validate_training_data.label_dist",
                distribution=vals.to_dict(),
                minority_pct=round(minority_pct, 4),
            )
            if len(vals) >= 2 and minority_pct < min_minority_pct:
                raise ValueError(
                    f"Minority class is only {minority_pct:.1%} of data "
                    f"(minimum {min_minority_pct:.1%}). Dataset too imbalanced."
                )

    log.info(
        "validate_training_data.summary",
        total_rows=n_rows,
        mean_text_len=round(mean_len, 1),
        pct_nulls=round(pct_nulls, 1),
    )
    return df


@overload
def _build_dataset(df: pd.DataFrame) -> tuple[list[str], list[int]]: ...


@overload
def _build_dataset(
    df: pd.DataFrame, *, return_weights: Literal[False]
) -> tuple[list[str], list[int]]: ...


@overload
def _build_dataset(
    df: pd.DataFrame, *, return_weights: Literal[True]
) -> tuple[list[str], list[int], list[float]]: ...


def _build_dataset(
    df: pd.DataFrame, *, return_weights: bool = False
) -> tuple[list[str], list[int]] | tuple[list[str], list[int], list[float]]:
    """Construye el dataset de entrenamiento desde el DataFrame.

    Fuentes de etiqueta (prioridad descendente):
      1. ``es_relevante`` columna (feedback humano explícito).
      2. ``raw_keywords`` IS NOT NULL → positivo.
      Negativos: ``raw_keywords`` IS NULL + CPV fuera del rango TI (no 48/72).
    Aumenta los textos con tokens CPV e importe si las columnas están presentes.

    Preserva el orden del df para que el split temporal en train() sea correcto.

    Args:
        df: DataFrame con las licitaciones.
        return_weights: Si ``True``, devuelve además una lista de pesos de
            muestra (PU learning). Los negativos *ambiguos* —CPV TI (48/72)
            sin keywords, potenciales SAP no detectados— reciben
            ``ML_PU_UNLABELED_WEIGHT`` en vez de 1.0, reduciendo el sesgo de
            aprender el filtro de keywords como ground truth.
    """
    import numpy as np

    has_cpv = "cpv" in df.columns
    has_importe = "importe" in df.columns
    has_keywords = "raw_keywords" in df.columns
    has_relevante = "es_relevante" in df.columns

    validate_training_data(df)

    def _text_for_row(row: dict[str, Any]) -> str:
        titulo = str(row.get("titulo", "") or "")
        desc = str(row.get("descripcion", "") or "")
        text = (titulo + " " + desc).strip()
        cpv = str(row.get("cpv", "") or "") if has_cpv else None
        importe = row.get("importe") if has_importe else None
        return _augment_text(text, cpv=cpv or None, importe=float(importe) if importe else None)

    # PU learning: un negativo con CPV TI (48/72) y sin keywords podría ser una
    # licitación SAP no detectada por el filtro → "unlabeled", no negativo de
    # confianza plena. Se marca como ambiguo para asignarle menor peso.
    def _is_ambiguous_neg(row: dict[str, Any]) -> bool:
        if not has_cpv:
            return False
        cpv_val = str(row.get("cpv", "") or "").strip()
        return cpv_val.startswith(("48", "72"))

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
        return ([], [], []) if return_weights else ([], [])

    # Máscara de negativos: sin señal positiva.
    # Incluye CPV 48/72 (TI) sin raw_keywords como hard negatives — estas
    # licitaciones son de TI pero no de SAP, y son cruciales para que el
    # modelo aprenda a distinguir SAP de otros proveedores TI.
    mask_neg = ~mask_pos

    pos_rows = df[mask_pos]
    neg_rows = df[mask_neg]

    pos_records = pos_rows.to_dict("records")
    neg_records = neg_rows.to_dict("records")
    pos_texts = [_text_for_row(r) for r in pos_records]  # type: ignore[arg-type]
    neg_texts_all = [_text_for_row(r) for r in neg_records]  # type: ignore[arg-type]
    neg_ambiguous_all = [_is_ambiguous_neg(r) for r in neg_records]  # type: ignore[arg-type]

    # Balancear: máx. 2x positivos en negativos
    max_neg = min(len(neg_texts_all), len(pos_texts) * 2)
    if max_neg < len(neg_texts_all):
        rng = np.random.default_rng(42)
        idx = rng.choice(len(neg_texts_all), max_neg, replace=False)
        idx_sorted = sorted(idx)
        neg_texts = [neg_texts_all[i] for i in idx_sorted]
        neg_ambiguous = [neg_ambiguous_all[i] for i in idx_sorted]
    else:
        neg_texts = neg_texts_all
        neg_ambiguous = neg_ambiguous_all

    texts = pos_texts + neg_texts
    labels = [1] * len(pos_texts) + [0] * len(neg_texts)
    if not return_weights:
        return texts, labels

    from config import settings

    unlabeled_w = float(getattr(settings, "ML_PU_UNLABELED_WEIGHT", 0.5))
    weights = [1.0] * len(pos_texts) + [(unlabeled_w if amb else 1.0) for amb in neg_ambiguous]
    return texts, labels, weights


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


# ---------------------------------------------------------------------------
# Multi-label support (technology classifier)
# ---------------------------------------------------------------------------

# Stopwords de dominio: boilerplate frecuente en pliegos de licitaciones del SP
# que aporta cero señal técnica y diluye el TF-IDF. Se combinan con stopwords
# castellanas estándar (cargadas dinámicamente vía sklearn en _make_tech_pipeline).
SPANISH_PROCUREMENT_STOPWORDS: list[str] = [
    "sociedad",
    "anonima",
    "anónima",
    "limitada",
    "sl",
    "sa",
    "sau",
    "presupuesto",
    "base",
    "licitacion",
    "licitación",
    "valor",
    "estimado",
    "iva",
    "euros",
    "eur",
    "pliego",
    "pliegos",
    "clausulas",
    "cláusulas",
    "lote",
    "lotes",
    "expediente",
    "expedientes",
    "adjudicatario",
    "adjudicación",
    "adjudicacion",
    "contrato",
    "contratacion",
    "contratación",
    "objeto",
    "prescripciones",
    "tecnicas",
    "técnicas",
    "administrativas",
    "particulares",
    "organo",
    "órgano",
    "contratante",
    "procedimiento",
    "abierto",
    "restringido",
    "negociado",
    "anuncio",
    "publicacion",
    "publicación",
    "documento",
    "documentacion",
    "documentación",
    "memoria",
    "informe",
    "expediente",
    "ley",
    "real",
    "decreto",
    "articulo",
    "artículo",
    "boletin",
    "boletín",
    "oficial",
    "estado",
    "doue",
]


def _make_tech_pipeline(
    *,
    fragile: bool = False,
    fragile_c: float = 0.3,
    use_domain_stopwords: bool = True,
) -> Any:
    """Pipeline para una sola tecnología (binario, OneVsRest-friendly).

    Args:
        fragile: Si True usa regularización más fuerte (C bajo) para tier
            con pocos positivos (20-49 ejemplos).
        fragile_c: Valor de C para tier frágil.
        use_domain_stopwords: Añade el set de boilerplate de licitaciones.

    Returns:
        sklearn Pipeline calibrado (TF-IDF word + MaxAbsScaler + CalibratedLR).
    """
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import MaxAbsScaler

    stop_words = SPANISH_PROCUREMENT_STOPWORDS if use_domain_stopwords else None

    # Para reconocimiento de proveedores (SAP, Oracle, Salesforce…) los word
    # n-grams son suficientes: son nombres propios que aparecen como tokens
    # completos. El char_wb se omite porque en textos largos de licitaciones
    # genera vocabularios enormes y ralentiza drásticamente el entrenamiento.
    vectorizer = TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        max_features=15_000,
        sublinear_tf=True,
        min_df=2,
        strip_accents="unicode",
        stop_words=stop_words,
    )
    c_value = fragile_c if fragile else 1.0
    base_lr = LogisticRegression(
        C=c_value,
        max_iter=300,
        class_weight="balanced",
        solver="lbfgs",
        random_state=42,
    )
    return Pipeline(
        [
            ("features", vectorizer),
            ("scaler", MaxAbsScaler()),
            ("clf", CalibratedClassifierCV(base_lr, cv=3, method="sigmoid")),
        ]
    )


def _parse_tecnologia_csv(value: Any) -> list[str]:
    """Normaliza el valor CSV de la columna ``tecnologia`` a una lista de labels.

    Tolera None, NaN, strings vacíos, espacios y mayúsculas inconsistentes.
    """
    if value is None:
        return []
    if isinstance(value, float):  # NaN
        import math

        if math.isnan(value):
            return []
    s = str(value).strip()
    if not s:
        return []
    parts = [p.strip().upper() for p in s.split(",") if p.strip()]
    # Filtrar etiquetas desconocidas y deduplicar preservando orden
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p not in seen and p in _VALID_LABELS:
            seen.add(p)
            out.append(p)
    return out


def _build_multilabel_dataset(
    df: pd.DataFrame,
    labels: list[str],
) -> tuple[list[str], Any, list[int]]:
    """Construye (textos_aumentados, Y_binaria, positivos_por_label).

    Args:
        df: DataFrame con columnas titulo, descripcion, tecnologia (CSV).
            Opcionalmente: cpv, importe.
        labels: Lista canónica de tecnologías (orden columnar de Y).

    Returns:
        ``texts``: lista de strings (título + descripción + tokens estructurales).
        ``Y``: matriz numpy shape ``(n, len(labels))`` con 0/1.
        ``positives``: nº de positivos por label (mismo orden que ``labels``).
    """
    import numpy as np

    has_cpv = "cpv" in df.columns
    has_importe = "importe" in df.columns
    has_tecnologia = "tecnologia" in df.columns

    validate_training_data(df, label_columns=labels)

    label_to_idx = {lbl: i for i, lbl in enumerate(labels)}
    n_rows = len(df)
    Y = np.zeros((n_rows, len(labels)), dtype=np.int8)
    texts: list[str] = []

    rows = df.to_dict("records")
    for i, row in enumerate(rows):
        titulo = str(row.get("titulo", "") or "")
        desc = str(row.get("descripcion", "") or "")
        base = (titulo + " " + desc).strip()
        cpv = str(row.get("cpv", "") or "") if has_cpv else None
        importe_val = row.get("importe") if has_importe else None
        try:
            importe_f = float(importe_val) if importe_val else None
        except (TypeError, ValueError):
            importe_f = None
        texts.append(_augment_text(base[:1000], cpv=cpv or None, importe=importe_f))

        if has_tecnologia:
            for tag in _parse_tecnologia_csv(row.get("tecnologia")):
                idx = label_to_idx.get(tag)
                if idx is not None:
                    Y[i, idx] = 1

    positives = [int(Y[:, j].sum()) for j in range(len(labels))]
    return texts, Y, positives


def _keyword_fallback_score(text: str, keywords: list[str]) -> float:
    """Fracción de keywords del label presentes en el texto (en minúsculas).

    Usado para tecnologías en tier "rules" (sin modelo entrenado por falta
    de positivos). Devuelve un valor en ``[0, 1]`` apto para usarse como
    proxy de probabilidad — no calibrado, pero monótono en señal.
    """
    if not keywords:
        return 0.0
    t = text.lower()
    matches = sum(1 for kw in keywords if kw.lower() in t)
    return matches / len(keywords)
