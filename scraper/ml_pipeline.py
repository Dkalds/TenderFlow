"""Construcción del pipeline sklearn y utilidades de features para el clasificador SAP.

Contiene:
  - ``_make_pipeline()`` — FeatureUnion(TF-IDF word + char_wb) + MaxAbsScaler + CalibratedLR
  - ``_augment_text()`` — añade tokens estructurales (CPV, importe) al texto
  - ``build_dataset_rows()`` — filas del dataset **en el orden del DataFrame**
  - ``_build_dataset()`` — atajo (texts, labels) sobre lo anterior
  - ``_expected_calibration_error()`` — ECE con bins equi-anchos
"""

from __future__ import annotations

from dataclasses import dataclass
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

    def __init__(self, model_name: str | None = None, batch_size: int = 64):
        # El default estaba hardcodeado a MiniLM-**L6**-v2 mientras
        # ``settings.EMBEDDING_MODEL`` (y ``services.embeddings``) usan
        # **L12**-v2: dos modelos de embeddings distintos conviviendo en el
        # mismo repo, y el de este pipeline no se podía cambiar por config.
        from config import settings

        self.model_name = model_name or str(settings.EMBEDDING_MODEL)
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


def _make_pipeline_with_embeddings(*, calibrate: bool = True) -> Any:
    """Construye el pipeline sklearn con FeatureUnion(TF-IDF word + char + embeddings).

    Args:
        calibrate: Si True (default), envuelve LogReg en ``CalibratedClassifierCV``.
            Poner a False cuando la calibración la aplica una capa externa
            (evita la doble calibración que degrada las probabilidades).
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


def _augment_text(
    text: str,
    *,
    cpv: str | None = None,
    importe: float | None = None,
    organo: str | None = None,
) -> str:
    """Añade tokens estructurales al texto para mejorar la discriminación.

    CPV: Los códigos 48xxx/72xxx son señal TI fuerte → token "CPV_TI".
         Cualquier otro CPV → token "CPV_NO_TI".
    Importe: Se codifica en rangos logarítmicos (k€) como tokens especiales, más
         un bucket fino (decil log) para mayor resolución que los 5 rangos.
    Órgano: Hash estable del órgano de contratación a un bucket → token
         "ORG_<bucket>". Captura que ciertos órganos compran SAP de forma
         recurrente. Solo se emite si se pasa ``organo`` (los call sites lo
         propagan según ``ML_USE_ORGANO_FEATURE`` para evitar skew train/serve).

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
        # Bucket fino: log10*10 redondeado → granularidad de 0.1 en log10
        # (~25% de importe), más informativo que los 5 rangos gruesos.
        parts.append(f"IMP_{round(log_imp * 10)}")
    if organo:
        import hashlib
        import unicodedata

        # Normalización robusta: minúsculas, sin acentos, solo alfanumérico.
        decomposed = unicodedata.normalize("NFKD", organo.lower())
        stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
        org_norm = " ".join("".join(ch if ch.isalnum() else " " for ch in stripped).split())
        if org_norm:
            digest = hashlib.sha256(org_norm.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % 4096
            parts.append(f"ORG_{bucket} ORG_{bucket}")  # duplicado para mayor peso
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
    import pandas as pd  # runtime: las ramas de abajo construyen Series

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


@dataclass(frozen=True)
class DatasetRow:
    """Una fila del dataset, con todo lo que el split necesita para no filtrar.

    ``_build_dataset`` devolvía solo ``(texts, labels)`` concatenando el bloque
    de positivos y luego el de negativos, lo que destruía el orden del
    DataFrame y dejaba el split temporal de ``SAPClassifier.train`` sin nada
    que cortar (ver el docstring de :func:`build_dataset_rows`). Esta fila
    transporta además la fecha y la clave de grupo, para que el split se pueda
    hacer por tiempo y por expediente en vez de por posición.
    """

    text: str
    label: int
    weight: float
    fecha: str | None
    grupo: str
    # ¿CPV 48/72? Es la población sobre la que el modelo decide de verdad en
    # producción, así que las métricas restringidas a ella son las que hay
    # que mirar (``f1_ti`` / ``pr_auc_ti``).
    cpv_ti: bool = False


def _clave_grupo(titulo: str, descripcion: str) -> str:
    """Clave de agrupación de licitaciones que son la *misma* convocatoria.

    Un expediente aparece varias veces en la BD: un anuncio por lote, las
    prórrogas, y las republicaciones con distinto ``id_externo`` y un título
    casi idéntico. Con un split aleatorio esas casi-duplicadas caen a ambos
    lados y el modelo "acierta" en test lo que ya memorizó en train, inflando
    F1 y PR-AUC. Agrupándolas, ninguna convocatoria puede estar en los dos
    lados del corte.

    La normalización quita acentos, mayúsculas, puntuación y **dígitos** —
    que es justo lo que distingue "Lote 3" de "Lote 7" o el año de la
    prórroga— y colapsa espacios.
    """
    import hashlib
    import unicodedata

    base = f"{titulo} {descripcion}".strip()
    decomposed = unicodedata.normalize("NFKD", base.lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    solo_letras = "".join(ch if ch.isalpha() or ch.isspace() else " " for ch in stripped)
    norm = " ".join(solo_letras.split())[:120]
    if not norm:
        # Sin texto no hay forma de agrupar: cada fila es su propio grupo.
        return f"vacio-{hashlib.sha256(base.encode('utf-8')).hexdigest()[:16]}"
    return norm


def _fecha_clave(valor: Any) -> str | None:
    """Normaliza ``fecha_publicacion`` a ``YYYY-MM-DD`` (o ``None`` si no sirve).

    Las columnas de fecha son TEXT y admiten basura; comparar strings de
    longitud distinta ordenaría mal, así que se recorta a la fecha ISO.
    """
    if valor is None:
        return None
    texto = str(valor).strip()
    if len(texto) < 10:
        return None
    fecha = texto[:10]
    if fecha[4] != "-" or fecha[7] != "-":
        return None
    return fecha


def build_dataset_rows(df: pd.DataFrame) -> list[DatasetRow]:
    """Construye las filas del dataset **preservando el orden del DataFrame**.

    Fuentes de etiqueta (prioridad descendente):
      1. ``es_relevante`` cuando está presente para esa fila — es la etiqueta
         ya resuelta por el caller (``train_from_db`` y
         ``concept_drift._fetch_training_dataframe`` mezclan ahí keywords y
         feedback humano, con el humano ganando).
      2. ``raw_keywords`` no vacío → positivo, solo para las filas sin
         ``es_relevante``.

    .. note:: Por qué ya no se hace ``es_relevante | raw_keywords``

        La versión anterior recomputaba la prioridad con un ``OR``, lo que
        revertía a positivo cualquier fila que hubiera hecho match de
        keywords — incluidas las que un humano acababa de marcar como **no
        relevantes**. El feedback negativo es el único capaz de corregir los
        falsos positivos del filtro de keywords, así que descartarlo fijaba el
        techo del modelo en "reproducir el filtro" en toda la zona
        ``keyword=True``. Ahora, donde hay etiqueta explícita, esa etiqueta
        manda; el ``OR`` solo se aplica a las filas que no la tienen.

    Negativos: todo lo que no sale positivo, submuestreado a un máximo de 2x
    positivos (semilla fija). El submuestreo elige *qué* negativos entran pero
    **no reordena**: las filas se emiten en el orden original del DataFrame.
    """
    import numpy as np
    import pandas as pd

    has_cpv = "cpv" in df.columns
    has_importe = "importe" in df.columns
    has_keywords = "raw_keywords" in df.columns
    has_relevante = "es_relevante" in df.columns
    has_organo = "organo_contratacion" in df.columns
    has_fecha = "fecha_publicacion" in df.columns

    from config import settings

    use_organo = has_organo and bool(getattr(settings, "ML_USE_ORGANO_FEATURE", False))

    validate_training_data(df)

    def _text_for_row(row: dict[str, Any]) -> str:
        titulo = str(row.get("titulo", "") or "")
        desc = str(row.get("descripcion", "") or "")
        text = (titulo + " " + desc).strip()
        cpv = str(row.get("cpv", "") or "") if has_cpv else None
        importe = row.get("importe") if has_importe else None
        organo = str(row.get("organo_contratacion", "") or "") if use_organo else None
        return _augment_text(
            text,
            cpv=cpv or None,
            importe=float(importe) if importe else None,
            organo=organo or None,
        )

    # PU learning: un negativo con CPV TI (48/72) y sin keywords podría ser una
    # licitación SAP no detectada por el filtro → "unlabeled", no negativo de
    # confianza plena. Se marca como ambiguo para asignarle menor peso.
    def _is_ambiguous_neg(row: dict[str, Any]) -> bool:
        if not has_cpv:
            return False
        cpv_val = str(row.get("cpv", "") or "").strip()
        return cpv_val.startswith(("48", "72"))

    # ── Máscara de positivos ───────────────────────────────────────────────
    mask_kw = df["raw_keywords"].notna() & (df["raw_keywords"] != "") if has_keywords else None

    if has_relevante:
        relevante = df["es_relevante"]
        explicita = relevante.notna()
        # ``to_numeric`` antes de ``fillna``: sobre una columna object,
        # ``fillna(0).astype(float)`` avisa de downcasting implícito.
        pos_relevante = pd.to_numeric(relevante, errors="coerce").fillna(0).astype(bool)
        if mask_kw is not None:
            # Donde hay etiqueta explícita manda ella (incluido un 0 que
            # contradice a las keywords); donde no, se cae a las keywords.
            mask_pos = pos_relevante.where(explicita, mask_kw).astype(bool)
        else:
            mask_pos = pos_relevante
    elif mask_kw is not None:
        mask_pos = mask_kw
    else:
        return []

    records: list[dict[str, Any]] = df.to_dict("records")  # type: ignore[assignment]
    # ``mask_pos`` conserva el índice del df; se recorre por posición.
    pos_flags = [bool(v) for v in mask_pos.to_numpy()]

    neg_positions = [i for i, es_pos in enumerate(pos_flags) if not es_pos]
    n_pos = len(pos_flags) - len(neg_positions)

    # Balancear: máx. 2x positivos en negativos. Se eligen posiciones, no se
    # reordena nada: el orden del DataFrame se preserva al emitir.
    max_neg = min(len(neg_positions), n_pos * 2)
    if max_neg < len(neg_positions):
        rng = np.random.default_rng(42)
        elegidos = rng.choice(len(neg_positions), max_neg, replace=False)
        neg_seleccionados = {neg_positions[i] for i in elegidos}
    else:
        neg_seleccionados = set(neg_positions)

    unlabeled_w = float(getattr(settings, "ML_PU_UNLABELED_WEIGHT", 0.5))

    filas: list[DatasetRow] = []
    for i, row in enumerate(records):
        es_pos = pos_flags[i]
        if not es_pos and i not in neg_seleccionados:
            continue
        peso = 1.0
        if not es_pos and _is_ambiguous_neg(row):
            peso = unlabeled_w
        filas.append(
            DatasetRow(
                text=_text_for_row(row),
                label=1 if es_pos else 0,
                weight=peso,
                fecha=_fecha_clave(row.get("fecha_publicacion")) if has_fecha else None,
                grupo=_clave_grupo(
                    str(row.get("titulo", "") or ""),
                    str(row.get("descripcion", "") or ""),
                ),
                cpv_ti=str(row.get("cpv", "") or "").strip().startswith(("48", "72")),
            )
        )
    return filas


@dataclass(frozen=True)
class DatasetSplit:
    """Partición train/test del dataset, con la estrategia que la produjo."""

    train: list[int]
    test: list[int]
    strategy: str  # "temporal" | "grouped_random"
    fecha_corte: str | None
    descartadas_por_grupo: int


class TemporalSplitImposible(RuntimeError):
    """Hay fechas pero no admiten un corte temporal con ambas clases a los dos lados.

    No se degrada a un split aleatorio: un split aleatorio sobre datos
    temporales no es un *fallback*, es **otra métrica** —mide interpolación,
    no predicción de licitaciones futuras— y publicarla bajo los mismos
    nombres (``f1``, ``pr_auc``) es lo que hacía que las cifras del registry
    no significaran lo que decían.
    """


_TEST_SHARE = 0.20
_MIN_TEST_ROWS = 10
# Un "grupo" que se lleva más de esta fracción del dataset no es un expediente:
# es la normalización de :func:`_clave_grupo` colapsando de más (p. ej. cientos
# de anuncios cuyo título solo difiere en un número de expediente). Tratarlo
# como una unidad indivisible dejaría el corte temporal sin salida, así que sus
# filas vuelven a agruparse individualmente y se avisa.
_MAX_GROUP_SHARE = 0.25


def _grupos_efectivos(filas: list[DatasetRow]) -> list[str]:
    """Claves de grupo, deshaciendo los colapsos patológicos de la normalización.

    :func:`_clave_grupo` quita los dígitos, que es lo que hace que "Lote 3" y
    "Lote 7" del mismo expediente compartan clave. El efecto secundario es que
    un corpus donde muchos títulos solo se diferencian en un número puede
    acabar con un único grupo gigante — y un grupo indivisible que se lleva
    medio dataset no deja hacer ningún corte. Por encima de
    ``_MAX_GROUP_SHARE`` se asume que la clave no identifica un expediente y
    esas filas se desagrupan.
    """
    from collections import Counter

    claves = [f.grupo for f in filas]
    tope = max(1, int(len(filas) * _MAX_GROUP_SHARE))
    sobredimensionados = {g for g, c in Counter(claves).items() if c > tope}
    if not sobredimensionados:
        return claves
    log.warning(
        "split_dataset.grupos_sobredimensionados",
        n_grupos=len(sobredimensionados),
        tope=tope,
        n_filas=len(filas),
        hint=(
            "La clave de grupo colapsa demasiadas licitaciones distintas; "
            "esas filas se tratan como grupos individuales para el split."
        ),
    )
    return [f"{g}#{i}" if g in sobredimensionados else g for i, g in enumerate(claves)]


def split_dataset_rows(filas: list[DatasetRow], *, seed: int = 42) -> DatasetSplit:
    """Parte las filas en train/test sin fuga temporal ni de grupo.

    **Temporal** (cuando hay fechas): se busca la fecha de corte que deja
    ~20% de filas después. ``train`` son las filas con fecha ≤ corte y
    ``test`` las posteriores **cuyo grupo no aparece antes del corte**. Las
    filas posteriores al corte que pertenecen a un grupo ya visto en train se
    **descartan**: dejarlas en test filtraría el expediente y dejarlas en
    train filtraría el futuro.

    **Agrupado aleatorio** (cuando no hay ninguna fecha): ``GroupShuffleSplit``
    sobre la clave de grupo. No hay información temporal que respetar, pero sí
    hay que impedir que lotes y republicaciones del mismo expediente caigan a
    los dos lados.

    Raises:
        TemporalSplitImposible: si hay fechas pero ningún corte deja las dos
            clases a ambos lados con suficientes filas en test.
    """
    n = len(filas)
    if n == 0:
        return DatasetSplit([], [], "grouped_random", None, 0)

    grupos = _grupos_efectivos(filas)
    fechas = [f.fecha for f in filas]
    con_fecha = [f for f in fechas if f is not None]

    # ── Sin ninguna fecha: split agrupado aleatorio ───────────────────────
    if not con_fecha:
        from sklearn.model_selection import GroupShuffleSplit

        etiquetas = [f.label for f in filas]
        splitter = GroupShuffleSplit(n_splits=1, test_size=_TEST_SHARE, random_state=seed)
        train_idx, test_idx = next(splitter.split(range(n), etiquetas, groups=grupos))
        log.info(
            "split_dataset.grouped_random",
            n_train=len(train_idx),
            n_test=len(test_idx),
            n_grupos=len(set(grupos)),
        )
        return DatasetSplit(
            [int(i) for i in train_idx], [int(i) for i in test_idx], "grouped_random", None, 0
        )

    # ── Con fechas: corte temporal por fecha, no por posición ─────────────
    # Las filas sin fecha no pueden situarse a un lado del corte: se descartan
    # del split temporal en vez de asumir que son antiguas.
    idx_datados = [i for i, f in enumerate(fechas) if f is not None]
    candidatas = sorted(set(con_fecha))

    # Primer grupo (por fecha mínima) de cada clave, para la regla de grupo.
    primera_fecha_grupo: dict[str, str] = {}
    for i in idx_datados:
        g = grupos[i]
        fecha_i = fechas[i]
        assert fecha_i is not None  # garantizado por idx_datados
        anterior = primera_fecha_grupo.get(g)
        if anterior is None or fecha_i < anterior:
            primera_fecha_grupo[g] = fecha_i

    def _particion(corte: str) -> tuple[list[int], list[int], int]:
        train: list[int] = []
        test: list[int] = []
        descartadas = 0
        for i in idx_datados:
            fecha_i = fechas[i]
            assert fecha_i is not None
            if fecha_i <= corte:
                train.append(i)
            elif primera_fecha_grupo[grupos[i]] > corte:
                test.append(i)
            else:
                descartadas += 1
        return train, test, descartadas

    # Se prueban los cortes por cercanía al 20% objetivo hasta dar con uno
    # válido: el más cercano puede dejar una sola clase en test.
    n_datadas = len(idx_datados)
    por_cercania = sorted(
        candidatas,
        key=lambda c: abs(
            sum(1 for i in idx_datados if (fechas[i] or "") > c) / n_datadas - _TEST_SHARE
        ),
    )
    for corte in por_cercania:
        train, test, descartadas = _particion(corte)
        if len(test) < _MIN_TEST_ROWS or not train:
            continue
        if len({filas[i].label for i in train}) < 2:
            continue
        if len({filas[i].label for i in test}) < 2:
            continue
        log.info(
            "split_dataset.temporal",
            fecha_corte=corte,
            n_train=len(train),
            n_test=len(test),
            descartadas_por_grupo=descartadas,
            n_sin_fecha=n - n_datadas,
        )
        return DatasetSplit(train, test, "temporal", corte, descartadas)

    raise TemporalSplitImposible(
        f"Ningún corte temporal deja las dos clases a ambos lados con >= {_MIN_TEST_ROWS} "
        f"filas en test (n={n}, con fecha={n_datadas}, "
        f"positivos={sum(1 for f in filas if f.label == 1)})."
    )


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
    """Atajo ``(texts, labels[, weights])`` sobre :func:`build_dataset_rows`.

    Se mantiene por compatibilidad con los call sites que solo necesitan los
    textos y las etiquetas. El orden es el del DataFrame de entrada, no el de
    positivos-y-luego-negativos que devolvía antes.
    """
    filas = build_dataset_rows(df)
    texts = [f.text for f in filas]
    labels = [f.label for f in filas]
    if not return_weights:
        return texts, labels
    return texts, labels, [f.weight for f in filas]


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
    *,
    label_column: str = "tecnologia",
) -> tuple[list[str], Any, list[int]]:
    """Construye (textos_aumentados, Y_binaria, positivos_por_label).

    Args:
        df: DataFrame con columnas titulo, descripcion y la columna de
            etiquetas indicada por ``label_column`` (CSV de tecnologías).
            Opcionalmente: cpv, importe.
        labels: Lista canónica de tecnologías (orden columnar de Y).
        label_column: Columna de la que salen las etiquetas. Por defecto
            ``"tecnologia"``, que es el resultado de ``matches_technology()``
            —el mismo regex que ve el texto de entrada, así que entrenar
            contra ella es circular. Los call sites que disponen de una
            etiqueta independiente (humana o LLM) deben pasar aquí su
            columna resuelta; ver ``scraper.tech_classifier``.

    Returns:
        ``texts``: lista de strings (título + descripción + tokens estructurales).
        ``Y``: matriz numpy shape ``(n, len(labels))`` con 0/1.
        ``positives``: nº de positivos por label (mismo orden que ``labels``).
    """
    import numpy as np

    has_cpv = "cpv" in df.columns
    has_importe = "importe" in df.columns
    has_tecnologia = label_column in df.columns

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
            for tag in _parse_tecnologia_csv(row.get(label_column)):
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
