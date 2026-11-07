"""Settings de los clasificadores y modelos predictivos (``services/ml/``).

Módulo hermano de ``config/settings.py`` (P3 «Los dos módulos-dios»): ``Settings``
hereda de esta clase, así que los nombres de las variables de entorno y el
acceso (``settings.ML_FBETA``) son los de siempre.

Sin ``model_config`` propio, por lo mismo que ``config/settings_resumen.py``.
"""

from __future__ import annotations

from typing import Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class MLSettings(BaseSettings):
    """Umbrales, tiers, pines de artefactos y modelos predictivos."""

    # ── ML ───────────────────────────────────────────────────────────────
    # Umbral de confianza para clasificar como SAP sin keywords (0.0-1.0)
    ML_CONFIDENCE_THRESHOLD: float = 0.70
    # β para F-beta en el threshold sweep. β>1 favorece recall (FN costoso),
    # β<1 favorece precision. 1.5 prioriza ligeramente recall (perder una
    # licitación SAP cuesta más que una falsa alerta).
    ML_FBETA: float = 1.5
    # Rangos de incertidumbre para la cola de active learning (P(SAP) ∈ [lo, hi]).
    ML_UNCERTAINTY_LO: float = 0.30
    ML_UNCERTAINTY_HI: float = 0.70

    # ── ML Multi-Tecnología (OneVsRest sobre la columna `tecnologia`) ─────
    # Master switch: si False, el pipeline y el scheduler no usan el clasificador
    # multi-tecnología; ml_proba (=P(SAP)) sigue gobernando el gating.
    # Activado en producción (2026-05-23) — requiere TechnologyClassifier en disco.
    # Si el modelo no existe, el pipeline cae silenciosamente a modo keywords.
    ML_TECH_ENABLED: bool = True
    # Prácticas activas para gating extendido. Por defecto sólo SAP, lo que
    # equivale al comportamiento histórico (no se aceptan licitaciones por
    # otras tecnologías hasta que la práctica correspondiente se active).
    ML_TECH_GATING_PRACTICES: list[str] = ["SAP"]
    # Threshold por defecto cuando una tecnología no tiene threshold optimizado.
    ML_TECH_DEFAULT_THRESHOLD: float = 0.50
    # Overrides por tecnología (en JSON via ENV). Si está vacío, se usan los
    # thresholds aprendidos en train() y persistidos en el pickle del modelo.
    ML_TECH_THRESHOLDS: dict[str, float] = {}
    # Tiers según número de positivos por tecnología:
    #   - ml_ready  : ≥ MIN_POS_READY   → LR calibrada normal
    #   - fragile   : ≥ MIN_POS_FRAGILE → LR con C reducido + threshold conservador
    #   - rules     : por debajo        → fallback a keywords curadas
    ML_TECH_MIN_POS_READY: int = 50
    ML_TECH_MIN_POS_FRAGILE: int = 20
    # Regularización LogReg para tier frágil (más fuerte = menos overfit).
    ML_TECH_FRAGILE_C: float = 0.3
    # Precisión mínima exigida al elegir threshold del tier frágil.
    ML_TECH_FRAGILE_MIN_PRECISION: float = 0.70
    # Score mínimo para aceptar una tecnología del etiquetado LLM como etiqueta
    # de entrenamiento. Es la fuente que rompe la circularidad del multi-label
    # (la columna `tecnologia` la escribe el mismo regex que ve el modelo), así
    # que conviene ser exigente: una etiqueta LLM floja es ruido con la
    # apariencia de ground truth. Ver services/ml/tech_classifier.
    ML_TECH_LLM_MIN_SCORE: float = 0.5
    # Keywords mínimas presentes en el texto para que el tier `rules` clasifique.
    # El score de ese tier es la *fracción* de keywords de la tecnología que
    # aparecen, así que compararlo contra ML_TECH_DEFAULT_THRESHOLD (0.50) exigía
    # que el texto contuviera la mitad del vocabulario de la tecnología: en la
    # práctica, el tier no clasificaba nada. Con 1, la semántica es "al menos
    # una keyword", que es lo que el fallback pretendía.
    ML_TECH_RULES_MIN_KEYWORDS: int = 1
    # Si True, train() ejecuta RandomizedSearchCV para buscar hiperparámetros.
    ML_TUNE_ON_TRAIN: bool = False
    # Si True, usa sentence-transformers embeddings como feature adicional en el
    # pipeline ML. Requiere: pip install licitaciones-sap[ml-embeddings]
    ML_USE_EMBEDDINGS: bool = False
    # Golden set etiquetado a mano (JSONL) para evaluación honesta de recall
    # contra labels humanas, independiente del filtro de keywords. Ruta relativa
    # al repo o absoluta. Ver services/ml_eval.py.
    ML_GOLDEN_SET_PATH: str = "tests/fixtures/golden_set.jsonl"
    # PU learning (Positive-Unlabeled): si True, los negativos "ambiguos" (CPV
    # TI 48/72 sin keywords — potenciales SAP no detectados) reciben menor peso
    # de muestra en el entrenamiento, en vez de tratarse como negativos de
    # confianza plena. Reduce el sesgo de aprender el filtro de keywords como
    # ground truth. Ver services/ml/classifier_pipeline._build_dataset.
    ML_PU_LEARNING: bool = False
    # Peso de muestra para los negativos ambiguos cuando ML_PU_LEARNING=True.
    ML_PU_UNLABELED_WEIGHT: float = 0.5
    # Costos relativos para el tuning de threshold sensible a coste. Un falso
    # negativo (perder una licitación SAP real) cuesta más que un falso positivo
    # (revisar una falsa alerta). El golden tuning usa beta = sqrt(FN/FP).
    ML_COST_FN: float = 3.0
    ML_COST_FP: float = 1.0
    # Si True, el threshold final se ajusta sobre el golden set (labels humanas)
    # con costos reales, en lugar de solo sobre el test split (labels derivadas
    # de keywords). Ver services/ml_eval.tune_threshold_on_golden.
    ML_TUNE_THRESHOLD_ON_GOLDEN: bool = True
    # Calibración externa: si True, el pipeline base se construye SIN
    # CalibratedClassifierCV interno y la calibración + tuning de umbral sensible
    # a coste la aplica services.threshold_tuning.calibrate_and_tune (una sola
    # capa, sin doble calibración). Si False (default), el pipeline calibra
    # internamente. Ver SAPClassifier.__init__.
    ML_USE_CALIBRATION: bool = False
    # Si True, _augment_text emite un token estable del órgano de contratación
    # (hash a bucket), permitiendo al modelo aprender que ciertos órganos compran
    # SAP de forma recurrente. Off por defecto para evitar training-serving skew
    # hasta que todos los call sites de predict propaguen el órgano. Ver
    # services/ml/classifier_pipeline._augment_text.
    ML_USE_ORGANO_FEATURE: bool = False
    # Hash SHA256 fijado del modelo (out-of-band). Si se define, load() y
    # ensure_downloaded() verifican el .pkl contra este valor ADEMÁS del checksum
    # .sha256 co-ubicado. Defensa contra un GitHub Release comprometido (donde
    # .pkl y .sha256 podrían sustituirse a la vez, y joblib.load ejecuta código
    # arbitrario). Vacío = sin pin. Ver services/ml/sap_classifier.SAPClassifier.load.
    ML_MODEL_SHA256: str = ""
    # Hash SHA256 fijado (out-of-band) para el TechnologyClassifier
    # (data/models/tech_classifier.pkl). Mismo propósito y semántica que
    # ML_MODEL_SHA256. Vacío = sin pin. Ver
    # services.ml.tech_classifier.TechnologyClassifier.load.
    ML_TECH_MODEL_SHA256: str = ""
    # Hash SHA256 fijado (out-of-band) para el artefacto que cargue BajaModel
    # (desde 2026-09-24 cada versión se publica como
    # `baja_model-<sha256[:12]>.pkl`; `data/models/baja_model.pkl` es solo el
    # default local de `save()`/`load()`). Vacío = sin pin. Ver
    # services.ml.baja_model.BajaModel.load.
    ML_BAJA_MODEL_SHA256: str = ""
    # Mismo pin para el modelo de baja por lote (`baja_model_lote-<sha12>.pkl`).
    ML_BAJA_LOTE_MODEL_SHA256: str = ""
    # Hash SHA256 fijado (out-of-band) para el artefacto que cargue
    # RetencionModel (`retencion_model-<sha256[:12]>.pkl` en las Releases).
    # Vacío = sin pin. Ver services.ml.retencion_model.RetencionModel.load.
    ML_RETENCION_MODEL_SHA256: str = ""

    # ── Modelos predictivos (Fase 6, RFC 20260611-2) ─────────────────────
    # Si True, el re-entrenamiento mensual activa la versión nueva
    # automáticamente cuando bate todas las métricas vs la activa (criterios
    # del RFC). Por defecto la activación es manual (model_registry).
    ML_PRED_AUTO_ACTIVATE: bool = False

    # Conformaliza el intervalo p10-p90 del modelo de baja (split-CQR) sobre un
    # bloque temporal que el ajuste no vio: la cobertura del 80% se cumple por
    # construcción en vez de depender de que los tres cuantiles salgan bien
    # calibrados por su cuenta. Ver services.ml.baja_model._offset_conformal.
    ML_BAJA_CONFORMAL: bool = True
    # Cortes de validación rolling-origin del modelo de baja. 1 reproduce el
    # holdout único anterior.
    ML_BAJA_FOLDS: int = 3
    # Combinaciones de hiperparámetros a explorar (0 = usar solo la base fija).
    ML_BAJA_SEARCH_COMBOS: int = 8
    # Vida media en meses del peso por recencia de las filas de entrenamiento.
    # 0 desactiva el decaimiento (pesos uniformes, comportamiento anterior).
    ML_BAJA_HALFLIFE_MESES: float = 18.0
    # Materializa además una predicción por lote (v140) en el batch nocturno.
    # Apagado por defecto: el agregado por expediente sigue siendo lo que se
    # sirve hasta que `scripts/comparar_baja_por_lote.py` mida que el
    # `mae_p50` por lote mejora (backlog P2 «Modelo de baja por lote»).
    ML_BAJA_POR_LOTE: bool = False
    # Excluye del scoring de retención los vencimientos cuya sucesora ya está
    # adjudicada según la heurística del etiquetado (`retencion_labels._emparejar`).
    # Apagado por defecto: esos casos se detectan y se cuentan siempre
    # (`resueltos_detectados`), pero la heurística da falsos positivos en
    # segmentos con mucha actividad, y excluir un contrato lo deja sin riesgo y
    # lo esconde del orden «score» de Renovaciones. Encenderlo exige auditar
    # antes una muestra a mano, como hace `scripts/audit_retencion.py` con los
    # pares de entrenamiento. Ver services.ml.scoring._separar_resueltos.
    ML_RETENCION_EXCLUIR_RESUELTOS: bool = False

    @field_validator("ML_CONFIDENCE_THRESHOLD", mode="before")
    @classmethod
    def _validate_ml_threshold(cls, v: object) -> float:
        val = float(v)  # type: ignore[arg-type]  # mode="before": v llega crudo y float() es la comprobación
        if not (0.0 <= val <= 1.0):
            raise ValueError("ML_CONFIDENCE_THRESHOLD debe estar entre 0.0 y 1.0")
        return val

    @field_validator("ML_TECH_DEFAULT_THRESHOLD", mode="before")
    @classmethod
    def _validate_ml_tech_default_threshold(cls, v: object) -> float:
        val = float(v)  # type: ignore[arg-type]  # mode="before": v llega crudo y float() es la comprobación
        if not (0.0 <= val <= 1.0):
            raise ValueError("ML_TECH_DEFAULT_THRESHOLD debe estar entre 0.0 y 1.0")
        return val

    @model_validator(mode="after")
    def _validate_ml_uncertainty_range(self) -> Self:
        if self.ML_UNCERTAINTY_LO >= self.ML_UNCERTAINTY_HI:
            raise ValueError(
                f"ML_UNCERTAINTY_LO ({self.ML_UNCERTAINTY_LO}) debe ser menor que "
                f"ML_UNCERTAINTY_HI ({self.ML_UNCERTAINTY_HI})"
            )
        return self
