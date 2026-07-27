"""Clasificador multi-tecnología alineado con la columna ``tecnologia``.

Reemplaza el desalineado ``SAPMultiLabelClassifier`` (Cloud/Integración/RRHH/…)
por un OneVsRest cuyas etiquetas son exactamente las claves de
``TECHNOLOGY_KEYWORDS`` (SAP, SALESFORCE, ORACLE, MICROSOFT, SERVICENOW,
WORKDAY, IBM, OPENTEXT, UNIT4, META4, SOPRA, SAGE, INFOR, …).

Diseño (3 tiers según número de positivos en la BD):

  * ``ml_ready``  (≥ ``ML_TECH_MIN_POS_READY``)  : LR calibrada normal,
    threshold optimizado por F1 en CV (clamp ``[0.30, 0.95]``).
  * ``fragile``   (≥ ``ML_TECH_MIN_POS_FRAGILE``): LR con C reducido y
    threshold conservador (precisión mínima exigida).
  * ``rules``     (resto)                         : fallback a las keywords
    curadas de ``TECHNOLOGY_KEYWORDS`` (mismo featurizer, sin modelo).

``SAPClassifier`` binario y la columna ``ml_proba`` se mantienen intactos por
compatibilidad con el pipeline y dashboard existentes.

Persistencia:
    data/models/tech_classifier.pkl   (joblib, compress=3)
    data/models/tech_classifier.sha256

Uso CLI:
    python -m scraper.ml_classifier train-tech
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import settings
from config.keywords import TECH_LABELS, TECHNOLOGY_KEYWORDS
from observability.logging import get_logger
from scraper.ml_pipeline import (
    _augment_text,
    _build_multilabel_dataset,
    _keyword_fallback_score,
    _make_tech_pipeline,
)

if TYPE_CHECKING:
    import pandas as pd

log = get_logger(__name__)

_MODEL_PATH = Path(__file__).parents[1] / "data" / "models" / "tech_classifier.pkl"
_TIER_ML_READY = "ml_ready"
_TIER_FRAGILE = "fragile"
_TIER_RULES = "rules"


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
        # Threshold individual aprendido para cada modelo. Tier rules usa
        # ``ML_TECH_DEFAULT_THRESHOLD`` aplicado al keyword_fallback_score.
        self._thresholds: dict[str, float] = {}
        self._tier: dict[str, str] = {}
        self._fallback_keywords: dict[str, list[str]] = dict(TECHNOLOGY_KEYWORDS)
        self._trained = False
        self.metadata: dict[str, Any] = {}

    # ── Entrenamiento ─────────────────────────────────────────────────────

    def train(self, df: pd.DataFrame) -> dict[str, Any]:
        """Entrena un binario calibrado por tecnología (silver labels CSV).

        Args:
            df: DataFrame con ``titulo``, ``descripcion``, ``tecnologia`` (CSV),
                opcionalmente ``cpv`` e ``importe``.

        Returns:
            Métricas globales y desglose ``per_tech``. Si no hay positivos
            suficientes para ningún tier ML, devuelve ``{"error": "no_ml_techs"}``.
        """
        import numpy as np
        from sklearn.metrics import (
            average_precision_score,
            f1_score,
            precision_recall_curve,
            precision_score,
            recall_score,
        )
        from sklearn.model_selection import (
            RepeatedStratifiedKFold,
            StratifiedKFold,
            cross_val_score,
            train_test_split,
        )

        if "tecnologia" not in df.columns:
            return {"error": "missing_tecnologia_column"}

        texts, Y, positives = _build_multilabel_dataset(df, self.labels)
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

        # Split global de filas; mantenemos las mismas filas de test para
        # todas las tecnologías (multi-label coherente).
        if n_rows >= 50:
            train_idx, test_idx = train_test_split(
                np.arange(n_rows), test_size=0.2, random_state=42
            )
        else:
            train_idx = np.arange(n_rows)
            test_idx = np.arange(0)  # sin test set fiable
        X_train = [texts[i] for i in train_idx]
        X_test = [texts[i] for i in test_idx]

        for j, label in enumerate(self.labels):
            n_pos = positives[j]

            # ── Tier rules (sin modelo) ───────────────────────────────────
            if n_pos < min_fragile:
                self._tier[label] = _TIER_RULES
                self._thresholds[label] = default_threshold
                per_tech[label] = {
                    "tier": _TIER_RULES,
                    "n_positive": n_pos,
                    "threshold": default_threshold,
                    "f1": None,
                    "precision": None,
                    "recall": None,
                    "note": "fallback_keywords",
                }
                continue

            y = Y[:, j]
            y_train = y[train_idx]
            y_test = y[test_idx] if len(test_idx) else np.array([], dtype=np.int8)

            if len(set(y_train)) < 2:
                # No clases en train: degradar a rules
                self._tier[label] = _TIER_RULES
                self._thresholds[label] = default_threshold
                per_tech[label] = {
                    "tier": _TIER_RULES,
                    "n_positive": n_pos,
                    "threshold": default_threshold,
                    "f1": None,
                    "precision": None,
                    "recall": None,
                    "note": "train_single_class",
                }
                continue

            fragile = n_pos < min_ready
            tier = _TIER_FRAGILE if fragile else _TIER_ML_READY

            try:
                pipe = _make_tech_pipeline(fragile=fragile, fragile_c=fragile_c)
                pipe.fit(X_train, y_train)
            except Exception as exc:
                log.warning(
                    "tech_classifier.fit_failed",
                    label=label,
                    tier=tier,
                    error=str(exc),
                )
                self._tier[label] = _TIER_RULES
                self._thresholds[label] = default_threshold
                per_tech[label] = {
                    "tier": _TIER_RULES,
                    "n_positive": n_pos,
                    "threshold": default_threshold,
                    "f1": None,
                    "precision": None,
                    "recall": None,
                    "note": f"fit_failed: {exc.__class__.__name__}",
                }
                continue

            # ── Cross-validation F1 ───────────────────────────────────────
            cv_f1_mean: float | None = None
            cv_f1_std: float | None = None
            if n_pos >= 30 and len(set(y_train)) >= 2:
                try:
                    cv_splitter = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
                    cv_pipe = _make_tech_pipeline(fragile=fragile, fragile_c=fragile_c)
                    cv_scores = cross_val_score(
                        cv_pipe, X_train, y_train, cv=cv_splitter, scoring="f1"
                    )
                    cv_f1_mean = float(np.mean(cv_scores))
                    cv_f1_std = float(np.std(cv_scores))
                    log.info(
                        "tech_classifier.cv_f1",
                        label=label,
                        cv_f1_mean=round(cv_f1_mean, 4),
                        cv_f1_std=round(cv_f1_std, 4),
                    )
                except Exception as _cv_exc:
                    log.warning("tech_classifier.cv_failed", label=label, error=str(_cv_exc))
            elif n_pos >= 15 and len(set(y_train)) >= 2:
                try:
                    cv_splitter = RepeatedStratifiedKFold(n_splits=2, n_repeats=3, random_state=42)
                    cv_pipe = _make_tech_pipeline(fragile=fragile, fragile_c=fragile_c)
                    cv_scores = cross_val_score(
                        cv_pipe, X_train, y_train, cv=cv_splitter, scoring="f1"
                    )
                    cv_f1_mean = float(np.mean(cv_scores))
                    cv_f1_std = float(np.std(cv_scores))
                    log.info(
                        "tech_classifier.cv_f1",
                        label=label,
                        cv_f1_mean=round(cv_f1_mean, 4),
                        cv_f1_std=round(cv_f1_std, 4),
                    )
                except Exception as _cv_exc:
                    log.warning("tech_classifier.cv_failed", label=label, error=str(_cv_exc))

            # ── Threshold tuning ──────────────────────────────────────────
            chosen_threshold: float = default_threshold
            f1_val: float | None = None
            prec_val: float | None = None
            rec_val: float | None = None
            pr_auc: float | None = None

            if len(y_test) and len(set(y_test)) >= 2:
                proba_test = pipe.predict_proba(X_test)[:, 1]
                try:
                    pr_auc = float(average_precision_score(y_test, proba_test))
                except Exception:
                    pr_auc = None
                precisions, recalls, thr = precision_recall_curve(y_test, proba_test)
                # precision_recall_curve devuelve thr de longitud n-1
                if len(thr) > 0:
                    p_arr = precisions[:-1]
                    r_arr = recalls[:-1]
                    if tier == _TIER_FRAGILE:
                        # Priorizar precisión sobre recall en tier frágil
                        valid = p_arr >= fragile_min_precision
                        if valid.any():
                            f1_vals = 2 * p_arr * r_arr / (p_arr + r_arr + 1e-9)
                            f1_vals[~valid] = -1.0
                            best = int(np.argmax(f1_vals))
                        else:
                            best = int(np.argmax(p_arr))
                    else:
                        f1_vals = 2 * p_arr * r_arr / (p_arr + r_arr + 1e-9)
                        best = int(np.argmax(f1_vals))
                    chosen_threshold = float(thr[best])
                # Clamping — 0.85 cap evita thresholds sobreajustados en datos
                # con separación perfecta donde precision_recall_curve sólo
                # evalúa probabilidades observadas (sin candidatos en el gap).
                chosen_threshold = max(0.30, min(0.85, chosen_threshold))
                y_pred = (proba_test >= chosen_threshold).astype(int)
                try:
                    f1_val = float(f1_score(y_test, y_pred, zero_division=0))
                    prec_val = float(precision_score(y_test, y_pred, zero_division=0))
                    rec_val = float(recall_score(y_test, y_pred, zero_division=0))
                except Exception:
                    pass

            self._models[label] = pipe
            self._thresholds[label] = chosen_threshold
            self._tier[label] = tier
            entry: dict[str, Any] = {
                "tier": tier,
                "n_positive": n_pos,
                "threshold": round(chosen_threshold, 4),
                "f1": round(cv_f1_mean, 4)
                if cv_f1_mean is not None
                else (round(f1_val, 4) if f1_val is not None else None),
                "f1_cv_mean": round(cv_f1_mean, 4) if cv_f1_mean is not None else None,
                "f1_cv_std": round(cv_f1_std, 4) if cv_f1_std is not None else None,
                "f1_single_split": round(f1_val, 4) if f1_val is not None else None,
                "precision": round(prec_val, 4) if prec_val is not None else None,
                "recall": round(rec_val, 4) if rec_val is not None else None,
                "pr_auc": round(pr_auc, 4) if pr_auc is not None else None,
            }
            per_tech[label] = entry
            if tier == _TIER_ML_READY:
                reported_f1 = cv_f1_mean if cv_f1_mean is not None else f1_val
                if reported_f1 is not None:
                    ml_ready_f1s.append(reported_f1)

        self._trained = True
        macro_f1_ml_ready = float(sum(ml_ready_f1s) / len(ml_ready_f1s)) if ml_ready_f1s else 0.0
        n_models = len(self._models)
        n_rules = sum(1 for t in self._tier.values() if t == _TIER_RULES)
        if n_models == 0:
            return {
                "error": "no_ml_techs",
                "per_tech": per_tech,
                "n_samples": n_rows,
            }

        metrics = {
            "macro_f1_ml_ready": round(macro_f1_ml_ready, 4),
            "n_models": n_models,
            "n_rules_fallback": n_rules,
            "n_train": len(X_train),
            "n_test": len(X_test),
            "n_samples": n_rows,
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
            macro_f1_ml_ready=metrics["macro_f1_ml_ready"],
            n_models=n_models,
            n_rules_fallback=n_rules,
        )
        return metrics

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

    def _threshold_for(self, label: str) -> float:
        overrides = getattr(settings, "ML_TECH_THRESHOLDS", {}) or {}
        if label in overrides:
            try:
                return float(overrides[label])
            except (TypeError, ValueError):
                pass
        return float(
            self._thresholds.get(label, getattr(settings, "ML_TECH_DEFAULT_THRESHOLD", 0.50))
        )

    def predict_one(
        self,
        text: str,
        *,
        cpv: str | None = None,
        importe: float | None = None,
    ) -> dict[str, Any]:
        """Devuelve scores, etiquetas predichas, principal y máximo.

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
        sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
        target.with_suffix(".sha256").write_text(sha256, encoding="utf-8")
        log.info(
            "tech_classifier.saved",
            path=str(target),
            sha256=sha256[:16],
            n_models=len(self._models),
        )
        return target

    @classmethod
    def load(cls, path: Path | None = None) -> TechnologyClassifier:
        import joblib

        target = path or _MODEL_PATH
        if not target.exists():
            raise FileNotFoundError(f"TechnologyClassifier no encontrado: {target}")

        # Verificar integridad SHA-256 si el sidecar existe
        sha_path = target.with_suffix(".sha256")
        if sha_path.exists():
            expected = sha_path.read_text(encoding="utf-8").strip()
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(
                    f"Checksum SHA-256 inválido para {target}: "
                    f"esperado={expected[:16]}…, actual={actual[:16]}…"
                )

        obj = joblib.load(target)
        # Aceptar instancias re-importadas vía __main__
        if type(obj).__name__ != cls.__name__:
            raise TypeError(f"El archivo no contiene un TechnologyClassifier: {type(obj)}")
        return obj  # type: ignore[no-any-return]

    @classmethod
    def is_available(cls, path: Path | None = None) -> bool:
        return (path or _MODEL_PATH).exists()


# ── Entrenamiento desde la BD ─────────────────────────────────────────────


def train_from_db(*, db_path: Path | None = None) -> dict[str, Any]:
    """Carga ``licitaciones`` desde la BD activa (Postgres o SQLite local) y
    entrena el ``TechnologyClassifier``.

    Persiste el modelo en ``data/models/tech_classifier.pkl`` si tiene al
    menos un tier ML entrenado.

    ``db_path`` se ignora cuando el proyecto usa Postgres como backend: en ese
    caso se usa ``db.connection.connect_read`` para garantizar que se lee de
    la fuente correcta.

    Antes de ADR-020 la condición era ``is_turso_backend()``, que devolvía
    ``False`` con Postgres activo ("Postgres tiene precedencia" — ver la
    función retirada). Con Postgres en producción, esta función caía siempre
    al fallback ``sqlite3.connect()`` de más abajo, leyendo un fichero SQLite
    local vacío en vez de los datos reales. Ningún test lo detectó porque
    ambos caminos se ejercitaban solo mockeando la condición, nunca contra un
    backend real (ADR-018).
    """
    import pandas as pd

    from db.connection import connect_read, is_postgres_backend

    if db_path is None and is_postgres_backend():
        # Leer desde Postgres vía el pool del proyecto
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
    else:
        import sqlite3

        from config import settings as _settings

        db_file = str(db_path or _settings.DB_PATH)
        with sqlite3.connect(db_file) as conn:
            conn.row_factory = sqlite3.Row
            df = pd.read_sql_query(
                "SELECT id_externo, titulo, descripcion, cpv, importe, "
                "       fecha_publicacion, tecnologia, raw_keywords "
                "FROM licitaciones",
                conn,
            )

    log.info("tech_classifier.train_from_db.loaded", n_rows=len(df))
    clf = TechnologyClassifier()
    metrics = clf.train(df)
    if "error" not in metrics:
        clf.save()
    return metrics
