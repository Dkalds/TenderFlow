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

    # Máscara de negativos: sin señal positiva.
    # Incluye CPV 48/72 (TI) sin raw_keywords como hard negatives — estas
    # licitaciones son de TI pero no de SAP, y son cruciales para que el
    # modelo aprenda a distinguir SAP de otros proveedores TI.
    mask_neg = ~mask_pos

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


# ---------------------------------------------------------------------------
# Multi-label support (technology classifier)
# ---------------------------------------------------------------------------

# Stopwords de dominio: boilerplate frecuente en pliegos de licitaciones del SP
# que aporta cero señal técnica y diluye el TF-IDF. Se combinan con stopwords
# castellanas estándar (cargadas dinámicamente vía sklearn en _make_tech_pipeline).
SPANISH_PROCUREMENT_STOPWORDS: list[str] = [
    "sociedad", "anonima", "anónima", "limitada", "sl", "sa", "sau",
    "presupuesto", "base", "licitacion", "licitación",
    "valor", "estimado", "iva", "euros", "eur",
    "pliego", "pliegos", "clausulas", "cláusulas",
    "lote", "lotes", "expediente", "expedientes",
    "adjudicatario", "adjudicación", "adjudicacion",
    "contrato", "contratacion", "contratación",
    "objeto", "prescripciones", "tecnicas", "técnicas",
    "administrativas", "particulares",
    "organo", "órgano", "contratante",
    "procedimiento", "abierto", "restringido", "negociado",
    "anuncio", "publicacion", "publicación",
    "documento", "documentacion", "documentación",
    "memoria", "informe", "expediente",
    "ley", "real", "decreto", "articulo", "artículo",
    "boletin", "boletín", "oficial", "estado", "doue",
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
            con pocos positivos (20–49 ejemplos).
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
    # Deduplicar preservando orden
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p not in seen:
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
