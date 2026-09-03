"""Clasificador multi-tecnología sobre las etiquetas de ``TECHNOLOGY_KEYWORDS``.

Reemplaza el desalineado ``SAPMultiLabelClassifier`` (Cloud/Integración/RRHH/…)
por un OneVsRest cuyas etiquetas son exactamente las claves de
``TECHNOLOGY_KEYWORDS`` (SAP, SALESFORCE, ORACLE, MICROSOFT, SERVICENOW,
WORKDAY, IBM, OPENTEXT, UNIT4, META4, SOPRA, SAGE, INFOR, …).

Circularidad del entrenamiento (por qué existe ``_resolver_label_column``)
--------------------------------------------------------------------------
La columna ``licitaciones.tecnologia`` la escriben los conectores
(``scraper/connectors/pscp.py:336``, ``ted.py:370``, ``regional_rss.py:141``)
llamando a ``matches_technology(titulo, descripcion)``: un regex de keywords
aplicado **al mismo texto** que después ve el modelo. Entrenar contra ella
convierte ``Y[:, j] == 1`` en una función determinista y perfectamente
aprendible del input, así que cada F1 / PR-AUC de ``per_tech`` mide cuánto
**imita** el modelo al regex, no cuánta tecnología detecta. Ese número puede
valer 0.98 con un modelo que no aporta absolutamente nada sobre las keywords.

Para romperla, :meth:`TechnologyClassifier.train` prefiere una etiqueta
**independiente del texto**, en este orden por licitación:

  1. ``tecnologia_humana`` — feedback humano (``ml_feedback`` con
     ``source='human'``: columnas ``tecnologia`` + ``tecnologias_secundarias``).
  2. ``tecnologia_llm``    — etiquetado LLM (``licitacion_tecnologia_pliego``
     con ``method IN ('llm_metadata','llm')`` y ``score`` sobre umbral).
  3. ``tecnologia``        — keywords. **Último recurso**: si el DataFrame no
     trae ninguna de las dos anteriores, el entrenamiento es circular y se
     emite ``log.warning("tech_classifier.circular_labels")``.

Hoy :func:`train_from_db` **no** trae las dos primeras columnas (su SELECT vive
en este módulo por herencia y el SQL nuevo debe ir a ``db/``); ver su docstring
para la query que falta. Mientras tanto el entrenamiento avisa de que es
circular en vez de fingir métricas honestas.

Diseño (3 tiers según número de positivos en la etiqueta resuelta):

  * ``ml_ready``  (≥ ``ML_TECH_MIN_POS_READY``)  : LR calibrada normal,
    threshold optimizado por F1 en **validación** (clamp ``[0.30, 0.85]``).
  * ``fragile``   (≥ ``ML_TECH_MIN_POS_FRAGILE``): LR con C reducido y
    threshold conservador (precisión mínima exigida), también en validación.
  * ``rules``     (resto)                         : fallback a las keywords
    curadas de ``TECHNOLOGY_KEYWORDS`` (mismo featurizer, sin modelo), con
    umbral propio — ver :meth:`TechnologyClassifier._rules_threshold`.

Split y umbrales: train / val / test = 60 / 20 / 20, **estratificado** por
combinación de etiquetas siempre que se pueda. El umbral se elige en ``val`` y
las métricas de ``per_tech`` se reportan en ``test`` **al umbral que se sirve
de verdad** (el de ``_threshold_for``, overrides de settings incluidos).

``SAPClassifier`` binario y la columna ``ml_proba`` se mantienen intactos por
compatibilidad con el pipeline y dashboard existentes.

Persistencia:
    data/models/tech_classifier.pkl   (joblib, compress=3)
    data/models/tech_classifier.sha256

Uso CLI:
    python -m scraper.ml_classifier train-tech
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from config import settings
from config.keywords import TECH_LABELS, TECHNOLOGY_KEYWORDS
from observability.logging import get_logger
from scraper.ml_pipeline import (
    _augment_text,
    _build_multilabel_dataset,
    _keyword_fallback_score,
    _make_tech_pipeline,
)
from shared.model_integrity import verify_model_integrity, write_checksum

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    # Alias local para no repetir la firma genérica de numpy en cada helper.
    # El `Any` del dtype es deliberado: la misma función recibe la matriz de
    # etiquetas (int8) y los vectores de índices (int64).
    _NDArray = np.ndarray[Any, np.dtype[Any]]

log = get_logger(__name__)

_MODEL_PATH = Path(__file__).parents[1] / "data" / "models" / "tech_classifier.pkl"
_TIER_ML_READY = "ml_ready"
_TIER_FRAGILE = "fragile"
_TIER_RULES = "rules"

# ── Resolución de la columna de etiquetas (anti-circularidad) ──────────────
_LABEL_COL_HUMAN = "tecnologia_humana"
_LABEL_COL_LLM = "tecnologia_llm"
_LABEL_COL_KEYWORDS = "tecnologia"
_LABEL_COL_RESOLVED = "tecnologia_resuelta"

#: Fuentes de etiqueta en orden de prioridad descendente: ``(columna, origen)``.
_LABEL_SOURCES: tuple[tuple[str, str], ...] = (
    (_LABEL_COL_HUMAN, "human"),
    (_LABEL_COL_LLM, "llm"),
    (_LABEL_COL_KEYWORDS, "keywords"),
)

#: Separador opcional ``TECNOLOGIA:score`` dentro de ``tecnologia_llm``.
_LLM_SCORE_SEP = ":"

#: Nº mínimo de keywords presentes para que el tier ``rules`` clasifique.
_RULES_MIN_KEYWORDS = 1

#: Por debajo de esto no hay val/test fiables y se entrena con todo.
_MIN_ROWS_FOR_SPLIT = 50

#: Tamaño mínimo de una combinación de etiquetas para estratificar por ella.
#: Se hacen dos splits encadenados, así que hace falta que sobrevivan ≥ 2
#: miembros al primero para que el segundo también pueda estratificar.
_MIN_STRATUM = 4


class LabelResolution(NamedTuple):
    """Columna de etiquetas elegida para entrenar y su procedencia.

    Attributes:
        df: DataFrame a usar (copia superficial con ``tecnologia_resuelta``
            añadida cuando hubo que resolver varias fuentes; el original si no).
        column: Nombre de la columna a pasar a ``_build_multilabel_dataset``.
            Cadena vacía si el DataFrame no trae ninguna fuente de etiqueta.
        circular: ``True`` si **toda** la etiqueta sale de las keywords, es
            decir, si el entrenamiento imita al regex que ve el mismo texto.
        counts: Filas resueltas por cada origen (``human``/``llm``/``keywords``/
            ``sin_etiqueta``).
    """

    df: pd.DataFrame
    column: str
    circular: bool
    counts: dict[str, int]


class _Split(NamedTuple):
    """Índices de train/val/test y si el reparto salió estratificado."""

    train: _NDArray
    val: _NDArray
    test: _NDArray
    stratified: bool
    reason: str


def _tiene_etiqueta(value: Any) -> bool:  # Any: celda cruda de pandas (str/None/NaN)
    """¿Esta celda constituye un pronunciamiento de su fuente?

    ``None``/``NaN`` = la fuente no se pronunció sobre esta licitación. Una
    cadena vacía **sí** es un pronunciamiento ("ninguna tecnología"), y es un
    verdadero negativo valioso: si se tratara como "sin etiqueta" el
    entrenamiento perdería justo los casos que un humano revisó y descartó.
    """
    if value is None:
        return False
    return not (isinstance(value, float) and math.isnan(value))


def _llm_min_score() -> float:
    """Umbral de score bajo el cual una etiqueta LLM no se considera fiable.

    ``ML_TECH_LLM_MIN_SCORE`` no existe todavía en ``config/settings.py``; hasta
    que exista se reutiliza ``PLIEGO_TECH_MIN_SCORE``, que es el corte con el
    que la señal LLM ya se fusiona en ``services/tech_signal.py``.
    """
    crudo: object = getattr(settings, "ML_TECH_LLM_MIN_SCORE", None)
    if crudo is None:
        crudo = getattr(settings, "PLIEGO_TECH_MIN_SCORE", 0.5)
    if isinstance(crudo, int | float | str):
        try:
            return float(crudo)
        except ValueError:
            pass
    log.warning("tech_classifier.llm_min_score_invalido", valor=repr(crudo))
    return 0.5


def _clean_llm_csv(value: Any, min_score: float) -> str:  # Any: celda cruda de pandas
    """Normaliza ``tecnologia_llm`` a un CSV simple filtrando por score.

    Acepta las dos formas que puede traer la query: ``"SAP,ORACLE"`` (ya
    filtrada por ``score >= umbral`` en SQL) y ``"SAP:0.91,ORACLE:0.42"``
    (score por tecnología). La segunda permite aplicar el criterio "score sobre
    umbral" **por tecnología**, que es la granularidad a la que la señal LLM se
    persiste en ``licitacion_tecnologia_pliego``. Las entradas sin score se
    conservan tal cual: se asume que la query ya las filtró.
    """
    out: list[str] = []
    for chunk in str(value).split(","):
        item = chunk.strip()
        if not item:
            continue
        if _LLM_SCORE_SEP in item:
            name, _, raw_score = item.partition(_LLM_SCORE_SEP)
            try:
                if float(raw_score) < min_score:
                    continue
            except ValueError:
                # Score ilegible: se conserva la etiqueta y se deja constancia.
                log.warning("tech_classifier.llm_score_invalido", item=item)
            out.append(name.strip())
        else:
            out.append(item)
    return ",".join(out)


def _resolver_label_column(df: pd.DataFrame) -> LabelResolution:
    """Elige la columna de etiquetas menos circular que traiga el DataFrame.

    Prioridad descendente **por licitación**: ``tecnologia_humana`` >
    ``tecnologia_llm`` > ``tecnologia``. La primera fuente que se pronuncia
    sobre una fila (ver :func:`_tiene_etiqueta`) decide **todas** las
    tecnologías de esa fila.

    La prioridad no puede aplicarse por ``(licitación, tecnología)`` con este
    formato: una columna CSV no sabe expresar "el humano no se pronunció sobre
    ORACLE" —sólo "el humano dijo SAP"—, así que mezclar el SAP humano con el
    ORACLE de keywords en la misma fila inventaría una etiqueta que nadie
    emitió. Para prioridad real por tecnología haría falta que la query trajera
    una fila por ``(licitacion, tecnologia, method)``; ver
    :func:`train_from_db`.

    Returns:
        :class:`LabelResolution`. ``column`` vacío si no hay ninguna fuente.
    """
    presentes = [(col, origen) for col, origen in _LABEL_SOURCES if col in df.columns]
    if not presentes:
        return LabelResolution(df=df, column="", circular=False, counts={})

    independientes = [col for col, _ in presentes if col != _LABEL_COL_KEYWORDS]
    if not independientes:
        # Sólo keywords: el modelo aprenderá el regex que ve el mismo texto.
        n = int(sum(1 for v in df[_LABEL_COL_KEYWORDS] if _tiene_etiqueta(v)))
        log.warning(
            "tech_classifier.circular_labels",
            label_column=_LABEL_COL_KEYWORDS,
            n_filas=n,
            motivo=(
                "El DataFrame sólo trae 'tecnologia', que la escribe "
                "matches_technology() sobre el mismo titulo/descripcion que ve "
                "el modelo: las metricas per_tech miden imitacion del regex, no "
                "deteccion de tecnologia. Alimenta 'tecnologia_humana' y/o "
                "'tecnologia_llm' para romper la circularidad."
            ),
        )
        return LabelResolution(
            df=df,
            column=_LABEL_COL_KEYWORDS,
            circular=True,
            counts={"human": 0, "llm": 0, "keywords": n, "sin_etiqueta": len(df) - n},
        )

    min_score = _llm_min_score()
    counts: dict[str, int] = {"human": 0, "llm": 0, "keywords": 0, "sin_etiqueta": 0}
    resueltas: list[str] = []
    for row in df.to_dict("records"):
        for col, origen in presentes:
            raw = row.get(col)
            if not _tiene_etiqueta(raw):
                continue
            resueltas.append(_clean_llm_csv(raw, min_score) if origen == "llm" else str(raw))
            counts[origen] += 1
            break
        else:
            resueltas.append("")
            counts["sin_etiqueta"] += 1

    # Copia superficial: añadir una columna nueva no toca el DataFrame del
    # llamador, y no se duplican los datos de las que ya existían.
    out = df.copy(deep=False)
    out[_LABEL_COL_RESOLVED] = resueltas

    circular = counts["human"] + counts["llm"] == 0
    if circular:
        log.warning(
            "tech_classifier.circular_labels",
            label_column=_LABEL_COL_RESOLVED,
            counts=counts,
            motivo=(
                "Las columnas independientes existen pero no traen ninguna "
                "etiqueta: todo el entrenamiento cae en keywords y es circular."
            ),
        )
    elif counts["keywords"]:
        log.warning(
            "tech_classifier.partially_circular_labels",
            label_column=_LABEL_COL_RESOLVED,
            counts=counts,
            pct_keywords=round(counts["keywords"] / max(len(df), 1) * 100, 1),
        )
    else:
        log.info("tech_classifier.labels_resolved", label_column=_LABEL_COL_RESOLVED, counts=counts)
    return LabelResolution(df=out, column=_LABEL_COL_RESOLVED, circular=circular, counts=counts)


# ── Split estratificado ───────────────────────────────────────────────────


def _stratification_key(Y: _NDArray) -> list[str]:
    """Firma de la combinación de etiquetas de cada fila (multi-label → clase)."""
    import numpy as np

    return [",".join(str(j) for j in np.flatnonzero(row)) or "__none__" for row in Y]


def _collapse_rare(keys: list[str], min_count: int) -> list[str]:
    """Agrupa en ``__rare__`` las combinaciones con menos de ``min_count`` filas.

    ``train_test_split(stratify=...)`` exige ≥ 2 miembros por clase; sin este
    colapso una sola combinación exótica (p. ej. ``SAP+WORKDAY`` una vez)
    tumbaría la estratificación de todo el dataset.
    """
    from collections import Counter

    counts = Counter(keys)
    return [k if counts[k] >= min_count else "__rare__" for k in keys]


def _split_indices(Y: _NDArray, *, random_state: int = 42) -> _Split:
    """Reparte las filas en train/val/test (60/20/20) estratificando si se puede.

    Tres conjuntos y no dos porque el umbral por etiqueta se **elige** en uno y
    se **reporta** en otro: elegirlo y medirlo en el mismo test set devuelve el
    máximo de una muestra, no una estimación del rendimiento en producción.

    La estratificación es por combinación de etiquetas (ver
    :func:`_stratification_key`). Sin ella, una tecnología del tier ``fragile``
    con ~20 positivos reparte ~4 a validación, y basta un split desafortunado
    para que se quede sin positivos: el umbral degrada en silencio al default.
    Si ``train_test_split`` no puede estratificar se cae a un split aleatorio y
    se registra ``tech_classifier.split_not_stratified``.
    """
    import numpy as np
    from sklearn.model_selection import train_test_split

    n_rows = int(Y.shape[0])
    idx = np.arange(n_rows)
    vacio = np.arange(0)
    if n_rows < _MIN_ROWS_FOR_SPLIT:
        log.warning("tech_classifier.split_skipped", n_rows=n_rows, minimo=_MIN_ROWS_FOR_SPLIT)
        return _Split(idx, vacio, vacio, False, "n_rows_insuficiente")

    estratos = np.asarray(_collapse_rare(_stratification_key(Y), _MIN_STRATUM))
    try:
        trainval, test = train_test_split(
            idx, test_size=0.2, random_state=random_state, stratify=estratos
        )
        train, val = train_test_split(
            trainval, test_size=0.25, random_state=random_state, stratify=estratos[trainval]
        )
        return _Split(train, val, test, True, "")
    except ValueError as exc:
        log.warning(
            "tech_classifier.split_not_stratified",
            n_rows=n_rows,
            error=str(exc),
            impacto="los umbrales de las etiquetas con pocos positivos pueden degradar al default",
        )
        trainval, test = train_test_split(idx, test_size=0.2, random_state=random_state)
        train, val = train_test_split(trainval, test_size=0.25, random_state=random_state)
        return _Split(train, val, test, False, f"stratify_failed: {exc.__class__.__name__}")


class TechnologyClassifier:
    """OneVsRest multi-label sobre las etiquetas de ``TECHNOLOGY_KEYWORDS``.

    No hereda de ni reemplaza a ``SAPClassifier``: convive con él. El
    pipeline puede consultar ambos (binario para ``ml_proba``, multi-label
    para ``ml_tecnologias`` / ``ml_proba_max`` / ``ml_tech_principal``).
    """

    def __init__(self) -> None:
        self.labels: list[str] = list(TECH_LABELS)
        # Modelos por tecnología (sólo para tiers ml_ready y fragile).
        self._models: dict[str, Any] = {}
        # Threshold individual aprendido para cada modelo. El tier rules usa
        # el suyo propio (``_rules_threshold``), no ML_TECH_DEFAULT_THRESHOLD.
        self._thresholds: dict[str, float] = {}
        self._tier: dict[str, str] = {}
        self._fallback_keywords: dict[str, list[str]] = dict(TECHNOLOGY_KEYWORDS)
        self._trained = False
        self.metadata: dict[str, Any] = {}

    # ── Entrenamiento ─────────────────────────────────────────────────────

    def train(self, df: pd.DataFrame, *, label_column: str | None = None) -> dict[str, Any]:
        """Entrena un binario calibrado por tecnología.

        Args:
            df: DataFrame con ``titulo``, ``descripcion`` y al menos una fuente
                de etiquetas. Para que el entrenamiento **no sea circular** debe
                traer ``tecnologia_humana`` (feedback humano) y/o
                ``tecnologia_llm`` (etiquetado LLM, admite ``"SAP:0.9,…"``);
                ``tecnologia`` (keywords) es el último recurso y dispara un
                WARNING porque la escribe el mismo regex que ve el texto.
                Opcionalmente: ``cpv`` e ``importe``.
            label_column: Fuerza la columna de etiquetas y salta la resolución
                automática. Pasar ``"tecnologia"`` es explícitamente circular y
                también avisa.

        Returns:
            Métricas globales y desglose ``per_tech``. Las de ``per_tech`` son
            del **test set** al umbral que se sirve de verdad; el umbral se
            eligió en validación. Si no hay positivos suficientes para ningún
            tier ML, devuelve ``{"error": "no_ml_techs"}``.
        """
        import numpy as np
        from sklearn.metrics import (
            average_precision_score,
            f1_score,
            precision_recall_curve,
        )

        if label_column is not None:
            if label_column not in df.columns:
                return {"error": "missing_tecnologia_column"}
            circular = label_column == _LABEL_COL_KEYWORDS
            if circular:
                log.warning(
                    "tech_classifier.circular_labels",
                    label_column=label_column,
                    motivo="label_column='tecnologia' es la salida de matches_technology()",
                )
            resolution = LabelResolution(df=df, column=label_column, circular=circular, counts={})
        else:
            resolution = _resolver_label_column(df)
            if not resolution.column:
                return {"error": "missing_tecnologia_column"}

        texts, Y, positives = _build_multilabel_dataset(
            resolution.df, self.labels, label_column=resolution.column
        )
        n_rows = len(texts)
        if n_rows < 20:
            return {"error": "insufficient_data", "n_samples": n_rows}

        min_ready = int(getattr(settings, "ML_TECH_MIN_POS_READY", 50))
        min_fragile = int(getattr(settings, "ML_TECH_MIN_POS_FRAGILE", 20))
        fragile_c = float(getattr(settings, "ML_TECH_FRAGILE_C", 0.3))
        fragile_min_precision = float(getattr(settings, "ML_TECH_FRAGILE_MIN_PRECISION", 0.70))
        default_threshold = float(getattr(settings, "ML_TECH_DEFAULT_THRESHOLD", 0.50))

        per_tech: dict[str, dict[str, Any]] = {}
        ml_ready_f1s: list[float] = []

        split = _split_indices(Y, random_state=42)
        X_train = [texts[i] for i in split.train]
        X_val = [texts[i] for i in split.val]
        X_test = [texts[i] for i in split.test]
        Y_test = (
            Y[split.test] if len(split.test) else np.zeros((0, len(self.labels)), dtype=np.int8)
        )
        # Predicciones en test de TODAS las etiquetas (tier rules incluido) al
        # umbral servido: es lo que alimenta el micro/macro-F1 global.
        Y_pred_test = np.zeros_like(Y_test)

        for j, label in enumerate(self.labels):
            n_pos = positives[j]
            y = Y[:, j]
            y_test = y[split.test] if len(split.test) else np.array([], dtype=np.int8)

            # ── Tier rules (sin modelo) ───────────────────────────────────
            fragile = n_pos < min_ready
            tier = _TIER_FRAGILE if fragile else _TIER_ML_READY
            pipe: Any = None
            degradar_a_rules: str | None = None
            if n_pos < min_fragile:
                degradar_a_rules = "fallback_keywords"
            elif len(set(y[split.train])) < 2:
                degradar_a_rules = "train_single_class"
            else:
                try:
                    pipe = _make_tech_pipeline(fragile=fragile, fragile_c=fragile_c)
                    pipe.fit(X_train, y[split.train])
                except Exception as exc:
                    log.warning(
                        "tech_classifier.fit_failed", label=label, tier=tier, error=str(exc)
                    )
                    degradar_a_rules = f"fit_failed: {exc.__class__.__name__}"

            if degradar_a_rules is not None:
                self._tier[label] = _TIER_RULES
                self._thresholds[label] = self._rules_threshold(label)
                served = self._threshold_for(label)
                kws = self._fallback_keywords.get(label, [])
                if len(split.test):
                    Y_pred_test[:, j] = [
                        1 if _keyword_fallback_score(t, kws) >= served else 0 for t in X_test
                    ]
                per_tech[label] = {
                    "tier": _TIER_RULES,
                    "n_positive": n_pos,
                    "threshold": round(served, 4),
                    "note": degradar_a_rules,
                    **self._test_scores(y_test, Y_pred_test[:, j] if len(split.test) else None),
                }
                continue

            # ── Cross-validation F1 (diagnóstico, umbral implícito 0.5) ───
            cv_f1_mean, cv_f1_std = self._cv_f1(
                X_train,
                y[split.train],
                n_pos=n_pos,
                fragile=fragile,
                fragile_c=fragile_c,
                label=label,
            )

            # ── Threshold tuning: SOBRE VALIDACIÓN, nunca sobre test ──────
            chosen_threshold = default_threshold
            f1_val: float | None = None
            y_val = y[split.val] if len(split.val) else np.array([], dtype=np.int8)
            if len(y_val) and len(set(y_val)) >= 2:
                proba_val = pipe.predict_proba(X_val)[:, 1]
                precisions, recalls, thr = precision_recall_curve(y_val, proba_val)
                if len(thr) > 0:
                    p_arr = precisions[:-1]
                    r_arr = recalls[:-1]
                    f1_vals = 2 * p_arr * r_arr / (p_arr + r_arr + 1e-9)
                    if tier == _TIER_FRAGILE:
                        # Priorizar precisión sobre recall en tier frágil
                        valid = p_arr >= fragile_min_precision
                        if valid.any():
                            f1_vals[~valid] = -1.0
                            best = int(np.argmax(f1_vals))
                        else:
                            best = int(np.argmax(p_arr))
                    else:
                        best = int(np.argmax(f1_vals))
                    chosen_threshold = float(thr[best])
                # Clamping — 0.85 cap evita thresholds sobreajustados en datos
                # con separación perfecta donde precision_recall_curve sólo
                # evalúa probabilidades observadas (sin candidatos en el gap).
                chosen_threshold = max(0.30, min(0.85, chosen_threshold))
                f1_val = float(
                    f1_score(y_val, (proba_val >= chosen_threshold).astype(int), zero_division=0)
                )
            else:
                log.warning(
                    "tech_classifier.threshold_sin_validacion",
                    label=label,
                    n_val=len(y_val),
                    threshold=chosen_threshold,
                )

            self._models[label] = pipe
            self._thresholds[label] = chosen_threshold
            self._tier[label] = tier
            # El umbral SERVIDO puede no ser el elegido: ML_TECH_THRESHOLDS
            # tiene prioridad en predicción, así que reportar métricas del
            # elegido sería describir un modelo que no se está sirviendo.
            served = self._threshold_for(label)

            # ── Métricas: SOBRE TEST, al umbral servido ───────────────────
            pr_auc: float | None = None
            if len(split.test):
                proba_test = pipe.predict_proba(X_test)[:, 1]
                Y_pred_test[:, j] = (proba_test >= served).astype(int)
                if len(set(y_test)) >= 2:
                    try:
                        pr_auc = float(average_precision_score(y_test, proba_test))
                    except ValueError as exc:  # test degenerado
                        log.warning("tech_classifier.pr_auc_failed", label=label, error=str(exc))

            entry: dict[str, Any] = {
                "tier": tier,
                "n_positive": n_pos,
                "threshold": round(served, 4),
                "threshold_tuned_on_val": round(chosen_threshold, 4),
                "threshold_overridden": abs(served - chosen_threshold) > 1e-9,
                "pr_auc": round(pr_auc, 4) if pr_auc is not None else None,
                # Diagnósticos que NO corresponden al umbral servido: el CV usa
                # el 0.5 implícito de `predict()` y f1_val es optimista porque
                # el umbral se eligió justo sobre esas filas.
                "f1_cv_mean": round(cv_f1_mean, 4) if cv_f1_mean is not None else None,
                "f1_cv_std": round(cv_f1_std, 4) if cv_f1_std is not None else None,
                "f1_val_tuning": round(f1_val, 4) if f1_val is not None else None,
                **self._test_scores(y_test, Y_pred_test[:, j] if len(split.test) else None),
            }
            per_tech[label] = entry
            if tier == _TIER_ML_READY and entry["f1"] is not None:
                ml_ready_f1s.append(float(entry["f1"]))

        self._trained = True
        n_models = len(self._models)
        n_rules = sum(1 for t in self._tier.values() if t == _TIER_RULES)
        if n_models == 0:
            return {
                "error": "no_ml_techs",
                "per_tech": per_tech,
                "n_samples": n_rows,
                "label_column": resolution.column,
                "labels_circulares": resolution.circular,
            }

        # None y no 0.0 cuando no hay nada medido (sin test set, o sin ninguna
        # etiqueta ml_ready): un 0.0 se lee como "el modelo es pésimo" cuando lo
        # que pasa es que no hay medición.
        macro_f1_ml_ready = float(sum(ml_ready_f1s) / len(ml_ready_f1s)) if ml_ready_f1s else None
        globales = self._global_scores(Y_test, Y_pred_test)
        metrics: dict[str, Any] = {
            # Renombrada: promedia SÓLO las etiquetas del tier con más
            # positivos —un promedio de los aprobados—. La métrica global es
            # macro_f1_all_labels / micro_f1_all_labels.
            "macro_f1_ml_ready_only": (
                round(macro_f1_ml_ready, 4) if macro_f1_ml_ready is not None else None
            ),
            **globales,
            "n_models": n_models,
            "n_rules_fallback": n_rules,
            "n_train": len(X_train),
            "n_val": len(X_val),
            "n_test": len(X_test),
            "n_samples": n_rows,
            "label_column": resolution.column,
            "labels_circulares": resolution.circular,
            "label_source_counts": dict(resolution.counts),
            "split_estratificado": split.stratified,
            "per_tech": per_tech,
        }
        self.metadata = {
            **{k: v for k, v in metrics.items() if k != "per_tech"},
            "trained_at": datetime.now(UTC).isoformat(),
            "labels": list(self.labels),
            "thresholds": dict(self._thresholds),
            "tier": dict(self._tier),
        }
        log.info(
            "tech_classifier.trained",
            macro_f1_ml_ready_only=metrics["macro_f1_ml_ready_only"],
            macro_f1_all_labels=metrics["macro_f1_all_labels"],
            micro_f1_all_labels=metrics["micro_f1_all_labels"],
            labels_circulares=resolution.circular,
            n_models=n_models,
            n_rules_fallback=n_rules,
        )
        return metrics

    # ── Helpers de entrenamiento ──────────────────────────────────────────

    def _cv_f1(
        self,
        X_train: list[str],
        y_train: _NDArray,
        *,
        n_pos: int,
        fragile: bool,
        fragile_c: float,
        label: str,
    ) -> tuple[float | None, float | None]:
        """F1 por cross-validation en train. Diagnóstico, no la métrica servida.

        ``cross_val_score(scoring="f1")`` llama a ``predict()``, así que mide el
        umbral 0.5 implícito de sklearn — no el que se sirve. Se reporta aparte
        (``f1_cv_mean``) precisamente para que no se confunda con ``f1``.
        """
        import numpy as np
        from sklearn.model_selection import (
            RepeatedStratifiedKFold,
            StratifiedKFold,
            cross_val_score,
        )

        if len(set(y_train)) < 2:
            return None, None
        splitter: Any
        if n_pos >= 30:
            splitter = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
        elif n_pos >= 15:
            splitter = RepeatedStratifiedKFold(n_splits=2, n_repeats=3, random_state=42)
        else:
            return None, None
        try:
            scores = cross_val_score(
                _make_tech_pipeline(fragile=fragile, fragile_c=fragile_c),
                X_train,
                y_train,
                cv=splitter,
                scoring="f1",
            )
        except Exception as exc:
            log.warning("tech_classifier.cv_failed", label=label, error=str(exc))
            return None, None
        mean = float(np.mean(scores))
        std = float(np.std(scores))
        log.info(
            "tech_classifier.cv_f1", label=label, cv_f1_mean=round(mean, 4), cv_f1_std=round(std, 4)
        )
        return mean, std

    @staticmethod
    def _test_scores(y_test: _NDArray, y_pred: _NDArray | None) -> dict[str, Any]:
        """P/R/F1 en test al umbral servido, o ``None`` si no hay test set.

        ``support`` es el nº de positivos de la etiqueta en test: sin él, un
        F1 de 0.0 no distingue "el modelo falla" de "no había nada que acertar".
        """
        from sklearn.metrics import f1_score, precision_score, recall_score

        if y_pred is None or len(y_test) == 0:
            return {"f1": None, "precision": None, "recall": None, "support_test": 0}
        return {
            "f1": round(float(f1_score(y_test, y_pred, zero_division=0)), 4),
            "precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
            "recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
            "support_test": int(y_test.sum()),
        }

    def _global_scores(self, Y_test: _NDArray, Y_pred_test: _NDArray) -> dict[str, Any]:
        """Micro-F1 y macro-F1 sobre **todas** las etiquetas, rules incluidas.

        ``macro_f1_ml_ready_only`` promedia sólo el tier con más positivos, que
        son justo las etiquetas fáciles: es un promedio de los aprobados y
        sobreestima el sistema. Estas dos cifras cubren el universo entero,
        cada etiqueta con el score que de verdad se sirve para ella (modelo o
        keywords), que es la única forma de que el número describa lo que el
        usuario recibe.
        """
        import numpy as np
        from sklearn.metrics import f1_score

        if Y_test.shape[0] == 0:
            return {
                "micro_f1_all_labels": None,
                "macro_f1_all_labels": None,
                "macro_f1_labels_con_soporte": None,
                "n_labels": len(self.labels),
                "n_labels_sin_soporte_en_test": len(self.labels),
            }
        soporte = Y_test.sum(axis=0)
        con_soporte = np.flatnonzero(soporte > 0)
        macro_con_soporte = (
            float(
                f1_score(
                    Y_test[:, con_soporte],
                    Y_pred_test[:, con_soporte],
                    average="macro",
                    zero_division=0,
                )
            )
            if len(con_soporte)
            else None
        )
        return {
            "micro_f1_all_labels": round(
                float(f1_score(Y_test, Y_pred_test, average="micro", zero_division=0)), 4
            ),
            "macro_f1_all_labels": round(
                float(f1_score(Y_test, Y_pred_test, average="macro", zero_division=0)), 4
            ),
            "macro_f1_labels_con_soporte": (
                round(macro_con_soporte, 4) if macro_con_soporte is not None else None
            ),
            "n_labels": len(self.labels),
            "n_labels_sin_soporte_en_test": int((soporte == 0).sum()),
        }

    # ── Predicción ────────────────────────────────────────────────────────

    def _score_one(self, augmented_text: str) -> dict[str, float]:
        """Calcula score por tecnología (modelo o fallback rules)."""
        scores: dict[str, float] = {}
        for label in self.labels:
            tier = self._tier.get(label, _TIER_RULES)
            if tier == _TIER_RULES:
                scores[label] = _keyword_fallback_score(
                    augmented_text, self._fallback_keywords.get(label, [])
                )
            else:
                pipe = self._models.get(label)
                if pipe is None:
                    scores[label] = 0.0
                    continue
                try:
                    scores[label] = float(pipe.predict_proba([augmented_text])[0][1])
                except Exception:
                    scores[label] = 0.0
        return scores

    def _rules_threshold(self, label: str) -> float:
        """Umbral del tier ``rules``, con la semántica que el score sí tiene.

        ``_keyword_fallback_score`` devuelve la **fracción** de keywords del
        label presentes en el texto, no una probabilidad: con las ~30 keywords
        de ORACLE, un texto que diga "Oracle Fusion" saca 2/30 = 0.07.
        Compararlo contra ``ML_TECH_DEFAULT_THRESHOLD`` (0.50) exigía que el
        texto contuviera la mitad del vocabulario de la tecnología —
        inalcanzable en la práctica: el tier ``rules`` no clasificaba nada.

        El umbral correcto para "al menos ``k`` keywords presentes" es
        ``(k - 0.5) / n_keywords``: cae estrictamente entre ``(k-1)/n`` y
        ``k/n``, así que no depende de la igualdad exacta de dos divisiones en
        coma flotante. Con el default ``k = 1`` la regla es "al menos una
        keyword", que es exactamente lo que hace ``matches_technology``.

        Se ajusta el umbral en vez de normalizar el score porque el score se
        persiste tal cual en ``licitacion_tecnologia_score.probabilidad``:
        renormalizarlo reescribiría el significado de datos ya escritos y de
        los cortes que otras superficies aplican sobre ellos.
        """
        kws = self._fallback_keywords.get(label, [])
        if not kws:
            return float(getattr(settings, "ML_TECH_DEFAULT_THRESHOLD", 0.50))
        try:
            k = int(getattr(settings, "ML_TECH_RULES_MIN_KEYWORDS", _RULES_MIN_KEYWORDS))
        except (TypeError, ValueError):
            k = _RULES_MIN_KEYWORDS
        k = max(1, min(k, len(kws)))
        return (k - 0.5) / len(kws)

    def _threshold_for(self, label: str) -> float:
        overrides = getattr(settings, "ML_TECH_THRESHOLDS", {}) or {}
        if label in overrides:
            try:
                return float(overrides[label])
            except (TypeError, ValueError):
                pass
        stored = self._thresholds.get(label)
        if stored is not None:
            return float(stored)
        # Sin umbral aprendido: el default de settings es una probabilidad y no
        # significa nada frente a una fracción de keywords (ver _rules_threshold).
        if self._tier.get(label, _TIER_RULES) == _TIER_RULES and self._fallback_keywords.get(label):
            return self._rules_threshold(label)
        return float(getattr(settings, "ML_TECH_DEFAULT_THRESHOLD", 0.50))

    def predict_one(
        self,
        text: str,
        *,
        cpv: str | None = None,
        importe: float | None = None,
    ) -> dict[str, Any]:
        """Devuelve scores, etiquetas predichas, principal y máximo.

        Los scores de las etiquetas en tier ``rules`` son fracciones de
        keywords, no probabilidades, y se comparan contra su propio umbral
        (ver :meth:`_rules_threshold`): no son comparables con los de los
        tiers ML aunque compartan el rango ``[0, 1]``.

        Returns:
            ``{"scores": {label: prob}, "predicted": [label, ...],
               "principal": label_or_none, "max_proba": float,
               "thresholds": {label: thr}, "low_confidence_techs": [label, ...]}``
        """
        if not self._trained:
            raise RuntimeError("TechnologyClassifier no entrenado.")
        augmented = _augment_text(text, cpv=cpv, importe=importe)
        scores = self._score_one(augmented)
        thresholds = {lbl: self._threshold_for(lbl) for lbl in self.labels}
        predicted = [lbl for lbl in self.labels if scores.get(lbl, 0.0) >= thresholds[lbl]]
        predicted.sort(key=lambda lbl: scores.get(lbl, 0.0), reverse=True)
        if predicted:
            principal: str | None = predicted[0]
            max_proba = scores.get(predicted[0], 0.0)
        else:
            principal = None
            # max sobre todos los labels (informativo aunque no pase threshold)
            max_proba = max(scores.values()) if scores else 0.0
        low_conf = [lbl for lbl in predicted if self._tier.get(lbl) == _TIER_FRAGILE]
        return {
            "scores": scores,
            "predicted": predicted,
            "principal": principal,
            "max_proba": float(max_proba),
            "thresholds": thresholds,
            "low_confidence_techs": low_conf,
        }

    def predict_batch(
        self,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Versión vectorizada de ``predict_one``.

        Args:
            items: Lista de dicts con ``text`` (obligatorio), ``cpv`` y
                ``importe`` opcionales.
        """
        if not self._trained:
            raise RuntimeError("TechnologyClassifier no entrenado.")
        if not items:
            return []

        augmented = [
            _augment_text(
                str(item.get("text", "") or ""),
                cpv=item.get("cpv"),
                importe=item.get("importe"),
            )
            for item in items
        ]

        # Score por label en batch (más eficiente que llamadas individuales)
        n = len(augmented)
        per_label_scores: dict[str, list[float]] = {}
        for label in self.labels:
            tier = self._tier.get(label, _TIER_RULES)
            kws = self._fallback_keywords.get(label, [])
            if tier == _TIER_RULES:
                per_label_scores[label] = [_keyword_fallback_score(t, kws) for t in augmented]
            else:
                pipe = self._models.get(label)
                if pipe is None:
                    per_label_scores[label] = [0.0] * n
                    continue
                try:
                    proba = pipe.predict_proba(augmented)
                    per_label_scores[label] = [float(p[1]) for p in proba]
                except Exception:
                    per_label_scores[label] = [0.0] * n

        thresholds = {lbl: self._threshold_for(lbl) for lbl in self.labels}
        results: list[dict[str, Any]] = []
        for i in range(n):
            scores = {lbl: per_label_scores[lbl][i] for lbl in self.labels}
            predicted = sorted(
                (lbl for lbl in self.labels if scores[lbl] >= thresholds[lbl]),
                key=lambda lbl: scores[lbl],
                reverse=True,
            )
            if predicted:
                principal: str | None = predicted[0]
                max_proba = scores[predicted[0]]
            else:
                principal = None
                max_proba = max(scores.values()) if scores else 0.0
            low_conf = [lbl for lbl in predicted if self._tier.get(lbl) == _TIER_FRAGILE]
            results.append(
                {
                    "scores": scores,
                    "predicted": predicted,
                    "principal": principal,
                    "max_proba": float(max_proba),
                    "thresholds": thresholds,
                    "low_confidence_techs": low_conf,
                }
            )
        return results

    # ── Persistencia ──────────────────────────────────────────────────────

    def save(self, path: Path | None = None) -> Path:
        """Persiste el modelo con joblib + checksum SHA256."""
        import joblib

        target = path or _MODEL_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, target, compress=3)
        sha256 = write_checksum(target)
        log.info(
            "tech_classifier.saved",
            path=str(target),
            sha256=sha256[:16],
            n_models=len(self._models),
        )
        return target

    @classmethod
    def load(cls, path: Path | None = None) -> TechnologyClassifier:
        """Carga un modelo serializado con joblib. Lanza FileNotFoundError si no existe.

        Verifica la integridad del fichero (pin out-of-band ML_TECH_MODEL_SHA256
        y/o checksum co-ubicado .sha256) antes de deserializar — ver
        ``shared.model_integrity`` para el razonamiento completo.
        """
        import joblib

        target = path or _MODEL_PATH
        if not target.exists():
            raise FileNotFoundError(f"TechnologyClassifier no encontrado: {target}")

        verify_model_integrity(
            target,
            pinned_sha256=str(getattr(settings, "ML_TECH_MODEL_SHA256", "") or ""),
            pin_setting_name="ML_TECH_MODEL_SHA256",
            model_label="tech_classifier",
            env=str(getattr(settings, "ENV", "dev")),
        )

        obj = joblib.load(target)
        # Aceptar instancias re-importadas vía __main__
        if type(obj).__name__ != cls.__name__:
            raise TypeError(f"El archivo no contiene un TechnologyClassifier: {type(obj)}")
        return obj  # type: ignore[no-any-return]

    @classmethod
    def ensure_downloaded(
        cls,
        path: Path | None = None,
        repo: str = "Dkalds/TenderFlow",
        asset_name: str = "tech_classifier.pkl",
    ) -> bool:
        """Descarga el modelo de la última Release si no está en disco.

        Gemela de ``SAPClassifier.ensure_downloaded``, y por el mismo motivo:
        ``data/models/`` es efímero en los runners de Actions. Su ausencia era
        el agujero más ancho del subsistema — sin este método,
        ``precompute_ml_tecnologias`` no tenía forma alguna de conseguir el
        artefacto y salía ``no_model`` en **todas** las pasadas de
        ``scrape-daily.yml``, no solo desde el 2026-07-27.

        Quien publica el asset es ``.github/workflows/train-tech.yml``.

        Returns:
            True si el modelo está disponible (ya existía o se descargó).
            False si no se pudo resolver — el caller degrada a reglas.
        """
        import os

        from shared.release_assets import (
            download_asset,
            download_checksum_sidecar,
            fetch_latest_release,
            find_asset_id,
        )

        target = path or _MODEL_PATH
        if target.exists():
            log.info("tech_classifier.model_already_local", path=str(target))
            return True

        github_token = os.environ.get("GITHUB_TOKEN", "")
        release = fetch_latest_release(repo, token=github_token)
        if release is None:
            return False
        asset_id = find_asset_id(release, asset_name)
        if asset_id is None:
            return False

        log.info("tech_classifier.downloading_model", asset_id=asset_id, dest=str(target))
        if not download_asset(repo, asset_id, target, token=github_token):
            return False

        pinned = str(getattr(settings, "ML_TECH_MODEL_SHA256", "") or "").strip().lower()
        if pinned:
            import hashlib

            actual = hashlib.sha256(target.read_bytes()).hexdigest().lower()
            if actual != pinned:
                log.error(
                    "tech_classifier.download_hash_mismatch",
                    expected=pinned[:16],
                    got=actual[:16],
                )
                target.unlink(missing_ok=True)
                return False

        if not download_checksum_sidecar(repo, release, target, token=github_token) and not pinned:
            log.warning(
                "tech_classifier.sin_verificacion_de_integridad",
                path=str(target),
                hint=(
                    "la Release no trae el .sha256 del artefacto y ML_TECH_MODEL_SHA256 "
                    "está vacío; con ENV=prod load() rechazará este fichero"
                ),
            )
        log.info("tech_classifier.model_downloaded", path=str(target))
        return True

    @classmethod
    def is_available(cls, path: Path | None = None) -> bool:
        """True si existe un modelo entrenado **en disco**, sin tocar la red.

        Mismo contrato que ``SAPClassifier.is_available``: barato porque lo
        llaman el ingest y la API. Para un runner efímero, :meth:`resolve_artifact`.
        """
        return (path or _MODEL_PATH).exists()

    @classmethod
    def resolve_artifact(cls) -> Path | None:
        """Artefacto servible, bajándolo de la Release si hace falta.

        Hoy nadie registra versiones de ``tech_classifier`` en
        ``model_versions``, así que el primer canal devuelve ``None``. Va por él
        igualmente para que el día que se registre una versión no haya que
        descubrir que este camino no la miraba.

        El tercer canal —:meth:`ensure_downloaded`, el asset de la Release por
        nombre— es el que puede traer el artefacto sin registro. Hoy tampoco
        encuentra nada, porque ``tech_classifier.pkl`` no está publicado: lo
        publica ``.github/workflows/train-tech.yml`` cuando el gate de etiquetas
        no circulares deja de rechazar.
        """
        from shared.model_artifacts import resolve_servable_artifact

        artefacto = resolve_servable_artifact("tech_classifier", _MODEL_PATH)
        if artefacto is not None:
            return artefacto
        return _MODEL_PATH if cls.ensure_downloaded() else None


# ── Entrenamiento desde la BD ─────────────────────────────────────────────


def train_from_db() -> dict[str, Any]:
    """Carga ``licitaciones`` desde la BD y entrena el ``TechnologyClassifier``.

    Persiste el modelo en ``data/models/tech_classifier.pkl`` si tiene al
    menos un tier ML entrenado.

    **Etiquetas no circulares.** La columna ``tecnologia`` la escriben los
    conectores con ``matches_technology()`` sobre el mismo
    ``titulo``/``descripcion`` que después ve el modelo: entrenar contra ella
    es enseñarle a reproducir un regex que ya tenemos. Por eso, además de la
    query base, se traen las dos fuentes independientes vía
    ``LicitacionRepository.etiquetas_tecnologia_no_circulares()`` (el SQL vive
    en ``db/``, ADR-022) y se pasan como columnas ``tecnologia_humana`` y
    ``tecnologia_llm``, que ``_resolver_label_column`` prioriza sobre las
    keywords. Si ninguna aporta datos, ``train()`` sigue funcionando pero emite
    ``tech_classifier.circular_labels``: el entrenamiento es circular y sus
    métricas no significan lo que parecen.

    El parámetro ``db_path`` y el fallback ``sqlite3.connect()`` se retiraron
    con ADR-021: ningún llamador pasaba una ruta, y ese fallback fue el
    vehículo de un bug real —hasta ADR-020 la condición era
    ``is_turso_backend()``, que devolvía ``False`` con Postgres activo, así que
    la función leía siempre un fichero SQLite local vacío en vez de los datos
    reales. Con un solo motor la clase de bug desaparece.
    """
    import pandas as pd

    from db.connection import connect_read

    with connect_read() as conn:
        cols = conn.execute(
            "SELECT id_externo, titulo, descripcion, cpv, importe, "
            "fecha_publicacion, tecnologia, raw_keywords FROM licitaciones"
        ).fetchall()
    # conn.description puede no estar disponible en todos los drivers;
    # forzamos nombres de columnas explícitos en el mismo orden que la query.
    _col_names = [
        "id_externo",
        "titulo",
        "descripcion",
        "cpv",
        "importe",
        "fecha_publicacion",
        "tecnologia",
        "raw_keywords",
    ]
    df = pd.DataFrame([dict(zip(_col_names, row, strict=False)) for row in cols])

    # Etiquetas independientes del regex. Si la consulta falla el
    # entrenamiento sigue (degradando a circular, con su warning), pero no se
    # cae: es una mejora de la etiqueta, no un requisito para entrenar.
    try:
        from db.repositories.licitaciones import LicitacionRepository

        externas = LicitacionRepository().etiquetas_tecnologia_no_circulares()
    except Exception as exc:
        log.warning("tech_classifier.etiquetas_externas_fallidas", error=str(exc))
        externas = {}

    if externas and not df.empty:
        for columna in ("tecnologia_humana", "tecnologia_llm"):
            df[columna] = [
                externas.get(str(ident), {}).get(columna) for ident in df["id_externo"].tolist()
            ]

    log.info(
        "tech_classifier.train_from_db.loaded",
        n_rows=len(df),
        n_etiquetas_externas=len(externas),
    )
    clf = TechnologyClassifier()
    metrics = clf.train(df)
    if "error" not in metrics:
        clf.save()
    return metrics
